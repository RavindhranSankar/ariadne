import hashlib
import os
from pathlib import Path


def ariadne_home() -> Path:
    env = os.getenv("ARIADNE_HOME", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return Path.home() / ".ariadne"


def get_logs_dir() -> Path:
    env = os.getenv("LOGS_DIR", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return ariadne_home() / "logs"


def get_briefs_dir(repo_path: str) -> Path:
    env = os.getenv("ARIADNE_BRIEFS_DIR", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return Path(repo_path).resolve() / ".ariadne" / "briefs"


def get_project_background_default_path(repo_path: str) -> Path:
    repo = Path(repo_path).resolve()
    path_hash = hashlib.sha256(str(repo).encode()).hexdigest()[:8]
    return ariadne_home() / "project-backgrounds" / f"{repo.name}-{path_hash}" / "PROJECT_BACKGROUND.md"
