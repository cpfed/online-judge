import io
import json
import logging
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZipFile

from django.conf import settings
from django.forms import modelform_factory
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone
from django.utils.translation import get_language, override
from esep.statement_languages import resolve_statement
from lxml import etree

from judge.admin.problem import ProblemTranslationForm
from judge.models import ProblemGroup, ProblemTranslation, ProblemType
from judge.models.problem import disallowed_characters_validator
from judge.models.tests.util import CommonDataMixin, create_contest, create_contest_problem, create_problem
from judge.views.api.api_esep import APIContestProblemDetail, APIContestProblems
from polygon.problem.handler import prepare_properties, save_problem
from polygon.problem.statement import parse_statements
from polygon.problem.types import ProblemConfig


@override_settings(LANGUAGE_CODE='en')
class StatementLanguageTestCase(CommonDataMixin, TestCase):
    def make_package(self, languages):
        descriptor = etree.Element('problem')
        names = etree.SubElement(descriptor, 'names')
        blocks = etree.SubElement(descriptor, 'statements')
        testset = etree.SubElement(descriptor, 'testset', name='tests')
        etree.SubElement(testset, 'time-limit').text = '1000'
        etree.SubElement(testset, 'memory-limit').text = str(256 * 1024 * 1024)
        data = io.BytesIO()
        archive = ZipFile(data, 'w')
        self.addCleanup(archive.close)
        for language in languages:
            etree.SubElement(names, 'name', language=language, value=f'{language} title')
            etree.SubElement(blocks, 'statement', language=language, type='application/x-tex',
                             path=f'{language}/statement.tex')
            archive.writestr(f'{language}/problem-properties.json', json.dumps({
                'legend': f'{language} legend $a+b$',
                'input': 'Input body', 'output': 'Output body', 'interaction': 'Interaction body',
                'scoring': 'Scoring body', 'notes': 'Notes body',
                'sampleTests': [{'input': '1 2', 'output': '3'}],
            }))
        return SimpleNamespace(
            descriptor=descriptor, package=archive, logger=logging.getLogger(__name__),
            source=SimpleNamespace(problem_code='uzsample', author=self.users['normal'].profile),
        )

    def test_polygon_language_sets_and_primary_selection(self):
        ProblemGroup.objects.get_or_create(name='group', defaults={'full_name': 'Group'})
        config = ProblemConfig(archive='tests.zip', test_cases=[{'points': 100}])
        for languages, expected_primary, codes in [
            (['russian', 'english', 'kazakh', 'uzbek'], 'english', {'ru', 'en', 'kk', 'uz'}),
            (['uzbek'], 'uzbek', {'uz'}),
            (['uz'], 'uz', {'uz'}),
            (['russian', 'uzbek'], 'russian', {'ru', 'uz'}),
        ]:
            with self.subTest(languages=languages):
                context = self.make_package(languages)
                statements = parse_statements(context)
                properties = prepare_properties(context, config, statements)
                self.assertEqual(properties.name, f'{expected_primary} title')
                self.assertEqual({item.language for item in properties.translations}, codes)
                uz = next(item for item in statements if item.language == 'uz')
                self.assertIn('Kiruvchi maʼlumotlar', uz.description)
                self.assertIn('Chiquvchi maʼlumotlar', uz.description)
                self.assertIn('Oʻzaro aloqa', uz.description)
                self.assertIn('Baholash', uz.description)
                self.assertIn('Misollar', uz.description)
                self.assertIn('Izohlar', uz.description)
                self.assertIn('### Kiruvchi maʼlumotlar 1\n', uz.description)
                self.assertIn('### Chiquvchi maʼlumotlar 1\n', uz.description)
                self.assertIn('1 2', uz.description)
                self.assertIn('a+b', uz.description)
                disallowed_characters_validator(uz.description)

    def test_statement_language_is_independent_of_active_language(self):
        with override('ru'):
            statements = parse_statements(self.make_package(['uzbek', 'english']))
            descriptions = {item.language: item.description for item in statements}
            self.assertIn('## Kiruvchi maʼlumotlar\n', descriptions['uz'])
            self.assertIn('## Input\n', descriptions['en'])
            self.assertNotIn('Kiruvchi maʼlumotlar', descriptions['en'])
            self.assertEqual(get_language(), 'ru')

    def test_reimport_preserves_primary_translation_and_admin_editing(self):
        ProblemGroup.objects.get_or_create(name='group', defaults={'full_name': 'Group'})
        ProblemType.objects.get_or_create(name='type', defaults={'full_name': 'Type'})
        config = ProblemConfig(archive='tests.zip', test_cases=[{'points': 100}])
        context = self.make_package(['uzbek'])
        properties = prepare_properties(context, config, parse_statements(context))
        with TemporaryDirectory() as directory, override_settings(DMOJ_PROBLEM_DATA_ROOT=directory):
            context.temp_dir = Path(directory)
            (context.temp_dir / config.archive).write_bytes(b'test fixture')
            (context.temp_dir / properties.code).mkdir()
            # Exercise the real ORM import; problem data upload is unrelated to statement storage.
            with patch('polygon.problem.handler.ProblemData.objects.update_or_create'):
                problem = save_problem(context, properties, config)
                properties.translations[0].description += '\nUpdated'
                properties.description = properties.translations[0].description
                problem = save_problem(context, properties, config)
            self.assertEqual(problem.translations.count(), 1)
            translated = problem.translations.get(language='uz')
            self.assertIn('Updated', translated.description)
            self.assertEqual(problem.description, translated.description)
            self.assertEqual(resolve_statement(problem, 'ru')['language'], 'uz')
            form_class = modelform_factory(
                ProblemTranslation, form=ProblemTranslationForm, fields=('language', 'name', 'description'),
            )
            form = form_class(data={
                'language': 'uz', 'name': 'Tahrirlangan', 'description': translated.description,
            }, instance=translated)
            self.assertTrue(form.is_valid(), form.errors)
            form.save()
            self.assertEqual(resolve_statement(problem, 'uz')['name'], 'Tahrirlangan')

    def test_exact_base_language_and_legacy_fallback(self):
        problem = create_problem('fallback', name='Original', description='Original body')
        self.assertEqual(resolve_statement(problem, 'uz')['language'], 'en')
        for language in ['ru', 'kk']:
            ProblemTranslation.objects.create(
                problem=problem, language=language, name=problem.name, description=problem.description,
            )
        self.assertEqual(resolve_statement(problem, 'uz')['language'], 'kk')
        ProblemTranslation.objects.create(
            problem=problem, language='en', name=problem.name, description=problem.description,
        )
        self.assertEqual(resolve_statement(problem, 'uz')['language'], 'en')
        ProblemTranslation.objects.create(problem=problem, language='uz', name='Uzbek', description='Uzbek body')
        self.assertEqual(resolve_statement(problem, 'uz-Latn'), {
            'name': 'Uzbek', 'description': 'Uzbek body', 'language': 'uz', 'translated': True,
        })

    @override_settings(CPFED_TOKEN='local-test-token')
    def test_contest_api_language_and_access_checks(self):
        problem = create_problem('apitest', name='Original', description='Original body')
        ProblemTranslation.objects.create(problem=problem, language='uz', name='Masala', description='Shart')
        contest = create_contest('uzround', end_time=timezone.now() - timezone.timedelta(hours=1))
        create_contest_problem(contest=contest, problem=problem)
        factory = RequestFactory()
        request = factory.get('/', {'language': 'uz'}, HTTP_AUTHORIZATION=f'Bearer {settings.CPFED_TOKEN}')
        detail = APIContestProblemDetail.as_view()
        response = detail(request, contest_key=contest.key, problem_code=problem.code)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)['language'], 'uz')
        response = APIContestProblems.as_view()(request, contest_key=contest.key)
        self.assertEqual(json.loads(response.content)['problems'][0]['name'], 'Masala')
        self.assertEqual(detail(factory.get('/'), contest_key=contest.key, problem_code=problem.code).status_code, 401)
        contest.end_time = timezone.now() + timezone.timedelta(hours=1)
        contest.save()
        self.assertEqual(detail(request, contest_key=contest.key, problem_code=problem.code).status_code, 403)
