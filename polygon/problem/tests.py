import math
import time
import zipfile
from typing import Any, Dict, List

from .exceptions import ProblemImportError
from .types import Batch, ImportContext, ProblemConfig
from .utils import asdict_notnull


def parse_testset(context: ImportContext, storage: zipfile.ZipFile, name: str) -> List[Dict[str, Any]]:
    testset = context.descriptor.find(f'.//testset[@name="{name}"]')
    if testset is None:
        return None
    if len(testset.find('tests')) == 0:
        return None

    context.logger.info('Processing testset %s', name)

    group_name_to_id: Dict[str, int] = {}
    groups: List[Batch] = []
    group_blocks = testset.find('groups')
    groups_enabled = group_blocks is not None
    if groups_enabled:
        for idx, group_block in enumerate(group_blocks, start=1):
            name = int(group_block.get('name'))

            points_policy = group_block.get('points-policy')
            assert points_policy in ['complete-group', 'each-test']

            dep_names = [d.get('group') for d in group_block.find('dependencies') or []]

            if points_policy == 'each-test':
                if len(dep_names) > 0:
                    raise ProblemImportError('Dependencies only supported for groups with complete-group policy')
                continue

            dependencies = []
            for dep in dep_names:
                if dep not in group_name_to_id:
                    raise ProblemImportError(
                        f'Group {name} depends on group {dep} that does not exist or has each-test points policy',
                    )
                dependencies.append(group_name_to_id[dep])

            group = Batch(points=float(group_block.get('points', 0)), dependencies=dependencies)

            groups.append(group)
            group_name_to_id[name] = idx

    ungrouped_tests: List[Dict[str, str]] = []
    input_path_pattern = testset.find('input-path-pattern').text
    answer_path_pattern = testset.find('answer-path-pattern').text
    for idx, test in enumerate(testset.find('tests'), start=1):
        input_path = input_path_pattern % idx
        output_path = answer_path_pattern % idx

        if input_path not in context.package.namelist():
            raise ProblemImportError(f'Input file {input_path} for test {idx} is missing')
        if output_path not in context.package.namelist():
            raise ProblemImportError(f'Output file {output_path} for test {idx} is missing')

        input_file = f'{name}-{idx:02d}.inp'
        output_file = f'{name}-{idx:02d}.out'
        storage.writestr(input_file, context.package.read(input_path))
        storage.writestr(output_file, context.package.read(output_path))

        test_record = {'in': input_file, 'out': output_file}

        points = float(test.get('points', 0))
        group = test.get('group', None)
        if group in group_name_to_id:
            group_id = group_name_to_id[group] - 1
            groups[group_id].batched.append(test_record)
        else:
            if groups_enabled and points == 0:
                raise ProblemImportError('All tests in groups with each-test policy should be scored')
            test_record['points'] = points
            ungrouped_tests.append(test_record)

    result: Dict[str, Any] = ungrouped_tests + [asdict_notnull(group) for group in groups]

    all_points: list[float] = [item['points'] for item in result]
    if any(not p.is_integer() for p in all_points):
        context.logger.warning('FLOATING-POINT TEST POINTS ARE NOT SUPPORTED. NORMALIZING TO INTEGERS')
        all_points = [int(p * 100) for p in all_points]
        gcd = math.gcd(*all_points)
        for item in result:
            item['points'] = int(item['points'] * 100) // gcd
    else:
        for item in result:
            item['points'] = int(item['points'])

    test_count = sum(len(item['batched']) if 'batched' in item else 1 for item in result)
    batch_count = len(groups)
    context.logger.info('Parsed %d tests and %d batches', test_count, batch_count)

    return result


def parse_tests(context: ImportContext) -> ProblemConfig:
    revision = context.descriptor.get('revision')
    archive = f'tests-r{revision}-{int(time.time())}.zip'

    context.logger.info('Storing tests in %s', archive)
    with zipfile.ZipFile(context.temp_dir / archive, 'w') as zf:
        pretests = parse_testset(context, zf, 'pretests')
        tests = parse_testset(context, zf, 'tests')

        if tests is None:
            raise ProblemImportError('Testset "tests" is empty or missing')

        for testset in context.descriptor.findall('.//judging/testset'):
            if (name := testset.get('name')) not in ('tests', 'pretests'):
                context.logger.warning('Unsupported testset %s, skipping...', name)

    return ProblemConfig(
        test_cases=tests,
        pretest_test_cases=pretests,
        archive=archive,
    )
