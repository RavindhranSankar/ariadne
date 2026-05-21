import os
from dataclasses import dataclass
from pathlib import Path

_ARIADNE_DIR = Path(__file__).parent


@dataclass
class AriadneConfig:
    openai_api_key: str
    openai_model: str
    deepgram_api_key: str
    cartesia_api_key: str
    daily_api_key: str
    repo_path: str
    task_timeout_seconds: float
    idle_timeout_seconds: float
    task_queue_max: int
    debug_server_enabled: bool
    user_name: str
    project_name: str
    agent_background_path: str
    project_background_path: str
    codex_bypass_sandbox: bool
    codex_timeout_seconds: float
    logs_dir: str
    briefs_dir: str

    @classmethod
    def from_env(cls) -> "AriadneConfig":
        default_agent_bg = str(_ARIADNE_DIR / "llm_agent" / "AGENT_BACKGROUND.md")
        default_project_bg = str(_ARIADNE_DIR / "llm_agent" / "PROJECT_BACKGROUND.md")
        return cls(
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-4.1"),
            deepgram_api_key=os.getenv("DEEPGRAM_API_KEY", ""),
            cartesia_api_key=os.getenv("CARTESIA_API_KEY", ""),
            daily_api_key=os.getenv("DAILY_API_KEY", ""),
            repo_path=os.getenv("ARIADNE_REPO_PATH", "").strip(),
            task_timeout_seconds=float(os.getenv("ARIADNE_TASK_TIMEOUT_SECONDS", "360")),
            idle_timeout_seconds=float(os.getenv("ARIADNE_IDLE_TIMEOUT_SECONDS", "300")),
            task_queue_max=int(os.getenv("ARIADNE_TASK_QUEUE_MAX", "5")),
            debug_server_enabled=os.getenv("ARIADNE_DEBUG_SERVER_ENABLED", "").lower() in ("1", "true", "yes"),
            user_name=os.getenv("ARIADNE_USER_NAME", "").strip(),
            project_name=os.getenv("ARIADNE_PROJECT_NAME", "").strip(),
            agent_background_path=os.getenv("ARIADNE_AGENT_BACKGROUND_PATH", default_agent_bg),
            project_background_path=os.getenv("ARIADNE_PROJECT_BACKGROUND_PATH", default_project_bg),
            codex_bypass_sandbox=os.getenv("ARIADNE_CODEX_BYPASS_SANDBOX", "").lower() in ("1", "true", "yes"),
            codex_timeout_seconds=float(os.getenv("ARIADNE_CODEX_TIMEOUT_SECONDS", "300")),
            logs_dir=os.getenv("LOGS_DIR", "").strip(),
            briefs_dir=os.getenv("ARIADNE_BRIEFS_DIR", "").strip(),
        )
