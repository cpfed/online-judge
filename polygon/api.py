import hashlib
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

import requests
import requests.exceptions
from django.conf import settings

from .problem import ProblemImportError

__all__ = ('get_problem', 'get_problem_packages', 'save_package')


@dataclass
class Problem:
    id: int
    owner: str
    name: str
    deleted: bool
    favourite: bool
    accessType: str
    revision: int
    modified: bool
    latestPackage: int | None = None


@dataclass
class Package:
    id: int
    revision: int
    creationTimeSeconds: int
    state: str
    comment: str
    type: str


def sign(method: str, params: Dict[str, str]) -> Dict[str, str]:
    timestamp = int(time.time())

    params = {'time': timestamp, 'apiKey': settings.POLYGON_API_KEY, **params}

    rand = secrets.token_hex(3)

    source = f'{rand}/{method}?' + '&'.join(
        f'{k}={v}'
        for k, v in sorted(params.items())
    ) + f'#{settings.POLYGON_API_SECRET}'

    params['apiSig'] = rand + hashlib.sha512(source.encode()).hexdigest()

    return params


def call_api(method: str, params: Dict[str, str]) -> requests.Response:
    return requests.post(
        f'https://polygon.codeforces.com/api/{method}',
        params=sign(method, params),
    )


def call_api_json(method: str, params: Dict[str, str]) -> Any:
    response = call_api(method, params)

    try:
        response_json = response.json()
    except requests.exceptions.JSONDecodeError:
        raise ProblemImportError(f'Polygon responded with code {response.status_code}: {response.text}')

    if 'status' not in response_json:
        raise ProblemImportError(f'Polygon responded with code {response.status_code}: {response.text}')

    if response_json['status'] != 'OK':
        raise ProblemImportError(f'Polygon request failed: {response_json["comment"]}')

    return response_json['result']


def get_problem(problem_id: int) -> Problem:
    response = call_api_json('problems.list', {'id': str(problem_id)})

    if len(response) == 0:
        raise ProblemImportError(f'Problem {problem_id} does not exist ' +
                                 f'or user {settings.POLYGON_USER} has no access to it')
    if len(response) > 1:
        raise ProblemImportError(f'Invalid Polygon response: multiple problems for ID {problem_id}')

    problem = Problem(**response[0])

    return problem


def get_problem_packages(problem_id: int) -> List[Package]:
    response = call_api_json('problem.packages', {'problemId': str(problem_id)})

    packages = [Package(**package) for package in response]

    return packages


def save_package(problem_id: int, package_id: int, path: Path, type: str = 'linux') -> None:
    with call_api(
        'problem.package',
        {'packageId': str(package_id), 'type': type, 'problemId': str(problem_id)},
    ) as archive:
        if archive.status_code != 200:
            raise ProblemImportError(f'Polygon returned unexpected status code {archive.status_code}')

        with path.open('wb') as f:
            for chunk in archive.iter_content(chunk_size=16384):
                f.write(chunk)
