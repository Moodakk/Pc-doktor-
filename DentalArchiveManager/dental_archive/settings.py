"""Per-user persisted application settings.

Stores a small JSON file in the platform application-data directory:
``%APPDATA%\\DentalArchiveManager`` on Windows, ``~/.config/dental-archive-manager``
elsewhere. Used for the UI language and the last used sources/destination.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

_FILE_NAME = "settings.json"


def settings_directory() -> Path:
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA")
        if base:
            return Path(base) / "DentalArchiveManager"
        return Path.home() / "AppData" / "Roaming" / "DentalArchiveManager"
    return Path.home() / ".config" / "dental-archive-manager"


def settings_path() -> Path:
    return settings_directory() / _FILE_NAME


def load_settings() -> dict[str, Any]:
    try:
        payload = json.loads(settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def save_settings(updates: dict[str, Any]) -> None:
    """Merge ``updates`` into the stored settings; failures are non-fatal."""
    current = load_settings()
    current.update(updates)
    try:
        directory = settings_directory()
        directory.mkdir(parents=True, exist_ok=True)
        settings_path().write_text(
            json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        pass
