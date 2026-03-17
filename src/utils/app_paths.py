from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIR_NAME = "Financial Automation"


def is_packaged_app() -> bool:
    """Return True when running from a bundled executable."""
    return bool(
        getattr(sys, "frozen", False)
        or getattr(sys, "_MEIPASS", None)
        or "__compiled__" in globals()
    )


def get_project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def get_resource_root() -> Path:
    if is_packaged_app():
        return Path(sys.executable).resolve().parent
    return get_project_root()


def get_user_data_root() -> Path:
    if os.name == "nt":
        base_dir = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base_dir = Path.home() / "Library" / "Application Support"
    else:
        base_dir = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))

    return base_dir / APP_DIR_NAME


def get_runtime_root() -> Path:
    root = get_user_data_root() if is_packaged_app() else get_project_root()
    root.mkdir(parents=True, exist_ok=True)
    return root


def get_runtime_subdir(*parts: str) -> Path:
    path = get_runtime_root().joinpath(*parts)
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_log_file_path() -> Path:
    return get_runtime_subdir("logs") / "app.log"


def get_asset_path(*parts: str) -> Path:
    return get_resource_root().joinpath("assets", *parts)
