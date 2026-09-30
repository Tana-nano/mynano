"""Default locations, derived from environment variables so tests can inject them.

Windows:
  VRChat  %LOCALAPPDATA%Low\\VRChat\\VRChat       (OSC\\usr_*\\Avatars\\*.json lives under here)
  output  %USERPROFILE%\\Documents\\OscDoctor     (reports, cache backups)

``OSCDOCTOR_VRC_DIR`` overrides the VRChat folder.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

from . import APP_NAME


def vrc_dir(env: Mapping[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    override = env.get("OSCDOCTOR_VRC_DIR")
    if override:
        return Path(override)
    local = env.get("LOCALAPPDATA")
    if local:
        # %LOCALAPPDATA% is ...\AppData\Local; VRChat writes to ...\AppData\LocalLow.
        return Path(local + "Low") / "VRChat" / "VRChat"
    return Path.home() / ".vrchat"


def output_dir(env: Mapping[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    profile = env.get("USERPROFILE")
    documents = Path(profile) / "Documents" if profile else Path.home() / "Documents"
    return documents / APP_NAME
