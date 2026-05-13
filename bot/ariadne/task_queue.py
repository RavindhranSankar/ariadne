import asyncio
import os
from dataclasses import dataclass
from datetime import datetime, timezone

VALID_KINDS = {"investigation", "write-doc"}


@dataclass
class TaskRecord:
    task_id: str
    kind: str
    status: str  # "queued" | "running" | "done" | "failed"
    description: str
    problem_context: str
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result: dict | None = None  # {"summary_for_voice": str, "full_result": str}
    failure_reason: str | None = None


class TaskQueue:
    """
    In-process task store and queue for Ariadne background tasks.

    Tracks all task records. Exposes synchronous read/write operations for
    LLM tool handlers and orchestrator. Signals waiters via asyncio.Event
    when new work becomes eligible.
    """

    def __init__(self):
        self._max_active = int(os.getenv("ARIADNE_TASK_QUEUE_MAX", "5"))
        self._tasks: dict[str, TaskRecord] = {}
        self._counter = 0
        self._work_available: asyncio.Event = asyncio.Event()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _active_count(self) -> int:
        return sum(1 for t in self._tasks.values() if t.status in ("queued", "running"))

    def _has_running(self, kind: str) -> bool:
        return any(t.kind == kind and t.status == "running" for t in self._tasks.values())

    def get(self, task_id: str) -> TaskRecord | None:
        return self._tasks.get(task_id)

    def next_eligible(self) -> TaskRecord | None:
        """Return the oldest queued task that has no same-kind task running."""
        for record in sorted(self._tasks.values(), key=lambda t: t.created_at):
            if record.status != "queued":
                continue
            if self._has_running(record.kind):
                continue
            return record
        return None

    # ------------------------------------------------------------------
    # Tool-facing operations (called by LLM tool handlers)
    # ------------------------------------------------------------------

    def enqueue(self, kind: str, description: str, problem_context: str) -> dict:
        if kind not in VALID_KINDS:
            return {"status": "rejected", "reason": f"unknown kind '{kind}'"}
        if not description.strip():
            return {"status": "rejected", "reason": "description must be non-empty"}
        if not problem_context.strip():
            return {"status": "rejected", "reason": "problem_context must be non-empty"}
        if self._active_count() >= self._max_active:
            return {
                "status": "queue_full",
                "active_count": self._active_count(),
                "active_capacity": self._max_active,
            }

        self._counter += 1
        task_id = f"task-{self._counter:03d}"
        now = datetime.now(timezone.utc)
        record = TaskRecord(
            task_id=task_id,
            kind=kind,
            status="queued",
            description=description,
            problem_context=problem_context,
            created_at=now,
            updated_at=now,
        )
        self._tasks[task_id] = record
        self._work_available.set()

        response: dict = {"status": "queued", "task_id": task_id}
        if self._has_running(kind):
            response["note"] = "waiting for running same-kind task"
        return response

    def dequeue(self, task_id: str) -> dict:
        record = self._tasks.get(task_id)
        if record is None:
            return {"dequeued": False, "previous_status": "not_found", "status": "not_found"}
        prev = record.status
        if prev != "queued":
            return {"dequeued": False, "previous_status": prev, "status": prev}
        now = datetime.now(timezone.utc)
        record.status = "failed"
        record.failure_reason = "dequeued"
        record.updated_at = now
        return {
            "dequeued": True,
            "previous_status": prev,
            "status": "failed",
            "failure_reason": "dequeued",
        }

    def get_task_status(self, task_id: str) -> dict:
        record = self._tasks.get(task_id)
        if record is None:
            return {"status": "not_found"}
        elapsed = None
        if record.started_at:
            elapsed = int((datetime.now(timezone.utc) - record.started_at).total_seconds())
        return {
            "status": record.status,
            "elapsed_seconds": elapsed,
            "description": record.description,
            "failure_reason": record.failure_reason,
        }

    def get_active_tasks(self, kind: str | None = None) -> dict:
        tasks = []
        for record in sorted(self._tasks.values(), key=lambda t: t.created_at):
            if record.status not in ("queued", "running"):
                continue
            if kind is not None and record.kind != kind:
                continue
            elapsed = None
            if record.started_at:
                elapsed = int((datetime.now(timezone.utc) - record.started_at).total_seconds())
            tasks.append({
                "task_id": record.task_id,
                "kind": record.kind,
                "status": record.status,
                "elapsed_seconds": elapsed,
                "description": record.description,
            })
        return {
            "tasks": tasks,
            "active_count": len(tasks),
            "active_capacity": self._max_active,
        }

    def get_task_results(self, task_id: str) -> dict:
        record = self._tasks.get(task_id)
        if record is None:
            return {"status": "not_found"}
        elapsed = None
        if record.started_at:
            elapsed = int((datetime.now(timezone.utc) - record.started_at).total_seconds())
        if record.status == "done":
            return {"status": "done", "result": record.result, "elapsed_seconds": elapsed}
        return {
            "status": record.status,
            "failure_reason": record.failure_reason,
            "elapsed_seconds": elapsed,
        }

    def cancel(self, task_id: str) -> dict:
        record = self._tasks.get(task_id)
        if record is None:
            return {"status": "not_found"}
        if record.status not in ("queued", "running"):
            return {"status": record.status}
        record.status = "failed"
        record.failure_reason = "cancelled"
        record.updated_at = datetime.now(timezone.utc)
        return {"status": "failed", "failure_reason": "cancelled"}

    # ------------------------------------------------------------------
    # Orchestrator-facing operations
    # ------------------------------------------------------------------

    def mark_running(self, task_id: str):
        r = self._tasks[task_id]
        now = datetime.now(timezone.utc)
        r.status = "running"
        r.started_at = now
        r.updated_at = now

    def mark_done(self, task_id: str, result: dict):
        r = self._tasks[task_id]
        now = datetime.now(timezone.utc)
        r.status = "done"
        r.result = result
        r.completed_at = now
        r.updated_at = now
        self._work_available.set()  # A slot freed up; same-kind queued tasks may now be eligible.

    def mark_failed(self, task_id: str, failure_reason: str):
        r = self._tasks[task_id]
        now = datetime.now(timezone.utc)
        r.status = "failed"
        r.failure_reason = failure_reason
        r.completed_at = now
        r.updated_at = now
        self._work_available.set()

    async def wait_for_work(self):
        """Block until something might be eligible to run."""
        await self._work_available.wait()
        self._work_available.clear()
