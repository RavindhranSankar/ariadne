import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger

from ariadne.paths import get_logs_dir

# Subfolder names for per-module event logs.
_MODULE_FOLDERS = {
    "session": "session",
    "daily": "daily",
    "stt": "stt",
    "conversation-agent": "conversation-agent",
    "tts": "tts",
    "repo-investigator": "repo-investigator",
    "runtime": "runtime",
}


class SessionLogger:
    def __init__(self, session_id: str, session_short_id: str):
        self._session_dir = get_logs_dir() / "session-logs" / session_short_id
        self._session_id = session_id
        self._session_short_id = session_short_id
        # Subscribers that receive every event dict for live debug streaming.
        self._sse_queues: list[asyncio.Queue[dict]] = []
        self._setup_dirs()
        self._init_transcript(session_id)

    def _setup_dirs(self):
        try:
            for folder in _MODULE_FOLDERS.values():
                (self._session_dir / folder).mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            logger.error(f"Failed to create session directories: {exc}")

    def _init_transcript(self, session_id: str):
        try:
            ts = datetime.now(timezone.utc).isoformat()
            (self._session_dir / "transcript.md").write_text(
                f"# Ariadne Session Transcript\n\nSession: {session_id}\nStarted: {ts}\n"
            )
        except Exception as exc:
            logger.error(f"Failed to initialise transcript: {exc}")

    def add_sse_subscriber(self) -> asyncio.Queue:
        """Register a new SSE subscriber and return its queue."""
        q: asyncio.Queue[dict] = asyncio.Queue(maxsize=500)
        self._sse_queues.append(q)
        return q

    def remove_sse_subscriber(self, q: asyncio.Queue):
        try:
            self._sse_queues.remove(q)
        except ValueError:
            pass

    def log(
        self,
        module: str,
        event: str,
        data: dict[str, Any],
        *,
        turn_id: str | None = None,
        investigation_id: str | None = None,
    ):
        try:
            record: dict[str, Any] = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "session_id": self._session_id,
                "session_short_id": self._session_short_id,
                "module": module,
                "event": event,
                "turn_id": turn_id,
                "investigation_id": investigation_id,
                "data": data,
            }

            # Per-module log
            folder = _MODULE_FOLDERS.get(module, module)
            module_path = self._session_dir / folder / "events.jsonl"
            with open(module_path, "a") as f:
                f.write(json.dumps(record) + "\n")

            # Timeline: chronological mirror of all events
            timeline_path = self._session_dir / "timeline.jsonl"
            with open(timeline_path, "a") as f:
                f.write(json.dumps(record) + "\n")

            # Notify SSE subscribers (best-effort, non-blocking)
            for q in list(self._sse_queues):
                try:
                    q.put_nowait(record)
                except asyncio.QueueFull:
                    pass

        except Exception as exc:
            logger.error(f"Log write failed [{module}.{event}]: {exc}")

    def append_transcript_user(self, turn_id: str, text: str):
        self._append(f"\n## {turn_id}\n\nUser:\n{text}\n")

    def append_transcript_assistant(self, turn_id: str | None, text: str):
        self._append(f"\nAriadne:\n{text}\n")

    def append_transcript_codex(self, turn_id: str, investigation_id: str, text: str):
        self._append(f"\nRepo Investigator ({investigation_id}):\n{text}\n")

    def write_session_json(self, session):
        try:
            data = {
                "session_id": session.session_id,
                "session_short_id": session.session_short_id,
                "started_at": session.started_at.isoformat(),
                "ended_at": session.ended_at.isoformat() if session.ended_at else None,
                "status": session.status,
                "close_reason": session.close_reason,
            }
            with open(self._session_dir / "session.json", "w") as f:
                json.dump(data, f, indent=2)
        except Exception as exc:
            logger.error(f"session.json write failed: {exc}")

    def _append(self, text: str):
        try:
            with open(self._session_dir / "transcript.md", "a") as f:
                f.write(text)
        except Exception as exc:
            logger.error(f"Transcript append failed: {exc}")
