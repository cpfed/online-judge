import json
import shutil
from pathlib import Path
from typing import List

from django.conf import settings
from django.core.files import File
from django.core.files.storage import default_storage
from django.db import transaction
from django.utils import timezone

from judge.models import Language, Problem, ProblemData, ProblemGroup, ProblemTranslation, ProblemType, Solution, \
    Submission, SubmissionSource
from .assets import parse_assets
from .constants import POLYGON_COMPILERS
from .exceptions import ProblemImportError
from .statement import parse_statements
from .tests import parse_tests
from .types import ImportContext, MainSolution, ProblemConfig, ProblemProperties, Statement
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
    if context.source.author not in problem.authors.all():
        problem.authors.add(context.source.author)
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


def prepare_properties(context: ImportContext, config: ProblemConfig, statements: List[Statement]) -> ProblemProperties:
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
        context.logger.info('No points configured, adding 1 point for the last testcase')
        partial = False
        total_points = 1.0
        config.test_cases[-1]['points'] = 1  # Add score for the last test
    else:
        context.logger.info('Found points, total score: %s', total_points)
        partial = True

    return ProblemProperties(
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


def cleanup(context: ImportContext, config: ProblemConfig):
    # Cleanup judge directory
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

    # Cleanup media directory
    if default_storage.exists(f'problems/{context.source.problem_code}'):
        for item in default_storage.listdir(f'problems/{context.source.problem_code}')[0]:
            if item != context.upload_id:
                shutil.rmtree(default_storage.path(f'problems/{context.source.problem_code}/{item}'), ignore_errors=True)


def judge_main_submission(context: ImportContext, problem: Problem) -> None:
    def get_package_submission() -> MainSolution | None:
        main_solution = context.descriptor.find('.//solution[@tag="main"]')
        if main_solution is None:
            context.logger.warning('Problem has no main correct solution')
            return None

        source_tag = main_solution.find('source')
        if source_tag is None:
            raise ProblemImportError('No source for main solution')

        language = source_tag.get('type')
        if language not in POLYGON_COMPILERS:
            context.logger.warning('Main solution has unsupported type %s, skipping...', language)
            return None

        source_file = context.package.read(source_tag.get('path'))
        try:
            source_file = source_file.decode()
        except UnicodeDecodeError:
            context.logger.warning('Main solution is not a valid Unicode file, skipping...')
            return None

        return MainSolution(POLYGON_COMPILERS[language], source_file)

    def get_cached_submission() -> MainSolution | None:
        if context.source.main_submission is None:
            return None

        submission = context.source.main_submission
        return MainSolution(submission.language.key, submission.source.source)

    package_submission = get_package_submission()
    if package_submission is None:
        return

    cached_submission = get_cached_submission()

    if cached_submission != package_submission:
        context.logger.info('Submitting main correct solution')
        with transaction.atomic():
            submission = Submission.objects.create(
                problem=problem,
                user=context.author,
                language=Language.objects.get(key=package_submission.language),
            )
            SubmissionSource.objects.create(
                submission=submission,
                source=package_submission.source,
            )

        context.source.main_submission = submission
        context.source.save()

        context.source.main_submission.judge(force_judge=True)
    else:
        context.logger.info('Main correct solution is not changed, rejudging')
        context.source.main_submission.judge(force_judge=True, rejudge=True, rejudge_user=context.author.user)


def handle_import(context: ImportContext):
    revision = context.descriptor.get('revision')
    context.logger.info('Importing problem revision %s', revision)

    context.task.report('Processing testsets')
    config = parse_tests(context)
    context.task.report('Processing assets')
    parse_assets(context, config)

    try:
        context.task.report('Processing statements')
        statements = parse_statements(context)

        context.task.report('Saving problem')
        properties = prepare_properties(context, config, statements)

        problem = save_problem(context, properties, config)

        context.source.problem = problem
        context.source.save()
    except:  # noqa: E722, we need cleanup for every failure including KeyboardInterrupt
        try:
            shutil.rmtree(default_storage.path(f'problems/{context.source.problem_code}/{context.upload_id}'))
        except FileNotFoundError:
            pass
        raise

    cleanup(context, config)

    judge_main_submission(context, problem)
