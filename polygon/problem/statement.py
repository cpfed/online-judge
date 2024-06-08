import hashlib
import json
import os
import re
import subprocess
import tempfile
from typing import Any, List

from django.conf import settings
from django.core.files.storage import default_storage
from django.utils.translation import gettext as _, override

from .exceptions import ProblemImportError
from .types import ImportContext, Statement

POLYGON_TO_DMOJ_LANG = {
    'catalan': 'ca',
    'german': 'de',
    'greek': 'el',
    'english': 'en',
    'spanish': 'es',
    'french': 'fr',
    'croatian': 'hr',
    'hungarian': 'hu',
    'japanese': 'ja',
    'kazakh': 'kk',
    'korean': 'ko',
    'portuguese': 'pt',
    'romanian': 'ro',
    'russian': 'ru',
    'serbian': 'sr-latn',
    'turkish': 'tr',
    'vietnamese': 'vi',
    'chinese': 'zh-hans',
}

PANDOC_FILTER = r"""
local function normalize_quote(text)
    -- These four quotes are disallowed characters.
    -- See DMOJ_PROBLEM_STATEMENT_DISALLOWED_CHARACTERS
    text = text:gsub('\u{2018}', "'") -- left single quote
    text = text:gsub('\u{2019}', "'") -- right single quote
    text = text:gsub('\u{201C}', '"') -- left double quote
    text = text:gsub('\u{201D}', '"') -- right double quote
    text = text:gsub('<<', '\u{00AB}') -- russian left quote
    text = text:gsub('>>', '\u{00BB}') -- russian right quote
    return text
end

local function escape_html_content(text)
    -- Escape HTML/Markdown/MathJax syntax characters
    text = text:gsub('&', '&amp;') -- must be first
    text = text:gsub('<', "&lt;")
    text = text:gsub('>', "&gt;")
    text = text:gsub('*', '\\*')
    text = text:gsub('_', '\\_')
    text = text:gsub('%$', '<span>%$</span>')
    text = text:gsub('~', '<span>~</span>')
    return text
end

function Math(m)
    -- Fix math delimiters
    local delimiter = m.mathtype == 'InlineMath' and '~' or '$$'
    return pandoc.RawInline('html', delimiter .. m.text .. delimiter)
end

function Image(el)
    -- And blank lines before and after the image for caption to work
    return {pandoc.RawInline('markdown', '\n\n'), el, pandoc.RawInline('markdown', '\n\n')}
end

function Code(el)
    -- Normalize quotes and render similar to Codeforces
    local text = normalize_quote(el.text)
    text = escape_html_content(text)
    return pandoc.RawInline('html', '<span style="font-family: courier new,monospace;">' .. text .. '</span>')
end

function CodeBlock(el)
    -- Normalize quotes
    el.text = normalize_quote(el.text)

    -- Set language to empty string if it's nil
    -- This is a hack to force backtick code blocks instead of indented code blocks
    -- See https://github.com/jgm/pandoc/issues/7033
    if el.classes[1] == nil then
        el.classes[1] = ''
    end

    return el
end

function Quoted(el)
    -- Normalize quotes
    local quote = el.quotetype == 'SingleQuote' and "'" or '"'
    local inlines = el.content
    table.insert(inlines, 1, quote)
    table.insert(inlines, quote)
    return inlines
end

function Str(el)
    -- Normalize quotes
    el.text = normalize_quote(el.text)

    -- en dash/em dash/non-breaking space would still show up correctly if we don't escape them,
    -- but they would be hardly noticeable while editing.
    local res = {}
    local part = ''
    for c in el.text:gmatch(utf8.charpattern) do
        if c == '\u{2013}' then
            -- en dash
            if part ~= '' then
                table.insert(res, pandoc.Str(part))
                part = ''
            end
            table.insert(res, pandoc.RawInline('html', '&ndash;'))
        elseif c == '\u{2014}' then
            -- em dash
            if part ~= '' then
                table.insert(res, pandoc.Str(part))
                part = ''
            end
            table.insert(res, pandoc.RawInline('html', '&mdash;'))
        elseif c == '\u{00A0}' then
            -- Non-breaking space
            if part ~= '' then
                table.insert(res, pandoc.Str(part))
                part = ''
            end
            table.insert(res, pandoc.RawInline('html', '&nbsp;'))
        else
            part = part .. c
        end
    end
    if part ~= '' then
        table.insert(res, pandoc.Str(part))
    end

    return res
end

function Div(el)
    if el.classes[1] == 'center' then
        local res = {}
        table.insert(res, pandoc.RawBlock('markdown', '<' .. el.classes[1] .. '>'))
        for _, block in ipairs(el.content) do
            table.insert(res, block)
        end
        table.insert(res, pandoc.RawBlock('markdown', '</' .. el.classes[1] .. '>'))
        return res

    elseif el.classes[1] == 'epigraph' then
        local filter = {
            Math = Math,
            Code = Code,
            Quoted = Quoted,
            Str = Str,
            Para = function (s)
                return pandoc.Plain(s.content)
            end,
            Span = function (s)
                return s.content
            end
        }

        function renderHTML(el)
            local doc = pandoc.Pandoc({el})
            local rendered = pandoc.write(doc:walk(filter), 'html')
            return pandoc.RawBlock('markdown', rendered)
        end

        local res = {}
        table.insert(res, pandoc.RawBlock('markdown', '<div style="margin-left: 67%;">'))
        if el.content[1] then
            table.insert(res, renderHTML(el.content[1]))
        end
        table.insert(res, pandoc.RawBlock('markdown', '<div style="border-top: 1px solid #888;"></div>'))
        if el.content[2] then
            table.insert(res, renderHTML(el.content[2]))
        end
        table.insert(res, pandoc.RawBlock('markdown', '</div>'))
        return res
    end

    return nil
end
"""

# Polygon uses some custom macros: https://polygon.codeforces.com/docs/statements-tex-manual
# For example, \bf is deprecated in modern LaTeX, but Polygon treats it the same as \textbf
# and recommends writing \bf{...} instead of \textbf{...} for brevity.
# Similar for \it, \tt, \t
# We just redefine them to their modern counterparts.
# Note that this would break {\bf abcd}, but AFAIK Polygon never recommends that so it's fine.
TEX_MACROS = r"""
\renewcommand{\bf}{\textbf}
\renewcommand{\it}{\textit}
\renewcommand{\tt}{\texttt}
\renewcommand{\t}{\texttt}
"""


def pandoc_tex_to_markdown(tex: str) -> str:
    tex = TEX_MACROS + tex
    with tempfile.TemporaryDirectory() as tmp_dir:
        with open(os.path.join(tmp_dir, 'temp.tex'), 'w', encoding='utf-8') as f:
            f.write(tex)

        with open(os.path.join(tmp_dir, 'filter.lua'), 'w', encoding='utf-8') as f:
            f.write(PANDOC_FILTER)

        subprocess.run(
            ['pandoc', '--lua-filter=filter.lua', '-t', 'gfm', '-o', 'temp.md', 'temp.tex'],
            cwd=tmp_dir,
            check=True,
        )

        with open(os.path.join(tmp_dir, 'temp.md'), 'r', encoding='utf-8') as f:
            md = f.read()

    return md


def pandoc_get_version() -> tuple[int, int, int]:
    parts = subprocess.check_output(['pandoc', '--version']).decode().splitlines()[0].split(' ')[1].split('.')
    return tuple(map(int, parts))


def process_images(context: ImportContext, statement_folder: str, text: str) -> str:
    def save_image(image_path: str) -> str:
        if len(context.image_cache) == 0:
            os.makedirs(
                default_storage.path(f'problems/{context.source.problem_code}/{context.upload_id}'),
                exist_ok=True,
            )

        norm_path = os.path.normpath(os.path.join(statement_folder, image_path))
        sha1 = hashlib.sha1(context.package.read(norm_path)).hexdigest()

        if sha1 not in context.image_cache:
            path = f'problems/{context.source.problem_code}/{context.upload_id}/{sha1}_{os.path.basename(image_path)}'
            with context.package.open(norm_path, 'r') as image_source:
                default_storage.save(path, image_source)

            url = settings.MEDIA_URL
            if not url.endswith('/'):
                url = url + '/'
            url += path
            context.image_cache[sha1] = url

        return context.image_cache[sha1]

    for image_path in set(re.findall(r'!\[image\]\((.+?)\)', text)):
        text = text.replace(
            f'![image]({image_path})',
            f'![image]({save_image(image_path)})',
        )

    for img_tag in set(re.findall(r'<\s*img[^>]*>', text)):
        image_path = re.search(r'<\s*img[^>]+src\s*=\s*(["\'])(.*?)\1[^>]*>', img_tag).group(2)
        text = text.replace(
            img_tag,
            img_tag.replace(image_path, save_image(image_path)),
        )

    return text


def parse_problem_properties(language: str, problem_properties: dict[str, Any]) -> str:
    def header(text: str, level: int = 2) -> str:
        return f'\n{"#" * level} {text}\n\n'

    with override(language):
        description = pandoc_tex_to_markdown(problem_properties['legend'])

        if problem_properties['input']:
            description += header(_('Input'))
            description += pandoc_tex_to_markdown(problem_properties['input'])

        if problem_properties['output']:
            description += header(_('Output'))
            description += pandoc_tex_to_markdown(problem_properties['output'])

        if problem_properties['interaction']:
            description += header(_('Interaction'))
            description += pandoc_tex_to_markdown(problem_properties['interaction'])

        if problem_properties['scoring']:
            description += header(_('Scoring'))
            description += pandoc_tex_to_markdown(problem_properties['scoring'])

        if problem_properties['sampleTests']:
            description += header(_('Samples'))
            for i, sample in enumerate(problem_properties['sampleTests'], start=1):
                description += header(_('Input {}').format(i), level=3)
                description += '```\n' + sample['input'].strip() + '\n```\n'
                description += header(_('Output {}').format(i), level=3)
                description += '```\n' + sample['output'].strip() + '\n```\n'

        if problem_properties['notes']:
            description += header(_('Notes'))
            description += pandoc_tex_to_markdown(problem_properties['notes'])

        return description


def parse_statements(context: ImportContext) -> List[Statement]:
    statements: List[Statement] = []

    statement_blocks = context.descriptor.findall('.//statement[@type="application/x-tex"]')

    if len(statement_blocks) == 0:
        context.logger.warning('Statement not found, skipping...')
        try:
            name = context.descriptor.find('.//name').get('value')
        except AttributeError:
            name = None
        return Statement(name=name or 'Unnamed')

    existing_languages = set()

    for statement_block in statement_blocks:
        origin_language = statement_block.get('language', 'unknown')
        if origin_language not in POLYGON_TO_DMOJ_LANG:
            context.logger.warning(
                "Unknown language %s. Statement will be saved, but it's never to be shown",
                origin_language,
            )
        language = POLYGON_TO_DMOJ_LANG.get(origin_language, origin_language)

        if language in existing_languages:
            context.logger.warning('Duplicate language %s, skipping...', language)
            continue

        existing_languages.add(language)

        context.logger.info('Adding statement in %s', language)

        statement_folder = os.path.dirname(statement_block.get('path'))
        problem_properties_path = os.path.join(statement_folder, 'problem-properties.json')
        if problem_properties_path not in context.package.namelist():
            raise ProblemImportError(f'problem-properties.json not found at path {problem_properties_path}')

        problem_properties = json.loads(context.package.read(problem_properties_path).decode('utf-8'))

        description = parse_problem_properties(language, problem_properties)
        description = process_images(context, statement_folder, description)

        name_element = context.descriptor.find(f'.//name[@language="{origin_language}"]')
        name = name_element.get('value') if name_element is not None else ''

        tutorial = problem_properties.get('tutorial')
        if isinstance(tutorial, str) and tutorial != '':
            tutorial = pandoc_tex_to_markdown(tutorial)
            tutorial = process_images(context, statement_folder, tutorial)
        else:
            tutorial = None

        statements.append(
            Statement(
                language=language,
                name=name,
                description=description,
                tutorial=tutorial,
            ),
        )

    return statements
