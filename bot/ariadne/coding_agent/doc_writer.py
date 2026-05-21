import os
import re
from datetime import datetime
from pathlib import Path

import openai
from loguru import logger

from ariadne.ariadne_session import AriadneSession
from ariadne.task_result import TaskArtifact, TaskResult
from ariadne.utils.paths import get_briefs_dir

_BRIEF_PROMPT_TEMPLATE = (Path(__file__).parent / "BRIEF_PROMPT.md").read_text(encoding="utf-8")


def _is_ariadne_dir_gitignored(repo_path: str) -> bool:
    gitignore = Path(repo_path) / ".gitignore"
    if not gitignore.exists():
        return False
    lines = gitignore.read_text(encoding="utf-8").splitlines()
    return any(line.strip() in (".ariadne", ".ariadne/") for line in lines)


def _slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    text = text.strip("-")
    return text[:60] or "implementation-brief"


class DocWriter:
    def __init__(self, *, session: AriadneSession, repo_path: str):
        self._session = session
        self._repo_path = repo_path

    async def write_doc(self, problem_context: str) -> TaskResult | None:
        """
        Generate an implementation brief from problem_context and save it to the repo.
        Returns TaskResult on success, None on failure.
        """
        if not self._repo_path:
            logger.error("DocWriter: repo_path is not set")
            return None

        self._session.logger.log(
            "runtime",
            "runtime.implementation_doc_started",
            {"turn_id": self._session.current_turn_id},
            turn_id=self._session.current_turn_id,
        )

        try:
            content, title = await self._generate_brief(problem_context)
        except Exception as exc:
            logger.exception(f"DocWriter: OpenAI call failed: {exc}")
            self._session.logger.log(
                "runtime",
                "runtime.implementation_doc_error",
                {"error": str(exc)},
                turn_id=self._session.current_turn_id,
            )
            return None

        slug = _slugify(title)
        timestamp = datetime.now().strftime("%m%d-%H%M")
        filename = f"ariadne-{slug}-{timestamp}.md"

        output_dir = get_briefs_dir(self._repo_path)
        output_path = output_dir / filename

        if not _is_ariadne_dir_gitignored(self._repo_path):
            logger.warning(
                f"'{self._repo_path}/.ariadne/' is not listed in .gitignore. "
                "Add '.ariadne/' to avoid accidentally committing session artifacts."
            )

        try:
            output_path.resolve().relative_to(output_dir.resolve())
        except ValueError:
            logger.error(f"DocWriter: path escape detected: {output_path}")
            return None

        if not filename.startswith("ariadne-") or not filename.endswith(".md"):
            logger.error(f"DocWriter: filename safety check failed: {filename}")
            return None

        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path.write_text(content, encoding="utf-8")
        except Exception as exc:
            logger.exception(f"DocWriter: file write failed: {exc}")
            self._session.logger.log(
                "runtime",
                "runtime.implementation_doc_error",
                {"error": str(exc), "path": str(output_path)},
                turn_id=self._session.current_turn_id,
            )
            return None

        self._session.logger.log(
            "runtime",
            "runtime.implementation_doc_written",
            {"path": str(output_path)},
            turn_id=self._session.current_turn_id,
        )
        self._session.logger.append_transcript_doc(str(output_path))
        logger.info(f"DocWriter: brief saved to {output_path}")

        rel_path = str(output_path).replace(str(Path(self._repo_path).resolve()), "").lstrip("/")
        artifact = TaskArtifact(kind="implementation_brief", title=title, path=str(output_path))
        return TaskResult(
            voice_summary=f"Done. I saved the implementation brief to {rel_path}.",
            context=content,
            artifacts=(artifact,),
        )

    async def _generate_brief(self, problem_context: str) -> tuple[str, str]:
        project_bg = ""
        project_bg_path = os.getenv("ARIADNE_PROJECT_BACKGROUND_PATH", "")
        if project_bg_path:
            try:
                project_bg = Path(project_bg_path).read_text(encoding="utf-8").strip()
            except Exception:
                pass

        prompt = _BRIEF_PROMPT_TEMPLATE.format(
            problem_context=problem_context,
            project_background=project_bg or "(not available)",
            generated_at=datetime.utcnow().isoformat() + "Z",
        )

        client = openai.AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        response = await client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4.1"),
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2000,
        )
        content = (response.choices[0].message.content or "").strip()

        title = "implementation-brief"
        for line in content.splitlines():
            if line.startswith("# Implementation Brief:"):
                title = line.replace("# Implementation Brief:", "").strip()
                break

        return content, title
