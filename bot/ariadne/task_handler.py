from typing import Protocol

from ariadne.ariadne_task_queue import AriadneTask, TaskKind
from ariadne.task_result import TaskResult


class UnknownTaskKind(ValueError):
    pass


class TaskHandler(Protocol):
    kind: TaskKind

    async def run(self, task: AriadneTask) -> TaskResult:
        ...
