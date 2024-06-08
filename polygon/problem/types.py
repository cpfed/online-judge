from dataclasses import dataclass, field
from logging import Logger
from pathlib import Path
from typing import Any, Dict, List
from zipfile import ZipFile

from celery.app.task import Task
from lxml.etree import _Element

from judge.models import ProblemGroup, Profile
from ..models import ProblemSource


class TaskReporter:
    def __init__(self, task: Task):
        self.task = task

    def report(self, stage: str):
        self.task.update_state(state='WORKING', meta={'stage': stage})


@dataclass
class ImportContext:
    source: ProblemSource
    task: TaskReporter
    author: Profile
    package: ZipFile
    descriptor: _Element
    logger: Logger
    temp_dir: Path
    upload_id: str
    image_cache: dict[str, str] = field(default_factory=dict)


@dataclass
class Statement:
    name: str
    description: str
    language: str | None = None
    tutorial: str | None = None


@dataclass
class CheckerArgs:
    files: List[str]
    feedback: bool
    lang: str = 'CPP20'
    type: str = 'testlib'


@dataclass
class Checker:
    args: CheckerArgs
    name: str = 'bridged'


@dataclass
class Grader:
    files: List[str]
    feedback: bool
    lang: str = 'CPP20'
    type: str = 'testlib'


@dataclass
class MainSolution:
    language: str
    source: str


@dataclass
class ProblemConfig:
    archive: str
    # We can't really typehint test_cases because it contains key "in" which is keyword in Python.
    # test_cases and pretest_test_cases are one of two forms:
    # - {in: str, out: str, points: int}
    # - {batched: list[{in: str, out: str}], points: int, dependencies?: list[int]}
    test_cases: List[Dict[str, Any]]
    pretest_test_cases: List[Dict[str, Any]] | None = None

    checker: Checker | None = None
    interactive: Grader | None = None
    unbuffered: bool | None = None
    hints: List[str] | None = None


@dataclass
class ProblemProperties:
    code: str
    name: str
    time_limit: int
    memory_limit: int
    description: str
    partial: bool
    points: float
    group: ProblemGroup
    is_manually_managed: bool = False
    translations: List[Statement] = field(default_factory=list)
    tutorial: str | None = None


@dataclass
class Batch:
    points: float
    dependencies: List[int]
    batched: List[Dict[str, str]] = field(default_factory=list)
