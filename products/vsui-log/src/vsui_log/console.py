"""Console safety on Windows: never crash on characters the code page lacks."""

from __future__ import annotations

import io
import sys
from typing import TextIO


def setup_console(*streams: TextIO) -> None:
    """Keep the console's encoding (cp932 on Japanese Windows) but replace unencodable chars."""
    for s in streams or (sys.stdout, sys.stderr):
        if isinstance(s, io.TextIOWrapper):
            try:
                s.reconfigure(errors="replace")
            except (AttributeError, ValueError):
                pass
