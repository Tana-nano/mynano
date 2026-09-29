"""Default locations, derived from environment variables so tests can inject them.

Windows:
  data   %APPDATA%\\VsuiLog                       (config.toml, vsui.db)
  logs   %LOCALAPPDATA%Low\\VRChat\\VRChat         (VRChat output_log_*.txt)
  output %USERPROFILE%\\Documents\\VsuiLog         (reports, cards, CSV)

``VSUILOG_HOME`` puts everything under one folder (portable use and tests).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from . import APP_NAME


@dataclass(frozen=True)
class AppPaths:
    data_dir: Path
    log_dir: Path
    output_dir: Path

    @property
    def config_path(self) -> Path:
        return self.data_dir / "config.toml"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "vsui.db"

    def with_overrides(self, log_dir: str = "", output_dir: str = "") -> "AppPaths":
        return AppPaths(
            data_dir=self.data_dir,
            log_dir=Path(log_dir) if log_dir else self.log_dir,
            output_dir=Path(output_dir) if output_dir else self.output_dir,
        )


def default_paths(env: Mapping[str, str] | None = None) -> AppPaths:
    env = os.environ if env is None else env
    home = env.get("VSUILOG_HOME")
    if home:
        base = Path(home)
        return AppPaths(base / "data", base / "vrchat", base / "output")

    appdata = env.get("APPDATA")
    local = env.get("LOCALAPPDATA")
    profile = env.get("USERPROFILE")
    fallback = Path.home() / ".vsui-log"

    data_dir = Path(appdata) / APP_NAME if appdata else fallback
    # %LOCALAPPDATA% is ...\AppData\Local; VRChat writes to ...\AppData\LocalLow.
    log_dir = Path(local + "Low") / "VRChat" / "VRChat" if local else fallback / "vrchat"
    documents = Path(profile) / "Documents" if profile else Path.home() / "Documents"
    return AppPaths(data_dir, log_dir, documents / APP_NAME)
