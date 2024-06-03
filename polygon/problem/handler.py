import json
import shutil
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.db import transaction
from django.utils import timezone

from judge.models import Language, Problem, ProblemData, ProblemGroup, ProblemTranslation, ProblemType, Solution
from .assets import parse_assets
from .statement import parse_statements
from .tests import parse_tests
from .types import ImportContext, ProblemConfig, ProblemProperties
from .utils import asdict_notnull


@transaction.atomic
def save_problem(
    context: ImportContext,
    properties: ProblemProperties,
    config: ProblemConfig,
) -> Problem:
    problem_dict = asdict_notnull(properties)
    problem_dict.pop('translations', None)
    problem_dict.pop('tutorial', None)

    problem, created = Problem.objects.update_or_create(code=properties.code, defaults=problem_dict)

    if created:
        context.logger.info('Created new problem')
    else:
        context.logger.info('Updating existing problem')

    problem.allowed_languages.set(Language.objects.all())
    if context.source.user not in problem.authors.all():
        problem.authors.add(context.source.user)
    if problem.types.count() == 0:
        problem.types.set([ProblemType.objects.order_by('id').first()])  # Uncategorized
    problem.save()

    ProblemTranslation.objects.filter(problem=problem).delete()
    for translation in properties.translations:
        ProblemTranslation.objects.create(
            problem=problem,
            language=translation.language,
            name=translation.name,
            description=translation.description,
        )

    Solution.objects.filter(problem=problem).delete()
    if properties.tutorial:
        Solution.objects.create(
            problem=problem,
            is_public=False,
            publish_on=timezone.now(),
            content=properties.tutorial,
        )

    problem_path = Path(settings.DMOJ_PROBLEM_DATA_ROOT) / problem.code

    with (context.temp_dir / config.archive).open('rb') as f:
        ProblemData.objects.update_or_create(
            problem=problem,
            defaults={
                'problem': problem,
                'zipfile': File(f, name=config.archive),
                'unicode': 'unicode' in (config.hints or []),
            },
        )

    # Should we import TestCases so they will be editable in site?

    problem_path = Path(settings.DMOJ_PROBLEM_DATA_ROOT) / problem.code

    # Save supplementary files
    files = []
    if config.checker:
        files += config.checker.args.files
    if config.interactive:
        files += config.interactive.files
    for file in files:
        shutil.move(context.temp_dir / file, problem_path / file)

    (problem_path / 'init.yml').write_text(json.dumps(asdict_notnull(config)))

    return problem


def cleanup(context: ImportContext, config: ProblemConfig):
    expected_files = ['init.yml', config.archive]
    if config.interactive:
        expected_files += config.interactive.files
    if config.checker:
        expected_files += config.checker.args.files

    problem_path = Path(settings.DMOJ_PROBLEM_DATA_ROOT) / context.source.problem_code

    for file in problem_path.iterdir():
        if file.name not in expected_files:
            if file.is_dir():
                context.logger.info('Removing old directory %s', file.name)
                shutil.rmtree(file)
            else:
                context.logger.info('Removing old file %s', file.name)
                file.unlink()


def handle_import(context: ImportContext) -> Problem:
    revision = context.descriptor.get('revision')
    context.logger.info('Importing problem revision %s', revision)

    config = parse_tests(context)
    parse_assets(context, config)
    statements = parse_statements(context)

    main_language = settings.LANGUAGE_CODE.split('-')[0]
    main_statement = next((s for s in statements if s.language == main_language), None)
    if main_statement is None:
        main_statement = statements[0]
        context.logger.info('Statement in %s not found, using %s as main', main_language, main_statement.language)

    other_statements = [s for s in statements if s.language is not None and s.language != main_statement.language]

    tutorials = '\n\n----\n\n'.join(s.tutorial for s in [main_statement] + other_statements if s.tutorial)

    testset = context.descriptor.find('.//testset[@name="tests"]')
    memory_limit = int(testset.find('memory-limit').text) // 1024  # in KB
    if hasattr(settings, 'DMOJ_PROBLEM_MIN_MEMORY_LIMIT'):
        memory_limit = max(memory_limit, settings.DMOJ_PROBLEM_MIN_MEMORY_LIMIT)
    if hasattr(settings, 'DMOJ_PROBLEM_MAX_MEMORY_LIMIT'):
        memory_limit = min(memory_limit, settings.DMOJ_PROBLEM_MAX_MEMORY_LIMIT)

    total_points = sum(case['points'] for case in config.test_cases)
    if total_points == 0:
        context.logger.info('No points configured, treating problem as non-partial')
        partial = False
        total_points = 1.0
        config.test_cases[-1]['points'] = 1  # Add score for the last test
    else:
        context.logger.info('Points configured, treating problem as partial')
        partial = True

    properties = ProblemProperties(
        code=context.source.problem_code,
        name=main_statement.name,
        time_limit=float(testset.find('time-limit').text) / 1000,  # in s
        memory_limit=memory_limit,
        description=main_statement.description,
        partial=partial,
        points=total_points,
        translations=other_statements,
        tutorial=tutorials,
        group=ProblemGroup.objects.order_by('id').first(),  # Uncategorized
    )

    problem = save_problem(context, properties, config)
    cleanup(context, config)
    return problem
