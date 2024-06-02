import io
import logging
import os
import tempfile
import traceback
import zipfile
from pathlib import Path

import requests
from celery import shared_task
from django.conf import settings
from django.core.files.storage import default_storage
from lxml import etree as ET

from judge.models import Problem
from .models import ProblemSource, ProblemSourceImport
from .problem import ImportContext, ProblemImportError, handle_import

__all__ = 'import_problem'


def download_archive(url: str, path: Path):
    assert url.startswith('https://polygon.codeforces.com/')
    with requests.post(
        url, params={'type': 'linux'}, data={'login': settings.POLYGON_LOGIN, 'password': settings.POLYGON_PASSWORD},
    ) as archive:
        archive.raise_for_status()

        with path.open('wb') as f:
            for chunk in archive.iter_content(chunk_size=16384):
                f.write(chunk)


@shared_task(bind=True)
def import_problem(self, problem_source_id: int):
    problem_source = ProblemSource.objects.get(id=problem_source_id)
    problem_import = ProblemSourceImport(problem_source=problem_source)
    problem_import.save()

    log_stream = io.StringIO()
    log_handler = logging.StreamHandler(log_stream)
    logger = logging.getLogger('judge.import_problem')
    logger.addHandler(log_handler)

    try:
        problem_code = problem_source.problem_code
        Problem._meta.get_field('code').run_validators(problem_code)
        if problem_source.problem is None and Problem.objects.filter(code=problem_code).exists():
            raise ProblemImportError(f'Problem with code {problem_code} already exists')

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)

            download_archive(problem_source.polygon_url, temp_dir / 'archive.zip')

            with zipfile.ZipFile(temp_dir / 'archive.zip') as package:
                if 'problem.xml' not in package.namelist():
                    raise ProblemImportError('problem.xml not found')

                context = ImportContext(
                    source=problem_source,
                    package=package,
                    descriptor=ET.fromstring(package.read('problem.xml')),
                    logger=logger,
                    temp_dir=temp_dir,
                )

                try:
                    problem_source.problem = handle_import(context)
                    problem_source.save()
                except:  # noqa: E722, we need cleanup for every failure including KeyboardInterrupt
                    for image_url in context.image_cache.values():
                        source_path = default_storage.path(
                            os.path.join(settings.MARTOR_UPLOAD_MEDIA_DIR, os.path.basename(image_url)),
                        )
                        os.remove(source_path)
                    raise
    except Exception as exc:
        problem_import.status = 'F'
        problem_import.error = f'{type(exc)}: {exc}\n' + traceback.format_exc()
        raise
    else:
        problem_import.status = 'C'
    finally:
        problem_import.log = log_stream.getvalue()
        problem_import.save()
