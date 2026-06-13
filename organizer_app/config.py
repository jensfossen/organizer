from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    app_root: Path
    data_root: Path
    host: str
    port: int
    agent_command: str | None


def get_settings() -> Settings:
    app_root = Path(os.environ.get("ORGANIZER_ROOT", Path.cwd())).resolve()
    data_root = Path(os.environ.get("ORGANIZER_DATA_ROOT", app_root / "data")).resolve()
    host = os.environ.get("ORGANIZER_HOST", "127.0.0.1")
    port = int(os.environ.get("ORGANIZER_PORT", "8765"))
    agent_command = os.environ.get("ORGANIZER_AGENT_COMMAND")
    return Settings(
        app_root=app_root,
        data_root=data_root,
        host=host,
        port=port,
        agent_command=agent_command,
    )
