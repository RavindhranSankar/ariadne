from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TaskArtifact:
    kind: str
    title: str
    path: str | None = None
    content: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TaskResult:
    voice_summary: str
    context: str
    artifacts: tuple[TaskArtifact, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
