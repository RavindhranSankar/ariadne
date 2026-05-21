from pathlib import Path

from loguru import logger
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.services.openai.responses.llm import OpenAIResponsesLLMService

from ariadne.config import AriadneConfig
from ariadne.llm_agent.tools import build_tools_schema

_AGENT_DIR = Path(__file__).resolve().parent
_CORE_INSTRUCTIONS = (_AGENT_DIR / "CORE_INSTRUCTIONS.md").read_text(encoding="utf-8").strip()


class LLMAgent:
    def __init__(self, config: AriadneConfig):
        self._context = LLMContext()
        self._context.set_tools(build_tools_schema())
        self._service = self._create_service(config)

    @property
    def service(self) -> OpenAIResponsesLLMService:
        return self._service

    @property
    def context(self) -> LLMContext:
        return self._context

    def _create_service(self, config: AriadneConfig) -> OpenAIResponsesLLMService:
        identity = self._build_identity(config)
        system_instruction = identity + " " + _CORE_INSTRUCTIONS
        background_context = self._build_background_context(config)

        if background_context:
            system_instruction = (
                f"{system_instruction}\n\n"
                f"{self._build_project_binding(config)}\n\n"
                "The following background context may inform your responses. "
                "AGENT_BACKGROUND is stable Ariadne product context. "
                "PROJECT_BACKGROUND is generated repo orientation and may be stale. "
                "Use enqueue_task(kind='investigation') when precise current-code evidence is needed.\n\n"
                f"{background_context}"
            )

        return OpenAIResponsesLLMService(
            api_key=config.openai_api_key,
            settings=OpenAIResponsesLLMService.Settings(
                model=config.openai_model,
                system_instruction=system_instruction,
            ),
        )

    @staticmethod
    def _build_identity(config: AriadneConfig) -> str:
        if config.user_name:
            identity = f"You are Ariadne, {config.user_name}'s voice-first engineering thought partner and coding assistant."
        else:
            identity = "You are Ariadne, a voice-first engineering thought partner."
        if config.project_name:
            identity += f" The project you are currently helping with is {config.project_name}."
        return identity

    @staticmethod
    def _read_optional_text(path: str) -> str:
        if not path:
            return ""
        try:
            return Path(path).expanduser().read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return ""
        except Exception as exc:
            logger.warning(f"Failed to read background file {path}: {exc}")
            return ""

    def _build_background_context(self, config: AriadneConfig) -> str:
        agent_background = self._read_optional_text(config.agent_background_path)
        project_background = self._read_optional_text(config.project_background_path)

        logger.info(f"AGENT_BACKGROUND loaded: {bool(agent_background)}")
        logger.info(f"PROJECT_BACKGROUND loaded: {bool(project_background)}")
        logger.info(f"ARIADNE_REPO_PATH: {config.repo_path}")

        parts = []
        if agent_background:
            parts.append("## AGENT_BACKGROUND\n\n" + agent_background)
        if project_background:
            parts.append("## PROJECT_BACKGROUND\n\n" + project_background)
        return "\n\n---\n\n".join(parts)

    @staticmethod
    def _build_project_binding(config: AriadneConfig) -> str:
        parts = [
            "## Current Project Binding",
            "",
            "In this Ariadne session, phrases like 'the project', 'the repo', 'the codebase', "
            "and 'our code' refer to the current local project described in PROJECT_BACKGROUND "
            "and rooted at ARIADNE_REPO_PATH.",
        ]
        if config.repo_path:
            parts.append(f"Current repo path: {config.repo_path}")
        parts.append(f"Project background path: {config.project_background_path}")
        parts.append(
            "If PROJECT_BACKGROUND is present, use it as the default project orientation. "
            "Do not ask 'which project?' unless no project background or repo path is available."
        )
        return "\n".join(parts)
