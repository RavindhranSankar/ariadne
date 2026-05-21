import asyncio
import os
import re
import time
from pathlib import Path

from loguru import logger

from ariadne.ariadne_session import AriadneSession
from ariadne.task_result import TaskResult

_RULES_PATH = Path(__file__).parent / "ARIADNE-AGENT-RULES.md"
_PROMPT_TEMPLATE = (Path(__file__).parent / "INVESTIGATION_PROMPT.md").read_text(encoding="utf-8")

_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"Bearer [A-Za-z0-9\-._~+/]+=*"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(
        r"-----BEGIN [A-Z ]* PRIVATE KEY-----.*?-----END [A-Z ]* PRIVATE KEY-----",
        re.DOTALL,
    ),
]


def _parse_investigation_result(raw: str) -> TaskResult:
    """
    Parse the 2-part Codex response into voice_summary and context.
    Falls back gracefully if the expected format wasn't followed.
    """
    summary = ""
    full = raw

    voice_marker = "## Summary For Voice"
    full_marker = "## Full Result"

    voice_idx = raw.find(voice_marker)
    full_idx = raw.find(full_marker)

    if voice_idx != -1 and full_idx != -1 and full_idx > voice_idx:
        summary = raw[voice_idx + len(voice_marker):full_idx].strip()
        full = raw[full_idx + len(full_marker):].strip()
    elif voice_idx != -1:
        summary = raw[voice_idx + len(voice_marker):].strip()
        full = raw
    else:
        paragraphs = [p.strip() for p in raw.split("\n\n") if p.strip()]
        summary = paragraphs[0] if paragraphs else raw

    return TaskResult(voice_summary=summary, context=full)


def _redact(text: str) -> str:
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[REDACTED_SECRET]", text)
    return text


class Investigator:
    def __init__(self, *, repo_path: str, session: AriadneSession, codex_timeout_seconds: float = 300.0):
        self._repo_path = repo_path
        self._session = session
        self._codex_timeout = codex_timeout_seconds
        self._rules = self._load_rules()
        self._safe = self._validate_paths()

    def _load_rules(self) -> str:
        try:
            return _RULES_PATH.read_text()
        except Exception as exc:
            logger.error(f"Failed to load ARIADNE-AGENT-RULES.md: {exc}")
            return ""

    def _validate_paths(self) -> bool:
        if not self._repo_path:
            logger.error("ARIADNE_REPO_PATH is not set — Investigator will not run")
            return False

        repo = Path(self._repo_path).resolve()

        if not repo.exists():
            logger.error(f"ARIADNE_REPO_PATH does not exist: {repo}")
            return False

        if not repo.is_dir():
            logger.error(f"ARIADNE_REPO_PATH is not a directory: {repo}")
            return False

        logs_dir = os.getenv("LOGS_DIR", "")
        if logs_dir:
            logs = Path(logs_dir).resolve()
            try:
                logs.relative_to(repo)
                logger.error(
                    f"LOGS_DIR ({logs}) is inside ARIADNE_REPO_PATH ({repo}) — "
                    "Investigator will not run."
                )
                return False
            except ValueError:
                pass

        logger.info(f"Investigator path validation passed: repo={repo}")
        return True

    async def investigate(
        self,
        task: str,
        turn_id: str | None,
        investigation_id: str,
    ) -> TaskResult | None:
        """
        Run a read-only Codex investigation for `task`.
        Returns TaskResult on success, None on failure.
        """
        if not self._safe:
            self._session.logger.log(
                "repo-investigator",
                "repo-investigator.error",
                {"error": "Investigator not launched: path validation failed at startup"},
                turn_id=turn_id,
                investigation_id=investigation_id,
            )
            return None

        prompt = _PROMPT_TEMPLATE.format(rules=self._rules, task=task).strip()

        self._session.logger.log(
            "repo-investigator",
            "repo-investigator.request",
            {"repo_path": self._repo_path, "task": task},
            turn_id=turn_id,
            investigation_id=investigation_id,
        )

        start = time.monotonic()
        proc = None
        try:
            # In Docker the bubblewrap sandbox can't create user namespaces;
            # the bypass flag is safe because the repo mount is already :ro.
            bypass = os.getenv("ARIADNE_CODEX_BYPASS_SANDBOX", "").lower() in ("1", "true", "yes")
            sandbox_args = (
                ["--dangerously-bypass-approvals-and-sandbox"]
                if bypass
                else ["--sandbox", "read-only"]
            )

            proc = await asyncio.create_subprocess_exec(
                "codex",
                "exec",
                "--cd",
                self._repo_path,
                *sandbox_args,
                "--skip-git-repo-check",
                "-",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await asyncio.wait_for(
                proc.communicate(prompt.encode("utf-8")),
                timeout=self._codex_timeout,
            )

            duration_ms = int((time.monotonic() - start) * 1000)
            raw = _redact(stdout.decode("utf-8", errors="replace").strip())

            if raw:
                self._session.logger.log(
                    "repo-investigator",
                    "repo-investigator.response",
                    {"stdout": raw, "duration_ms": duration_ms},
                    turn_id=turn_id,
                    investigation_id=investigation_id,
                )
                self._session.logger.append_transcript_codex(turn_id or "", investigation_id, raw)
                logger.info(f"Investigator response:\n{raw}")

            if stderr:
                stderr_text = _redact(stderr.decode("utf-8", errors="replace"))
                self._session.logger.log(
                    "repo-investigator",
                    "repo-investigator.stderr",
                    {"stderr": stderr_text},
                    turn_id=turn_id,
                    investigation_id=investigation_id,
                )
                logger.warning(f"Investigator stderr:\n{stderr_text}")

            if not raw:
                return None

            return _parse_investigation_result(raw)

        except asyncio.TimeoutError:
            if proc:
                proc.kill()
            self._session.logger.log(
                "repo-investigator",
                "repo-investigator.timeout",
                {},
                turn_id=turn_id,
                investigation_id=investigation_id,
            )
            logger.warning("Investigator request timed out")
            return None

        except Exception as exc:
            self._session.logger.log(
                "repo-investigator",
                "repo-investigator.error",
                {"error": str(exc)},
                turn_id=turn_id,
                investigation_id=investigation_id,
            )
            logger.exception(f"Investigator request failed: {exc}")
            return None
