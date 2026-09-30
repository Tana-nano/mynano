"""Default locations, derived from environment variables so tests can inject them.

Windows:
  Editor.log  %LOCALAPPDATA%\\Unity\\Editor\\Editor.log
  output      %USERPROFILE%\\Documents\\UploadDoctor
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

from . import APP_NAME


def default_editor_log(env: Mapping[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    local = env.get("LOCALAPPDATA")
    if local:
        # UNVERIFIED: location taken from Unity's manual via search summary (docs.unity3d.com is blocked here).
        return Path(local) / "Unity" / "Editor" / "Editor.log"
    return Path.home() / ".config" / "unity3d" / "Editor.log"


def output_dir(env: Mapping[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    profile = env.get("USERPROFILE")
    documents = Path(profile) / "Documents" if profile else Path.home() / "Documents"
    return documents / APP_NAME
