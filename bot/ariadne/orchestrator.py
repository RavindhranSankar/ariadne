import asyncio
import os
from typing import Callable, Coroutine

from loguru import logger

from ariadne.implementation_doc import ImplementationDocWriter
from ariadne.repo_investigator import RepoInvestigator
from ariadne.session import AriadneSession
from ariadne.task_queue import TaskQueue, TaskRecord


class RepoAgentOrchestrator:
    """
    Consumes tasks from TaskQueue and manages worker lifecycle.

    Runs as a long-lived asyncio task for the duration of the session.
    Calls on_task_event when a task completes or fails so the pipeline
    can inject a notification into the LLM context.
    """

    def __init__(
        self,
        *,
        task_queue: TaskQueue,
        repo_investigator: RepoInvestigator,
        session: AriadneSession,
        on_task_event: Callable[[dict], Coroutine],
    ):
        self._queue = task_queue
        self._repo_investigator = repo_investigator
        self._session = session
        self._on_task_event = on_task_event
        self._timeout = float(os.getenv("ARIADNE_TASK_TIMEOUT_SECONDS", "300"))
        self._workers: dict[str, asyncio.Task] = {}

    async def run(self):
        """Main orchestrator loop. Runs until cancelled."""
        while True:
            try:
                await self._queue.wait_for_work()
                self._dispatch_eligible()
            except asyncio.CancelledError:
                for worker in self._workers.values():
                    worker.cancel()
                break
            except Exception as exc:
                logger.exception(f"Orchestrator error: {exc}")

    def _dispatch_eligible(self):
        """Start all currently eligible queued tasks."""
        while True:
            record = self._queue.next_eligible()
            if record is None:
                break
            if record.task_id in self._workers:
                break
            self._queue.mark_running(record.task_id)
            worker = asyncio.create_task(self._run_worker(record))
            self._workers[record.task_id] = worker
            worker.add_done_callback(
                lambda _, tid=record.task_id: self._workers.pop(tid, None)
            )

    async def cancel_worker(self, task_id: str):
        """Cancel the asyncio task for a running worker."""
        worker = self._workers.get(task_id)
        if worker:
            worker.cancel()

    async def _run_worker(self, record: TaskRecord):
        task_id = record.task_id
        self._session.logger.log(
            "runtime",
            "runtime.task_started",
            {
                "task_id": task_id,
                "kind": record.kind,
                "description": record.description,
                "problem_context": record.problem_context,
            },
        )

        try:
            result = await asyncio.wait_for(self._execute(record), timeout=self._timeout)
        except asyncio.TimeoutError:
            if self._queue.get(task_id).status == "failed":
                return  # Already cancelled by user — don't overwrite.
            self._queue.mark_failed(task_id, "timeout")
            self._session.logger.log(
                "runtime",
                "runtime.task_failed",
                {"task_id": task_id, "failure_reason": "timeout"},
            )
            await self._on_task_event({
                "task_id": task_id,
                "status": "failed",
                "failure_reason": "timeout",
                "elapsed_seconds": int(self._timeout),
                "message": "That task timed out. Would you like to try a more focused version?",
            })
            return
        except asyncio.CancelledError:
            return
        except Exception as exc:
            if self._queue.get(task_id).status == "failed":
                return
            self._queue.mark_failed(task_id, "worker_error")
            self._session.logger.log(
                "runtime",
                "runtime.task_failed",
                {"task_id": task_id, "failure_reason": "worker_error", "error": str(exc)},
            )
            await self._on_task_event({
                "task_id": task_id,
                "status": "failed",
                "failure_reason": "worker_error",
                "message": "The task hit an unexpected error.",
            })
            return

        # Check if the task was cancelled while the worker ran — discard results.
        if self._queue.get(task_id).status == "failed":
            self._session.logger.log(
                "runtime",
                "runtime.task_cancelled_result_discarded",
                {"task_id": task_id},
            )
            return

        if result is None:
            self._queue.mark_failed(task_id, "worker_error")
            self._session.logger.log(
                "runtime",
                "runtime.task_failed",
                {"task_id": task_id, "failure_reason": "worker_error"},
            )
            await self._on_task_event({
                "task_id": task_id,
                "status": "failed",
                "failure_reason": "worker_error",
                "message": "The task didn't return any results.",
            })
            return

        self._queue.mark_done(task_id, result)
        self._session.logger.log(
            "runtime",
            "runtime.task_done",
            {"task_id": task_id, "kind": record.kind},
        )
        await self._on_task_event({
            "task_id": task_id,
            "status": "done",
            "result_available": True,
        })

    async def _execute(self, record: TaskRecord) -> dict | None:
        if record.kind == "investigation":
            return await self._repo_investigator.investigate(
                record.problem_context,
                turn_id=self._session.current_turn_id,
                investigation_id=self._session.next_investigation_id(),
            )
        elif record.kind == "write-doc":
            writer = ImplementationDocWriter()
            return await writer.write_doc(record.problem_context, self._session)
        else:
            logger.error(f"Unknown task kind: {record.kind}")
            return None
