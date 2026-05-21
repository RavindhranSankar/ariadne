import asyncio
from typing import Callable, Coroutine

from loguru import logger

from ariadne.ariadne_session import AriadneSession
from ariadne.ariadne_task_queue import AriadneTask, AriadneTaskQueue
from ariadne.task_executor import TaskExecutor
from ariadne.task_result import TaskResult


class Orchestrator:
    """
    Consumes tasks from AriadneTaskQueue and manages worker lifecycle.

    Runs as a long-lived asyncio task for the duration of the session.
    Calls on_task_event when a task completes or fails so the pipeline
    can inject a notification into the LLM context.
    """

    def __init__(
        self,
        *,
        task_queue: AriadneTaskQueue,
        task_executor: TaskExecutor,
        session: AriadneSession,
        on_task_event: Callable[[dict], Coroutine],
        task_timeout_seconds: float = 300.0,
    ):
        self._queue = task_queue
        self._task_executor = task_executor
        self._session = session
        self._on_task_event = on_task_event
        self._timeout = task_timeout_seconds
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

    async def _run_worker(self, record: AriadneTask):
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
            result: TaskResult = await asyncio.wait_for(
                self._task_executor.execute(record),
                timeout=self._timeout,
            )
        except asyncio.TimeoutError:
            if (r := self._queue.get(task_id)) is not None and r.status == "failed":
                return
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
            if (r := self._queue.get(task_id)) is not None and r.status == "failed":
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

        # Discard results if the task was cancelled while the worker ran.
        if (r := self._queue.get(task_id)) is not None and r.status == "failed":
            self._session.logger.log(
                "runtime",
                "runtime.task_cancelled_result_discarded",
                {"task_id": task_id},
            )
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
