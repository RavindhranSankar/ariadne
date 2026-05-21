import uuid
from datetime import datetime, timezone

from ariadne.session_logger import SessionLogger


class AriadneSession:
    def __init__(self):
        self.session_id = str(uuid.uuid4())
        self.session_short_id = self.session_id[:8]
        self.started_at = datetime.now(timezone.utc)
        self.ended_at: datetime | None = None
        self.status = "open"
        self.close_reason: str | None = None
        self.current_turn_id: str | None = None
        self.last_human_activity = self.started_at
        self._turn_counter = 0
        self._investigation_counter = 0

        self.logger = SessionLogger(self.session_id, self.session_short_id)

    def next_turn_id(self) -> str:
        self._turn_counter += 1
        self.current_turn_id = f"turn-{self._turn_counter:06d}"
        return self.current_turn_id

    def next_investigation_id(self) -> str:
        self._investigation_counter += 1
        return f"inv-{self._investigation_counter:06d}"

    def mark_human_activity(self):
        self.last_human_activity = datetime.now(timezone.utc)

    def close(self, reason: str):
        if self.status == "closed":
            return
        self.status = "closed"
        self.close_reason = reason
        self.ended_at = datetime.now(timezone.utc)
        self.logger.log("session", "session.closed", {"reason": reason})
        self.logger.write_session_json(self)
