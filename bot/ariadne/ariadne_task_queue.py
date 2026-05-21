import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum

from ariadne.task_result import TaskResult


class TaskKind(StrEnum):
    INVESTIGATION = "investigation"
    WRITE_DOC = "write-doc"


class TaskStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class AriadneTask:
    task_id: str
    kind: TaskKind
    status: TaskStatus
    description: str
    problem_context: str
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result: TaskResult | None = None
    failure_reason: str | None = None


class AriadneTaskQueue:
    """
    In-process task store for Ariadne background tasks.

    Enforces one running task per kind and a configurable active-task cap.
    Signals waiters via asyncio.Event when new work becomes eligible.
    """

    def __init__(self, max_active: int = 5):
        self._max_active = max_active
        self._tasks: dict[str, AriadneTask] = {}
        self._counter = 0
        self._work_available: asyncio.Event = asyncio.Event()

    def _active_count(self) -> int:
        return sum(1 for t in self._tasks.values() if t.status in (TaskStatus.QUEUED, TaskStatus.RUNNING))

    def _has_running(self, kind: TaskKind) -> bool:
        return any(t.kind == kind and t.status == TaskStatus.RUNNING for t in self._tasks.values())

    def get(self, task_id: str) -> AriadneTask | None:
        return self._tasks.get(task_id)

    def next_eligible(self) -> AriadneTask | None:
        """Return the oldest queued task that has no same-kind task running."""
        for record in sorted(self._tasks.values(), key=lambda t: t.created_at):
            if record.status != TaskStatus.QUEUED:
                continue
            if self._has_running(record.kind):
                continue
            return record
        return None

    # ------------------------------------------------------------------
    # Tool-facing operations
    # ------------------------------------------------------------------

    def enqueue(self, kind: str, description: str, problem_context: str) -> dict:
        try:
            task_kind = TaskKind(kind)
        except ValueError:
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
        record = AriadneTask(
            task_id=task_id,
            kind=task_kind,
            status=TaskStatus.QUEUED,
            description=description,
            problem_context=problem_context,
            created_at=now,
            updated_at=now,
        )
        self._tasks[task_id] = record
        self._work_available.set()

        response: dict = {"status": "queued", "task_id": task_id}
        if self._has_running(task_kind):
            response["note"] = "waiting for running same-kind task"
        return response

    def dequeue(self, task_id: str) -> dict:
        record = self._tasks.get(task_id)
        if record is None:
            return {"dequeued": False, "previous_status": "not_found", "status": "not_found"}
        prev = record.status
        if prev != TaskStatus.QUEUED:
            return {"dequeued": False, "previous_status": prev, "status": prev}
        now = datetime.now(timezone.utc)
        record.status = TaskStatus.FAILED
        record.failure_reason = "dequeued"
        record.updated_at = now
        return {
            "dequeued": True,
            "previous_status": prev,
            "status": TaskStatus.FAILED,
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
        kind_filter: TaskKind | None = None
        if kind is not None:
            try:
                kind_filter = TaskKind(kind)
            except ValueError:
                return {"tasks": [], "active_count": 0, "active_capacity": self._max_active}
        tasks = []
        for record in sorted(self._tasks.values(), key=lambda t: t.created_at):
            if record.status not in (TaskStatus.QUEUED, TaskStatus.RUNNING):
                continue
            if kind_filter is not None and record.kind != kind_filter:
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
        if record.status == TaskStatus.DONE and record.result is not None:
            return {
                "status": "done",
                "voice_summary": record.result.voice_summary,
                "context": record.result.context,
                "elapsed_seconds": elapsed,
            }
        return {
            "status": record.status,
            "failure_reason": record.failure_reason,
            "elapsed_seconds": elapsed,
        }

    def cancel(self, task_id: str) -> dict:
        record = self._tasks.get(task_id)
        if record is None:
            return {"status": "not_found"}
        if record.status not in (TaskStatus.QUEUED, TaskStatus.RUNNING):
            return {"status": record.status}
        record.status = TaskStatus.FAILED
        record.failure_reason = "cancelled"
        record.updated_at = datetime.now(timezone.utc)
        return {"status": TaskStatus.FAILED, "failure_reason": "cancelled"}

    # ------------------------------------------------------------------
    # Orchestrator-facing operations
    # ------------------------------------------------------------------

    def mark_running(self, task_id: str):
        r = self._tasks[task_id]
        now = datetime.now(timezone.utc)
        r.status = TaskStatus.RUNNING
        r.started_at = now
        r.updated_at = now

    def mark_done(self, task_id: str, result: TaskResult):
        r = self._tasks[task_id]
        now = datetime.now(timezone.utc)
        r.status = TaskStatus.DONE
        r.result = result
        r.completed_at = now
        r.updated_at = now
        self._work_available.set()

    def mark_failed(self, task_id: str, failure_reason: str):
        r = self._tasks[task_id]
        now = datetime.now(timezone.utc)
        r.status = TaskStatus.FAILED
        r.failure_reason = failure_reason
        r.completed_at = now
        r.updated_at = now
        self._work_available.set()

    async def wait_for_work(self):
        """Block until something might be eligible to run."""
        await self._work_available.wait()
        self._work_available.clear()
