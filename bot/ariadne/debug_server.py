"""
Localhost-only debug server for live Ariadne session inspection.

Endpoints:
  GET /debug/sessions                       — list active sessions
  GET /debug/sessions/{id}                  — session state snapshot
  GET /debug/sessions/{id}/events           — recent events from timeline.jsonl
  GET /debug/sessions/{id}/stream           — SSE live event stream

Config env vars (all optional):
  ARIADNE_DEBUG_SERVER_ENABLED=true
  ARIADNE_DEBUG_SERVER_HOST=127.0.0.1
  ARIADNE_DEBUG_SERVER_PORT=8765
"""

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from aiohttp import web
from loguru import logger

from ariadne.ariadne_session import AriadneSession
from ariadne.utils.paths import get_logs_dir

# Registry of sessions added via register_session().
_sessions: dict[str, AriadneSession] = {}


def register_session(session: AriadneSession):
    _sessions[session.session_id] = session


def unregister_session(session: AriadneSession):
    _sessions.pop(session.session_id, None)


# ------------------------------------------------------------------
# Request handlers
# ------------------------------------------------------------------


async def _handle_list_sessions(request: web.Request) -> web.Response:
    data = [
        {
            "session_id": s.session_id,
            "session_short_id": s.session_short_id,
            "started_at": s.started_at.isoformat(),
            "status": s.status,
        }
        for s in _sessions.values()
    ]
    return web.json_response(data)


async def _handle_session_state(request: web.Request) -> web.Response:
    session_id = request.match_info["session_id"]
    session = _find_session(session_id)
    if session is None:
        raise web.HTTPNotFound(text="Session not found")

    data = {
        "session_id": session.session_id,
        "session_short_id": session.session_short_id,
        "started_at": session.started_at.isoformat(),
        "ended_at": session.ended_at.isoformat() if session.ended_at else None,
        "status": session.status,
        "close_reason": session.close_reason,
        "current_turn_id": session.current_turn_id,
        "last_human_activity": session.last_human_activity.isoformat(),
    }
    return web.json_response(data)


async def _handle_session_events(request: web.Request) -> web.Response:
    session_id = request.match_info["session_id"]
    session = _find_session(session_id)
    if session is None:
        raise web.HTTPNotFound(text="Session not found")

    limit = int(request.rel_url.query.get("limit", "100"))
    events = _read_recent_events(session, limit)
    return web.json_response(events)


async def _handle_session_stream(request: web.Request) -> web.StreamResponse:
    """Server-Sent Events stream of live session events."""
    session_id = request.match_info["session_id"]
    session = _find_session(session_id)
    if session is None:
        raise web.HTTPNotFound(text="Session not found")

    response = web.StreamResponse(
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )
    await response.prepare(request)

    queue = session.logger.add_sse_subscriber()
    try:
        # Send any buffered recent events first so the client isn't blank on connect.
        for event in _read_recent_events(session, limit=50):
            await _write_sse(response, event)

        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
                await _write_sse(response, event)
            except asyncio.TimeoutError:
                # Send a keepalive comment so the connection doesn't time out.
                await response.write(b": keepalive\n\n")
    except (ConnectionResetError, asyncio.CancelledError):
        pass
    finally:
        session.logger.remove_sse_subscriber(queue)

    return response


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _find_session(session_id: str) -> AriadneSession | None:
    # Accept full UUID or short ID.
    if session_id in _sessions:
        return _sessions[session_id]
    for s in _sessions.values():
        if s.session_short_id == session_id:
            return s
    return None


def _read_recent_events(session: AriadneSession, limit: int) -> list[dict]:
    timeline = get_logs_dir() / "session-logs" / session.session_short_id / "timeline.jsonl"
    if not timeline.exists():
        return []
    try:
        lines = timeline.read_text().splitlines()
        recent = lines[-limit:] if len(lines) > limit else lines
        return [json.loads(line) for line in recent if line.strip()]
    except Exception as exc:
        logger.warning(f"Failed to read timeline for debug: {exc}")
        return []


async def _write_sse(response: web.StreamResponse, event: dict):
    payload = f"data: {json.dumps(event)}\n\n"
    await response.write(payload.encode())


# ------------------------------------------------------------------
# Server lifecycle
# ------------------------------------------------------------------


async def start_debug_server() -> web.AppRunner | None:
    if not os.getenv("ARIADNE_DEBUG_SERVER_ENABLED", "").lower() in ("1", "true", "yes"):
        return None

    host = os.getenv("ARIADNE_DEBUG_SERVER_HOST", "127.0.0.1")
    port = int(os.getenv("ARIADNE_DEBUG_SERVER_PORT", "8765"))

    app = web.Application()
    app.router.add_get("/debug/sessions", _handle_list_sessions)
    app.router.add_get("/debug/sessions/{session_id}", _handle_session_state)
    app.router.add_get("/debug/sessions/{session_id}/events", _handle_session_events)
    app.router.add_get("/debug/sessions/{session_id}/stream", _handle_session_stream)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    logger.info(f"Ariadne debug server listening on http://{host}:{port}/debug/sessions")
    return runner


async def stop_debug_server(runner: web.AppRunner | None):
    if runner:
        await runner.cleanup()
