import asyncio
import os
from typing import Callable, Coroutine

from loguru import logger


class IdleTimeoutWatcher:
    def __init__(self, *, on_timeout: Callable[[], Coroutine]):
        self._timeout_seconds = float(os.getenv("ARIADNE_IDLE_TIMEOUT_SECONDS", "300"))
        self._on_timeout = on_timeout
        self._task: asyncio.Task | None = None

    def start(self):
        self._task = asyncio.create_task(self._watch())

    def reset(self):
        if self._task:
            self._task.cancel()
        self._task = asyncio.create_task(self._watch())

    def cancel(self):
        if self._task:
            self._task.cancel()
            self._task = None

    async def _watch(self):
        try:
            await asyncio.sleep(self._timeout_seconds)
            logger.info(f"Idle timeout reached after {self._timeout_seconds}s")
            await self._on_timeout()
        except asyncio.CancelledError:
            pass
