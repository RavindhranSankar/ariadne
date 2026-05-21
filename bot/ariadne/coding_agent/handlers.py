from ariadne.ariadne_session import AriadneSession
from ariadne.ariadne_task_queue import AriadneTask, TaskKind
from ariadne.coding_agent.doc_writer import DocWriter
from ariadne.coding_agent.investigator import Investigator
from ariadne.task_result import TaskResult


class InvestigationTaskHandler:
    kind = TaskKind.INVESTIGATION

    def __init__(self, investigator: Investigator, session: AriadneSession):
        self._investigator = investigator
        self._session = session

    async def run(self, task: AriadneTask) -> TaskResult:
        result = await self._investigator.investigate(
            task.problem_context,
            turn_id=self._session.current_turn_id,
            investigation_id=self._session.next_investigation_id(),
        )
        if result is None:
            raise RuntimeError("Investigation failed — no result returned")
        return result


class WriteDocTaskHandler:
    kind = TaskKind.WRITE_DOC

    def __init__(self, doc_writer: DocWriter):
        self._doc_writer = doc_writer

    async def run(self, task: AriadneTask) -> TaskResult:
        result = await self._doc_writer.write_doc(task.problem_context)
        if result is None:
            raise RuntimeError("Doc writing failed — no result returned")
        return result
