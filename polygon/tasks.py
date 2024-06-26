import io
import logging
import random
import tempfile
import zipfile
from pathlib import Path

from celery import shared_task
from celery.app.task import Task
from lxml import etree as ET

from judge.models import Problem, Profile
from . import api
from .models import ProblemSource, ProblemSourceImport
from .problem import ImportContext, ProblemImportError, TaskReporter, handle_import

__all__ = 'import_problem'


def prepare_archive(logger: logging.Logger, problem_id: int, path: Path) -> None:
    problem = api.get_problem(problem_id)

    if problem.latestPackage is None:
        raise ProblemImportError('No packages generated for problem')

    packages = api.get_problem_packages(problem_id)

    linux_package = next((p for p in packages if p.revision == problem.latestPackage and p.type == 'linux'), None)
    if linux_package is None:
        raise ProblemImportError('Only Standard package is generated for the latest revision. Generate Full package.')

    if linux_package.state != 'READY':
        raise ProblemImportError('Latest package is not ready for download')

    api.save_package(problem_id, linux_package.id, path)

    if problem.latestPackage != problem.revision:
        logger.warning('There is no package for latest revision %s', problem.revision)


@shared_task(bind=True)
def import_problem(self: Task, problem_source_id: int, profile_id: int):
    problem_source = ProblemSource.objects.get(id=problem_source_id)
    author = Profile.objects.get(id=profile_id)
    problem_import = ProblemSourceImport(problem_source=problem_source, author=author)
    problem_import.save()

    log_stream = io.StringIO()
    log_handler = logging.StreamHandler(log_stream)
    log_handler.setFormatter(logging.Formatter('%(levelname)s:%(message)s'))
    logger = logging.getLogger(f'polygon:import-{problem_source_id}')
    logger.setLevel(logging.DEBUG)
    logger.addHandler(log_handler)

    task = TaskReporter(self)

    try:
        problem_code = problem_source.problem_code
        Problem._meta.get_field('code').run_validators(problem_code)  # Just to ensure nothing broke
        if problem_source.problem is None and Problem.objects.filter(code=problem_code).exists():
            raise ProblemImportError(f'Problem with code {problem_code} already exists')

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            archive_path = temp_dir / 'archive.zip'

            task.report('Downloading problem archive')
            prepare_archive(logger, problem_source.polygon_id, archive_path)

            with zipfile.ZipFile(archive_path) as package:
                if 'problem.xml' not in package.namelist():
                    raise ProblemImportError('problem.xml not found')

                context = ImportContext(
                    source=problem_source,
                    task=task,
                    author=author,
                    package=package,
                    descriptor=ET.fromstring(package.read('problem.xml')),
                    logger=logger,
                    temp_dir=temp_dir,
                    upload_id=random.randbytes(4).hex(),
                )

                handle_import(context)
    except Exception as exc:
        problem_import.status = 'F'
        logger.exception('Failed to import problem')
        problem_import.error = str(exc)
        raise
    else:
        problem_import.status = 'C'
    finally:
        problem_import.log = log_stream.getvalue()
        problem_import.save()
