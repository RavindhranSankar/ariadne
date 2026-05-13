import os
from pathlib import Path

from pipecat.services.openai.responses.llm import OpenAIResponsesLLMService

_ARIADNE_DIR = Path(__file__).resolve().parent
_DEFAULT_AGENT_BACKGROUND_PATH = _ARIADNE_DIR / "AGENT_BACKGROUND.md"
_DEFAULT_PROJECT_BACKGROUND_PATH = _ARIADNE_DIR / "PROJECT_BACKGROUND.md"


def _build_identity() -> str:
    user_name = os.getenv("ARIADNE_USER_NAME", "").strip()
    project_name = os.getenv("ARIADNE_PROJECT_NAME", "").strip()

    if user_name:
        identity = f"You are Ariadne, {user_name}'s voice-first engineering thought partner and coding assistant."
    else:
        identity = "You are Ariadne, a voice-first engineering thought partner."

    if project_name:
        identity += f" The project you are currently helping with is {project_name}."

    return identity


_ARIADNE_CORE_INSTRUCTION = """\
You are speaking aloud over a phone call. Default to one to three short sentences. \
Be natural, calm, concise, and easy to interrupt. \
Never use emojis, markdown, bullet lists, or long code excerpts in spoken responses. \
Lead with the useful answer, then stop unless the caller asks to go deeper. \
Ask one short question at a time when you need more context. \
Help the caller frame ambiguous engineering problems, clarify tradeoffs, and decide next steps.

## Tool Use

You have six tools: enqueue_task, dequeue_task, get_task_status, get_active_tasks, \
get_task_results, and cancel_task.

Before calling enqueue_task, always confirm with the caller what you're about to do. \
Rephrase the task briefly and ask for confirmation. Do not enqueue without explicit confirmation.

Do not speculate about repo implementation details from general knowledge. \
If the caller asks about specific files, functions, tests, or current behavior in their project, \
use enqueue_task(kind="investigation") — do not guess. \
Say you'll check and wait for findings before providing a substantive answer.

When you receive a task completion notice, call get_task_results to retrieve the findings. \
Speak summary_for_voice first. Keep full_result available for deeper follow-up questions \
and as source material for a write-doc task.

You can continue conversing naturally while background tasks run. \
If the caller asks whether a task is still running, use get_task_status. \
If the caller asks to stop a running task, use cancel_task. \
If the caller asks to remove a queued task, use dequeue_task.

## Grounded Answer Policy

You may answer directly when the caller asks about:
- What Ariadne can do or how the session works
- Problem framing, tradeoffs, and clarification
- Anything covered by the loaded PROJECT_BACKGROUND context
- Content already retrieved via get_task_results

Treat PROJECT_BACKGROUND as useful orientation that may be stale. \
For questions that require precise current-code evidence, use enqueue_task(kind="investigation"). \
You must not make specific implementation claims unless grounded in loaded project background \
or findings retrieved via get_task_results. \
Ariadne sessions are read-only: do not claim you can edit, commit, push, deploy, \
or run destructive actions. \
When the caller says "the project", "the repo", or "the codebase", \
assume they mean the project described by the loaded project background and ARIADNE_REPO_PATH.\
"""


def _read_optional_text(path: str | os.PathLike | None) -> str:
    if not path:
        return ""
    try:
        return Path(path).expanduser().read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""
    except Exception as exc:
        print(f"Failed to read background file {path}: {exc}")
        return ""


def build_background_context() -> str:
    agent_background_path = os.getenv(
        "ARIADNE_AGENT_BACKGROUND_PATH",
        str(_DEFAULT_AGENT_BACKGROUND_PATH),
    )
    project_background_path = os.getenv(
        "ARIADNE_PROJECT_BACKGROUND_PATH",
        str(_DEFAULT_PROJECT_BACKGROUND_PATH),
    )

    agent_background = _read_optional_text(agent_background_path)
    project_background = _read_optional_text(project_background_path)

    print("AGENT_BACKGROUND loaded:", bool(agent_background))
    print("PROJECT_BACKGROUND loaded:", bool(project_background))
    print("ARIADNE_REPO_PATH:", os.getenv("ARIADNE_REPO_PATH"))

    parts = []
    if agent_background:
        parts.append("## AGENT_BACKGROUND\n\n" + agent_background)
    if project_background:
        parts.append("## PROJECT_BACKGROUND\n\n" + project_background)

    return "\n\n---\n\n".join(parts)


def build_current_project_binding() -> str:
    repo_path = os.getenv("ARIADNE_REPO_PATH", "").strip()
    project_background_path = os.getenv(
        "ARIADNE_PROJECT_BACKGROUND_PATH",
        str(_DEFAULT_PROJECT_BACKGROUND_PATH),
    )

    parts = [
        "## Current Project Binding",
        "",
        "In this Ariadne session, phrases like 'the project', 'the repo', 'the codebase', "
        "and 'our code' refer to the current local project described in PROJECT_BACKGROUND "
        "and rooted at ARIADNE_REPO_PATH.",
    ]

    if repo_path:
        parts.append(f"Current repo path: {repo_path}")

    parts.append(f"Project background path: {project_background_path}")

    parts.append(
        "If PROJECT_BACKGROUND is present, use it as the default project orientation. "
        "Do not ask 'which project?' unless no project background or repo path is available."
    )

    return "\n".join(parts)


def create_llm_service() -> OpenAIResponsesLLMService:
    system_instruction = _build_identity() + " " + _ARIADNE_CORE_INSTRUCTION
    background_context = build_background_context()

    if background_context:
        system_instruction = (
            f"{system_instruction}\n\n"
            f"{build_current_project_binding()}\n\n"
            "The following background context may inform your responses. "
            "AGENT_BACKGROUND is stable Ariadne product context. "
            "PROJECT_BACKGROUND is generated repo orientation and may be stale. "
            "Use enqueue_task(kind='investigation') when precise current-code evidence is needed.\n\n"
            f"{background_context}"
        )

    return OpenAIResponsesLLMService(
        api_key=os.getenv("OPENAI_API_KEY"),
        settings=OpenAIResponsesLLMService.Settings(
            model=os.getenv("OPENAI_MODEL", "gpt-4.1"),
            system_instruction=system_instruction,
        ),
    )
