from ariadne.ariadne_task_queue import AriadneTask
from ariadne.task_handler import TaskHandler, UnknownTaskKind
from ariadne.task_result import TaskResult


class TaskExecutor:
    def __init__(self, handlers: list[TaskHandler]):
        self._handlers = {handler.kind: handler for handler in handlers}

    async def execute(self, task: AriadneTask) -> TaskResult:
        handler = self._handlers.get(task.kind)
        if handler is None:
            raise UnknownTaskKind(task.kind)
        return await handler.run(task)
