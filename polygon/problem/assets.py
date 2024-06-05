import shutil
from pathlib import Path
from zipfile import ZipFile

from .exceptions import ProblemImportError
from .types import Checker, CheckerArgs, Grader, ImportContext, ProblemConfig


def extract(zf: ZipFile, member: str, destination: Path) -> None:
    if destination.is_dir():
        shutil.rmtree(destination)

    with zf.open(member, 'r') as src:
        with destination.open('wb') as dst:
            shutil.copyfileobj(src, dst)


def parse_assets(context: ImportContext, config: ProblemConfig) -> None:
    """Adds checker or interactor."""

    # Polygon supports hiding checker comments by using tag
    feedback = True
    for tag in context.descriptor.findall('.//tags/tag'):
        if tag.get('value') == 'hide_checker_comment':
            feedback = False
            break

    interactor = context.descriptor.find('.//interactor')
    if interactor is not None:
        context.logger.info('Problem is interactive')

        source = interactor.find('source')
        if source is None:
            raise ProblemImportError('Interactor has no source')

        path = source.get('path')
        if not path.lower().endswith('.cpp'):
            raise ProblemImportError('Only C++ interactors are supported')

        extract(context.package, 'files/testlib.h', context.temp_dir / 'testlib.h')
        extract(context.package, path, context.temp_dir / 'interactor.cpp')

        config.interactive = Grader(files=['interactor.cpp', 'testlib.h'], feedback=feedback)
        config.unbuffered = True

        context.logger.warning('DMOJ does not support checker and interactor at the same time')
        context.logger.info('Your checker should ALWAYS quitf(_ok), all checks should be made in the interactor')
        return

    context.logger.info('Problem is non-interactive, adding checker')

    checker = context.descriptor.find('.//checker')
    if checker is None or checker.get('type') != 'testlib' or (source := checker.find('source')) is None:
        raise ProblemImportError('Checker is missing or not well-formed')

    path = source.get('path')
    if not path.lower().endswith('.cpp'):
        raise ProblemImportError('Only C++ checkers are supported')

    extract(context.package, 'files/testlib.h', context.temp_dir / 'testlib.h')
    extract(context.package, path, context.temp_dir / 'checker.cpp')

    config.checker = Checker(args=CheckerArgs(files=['checker.cpp', 'testlib.h'], feedback=feedback))
