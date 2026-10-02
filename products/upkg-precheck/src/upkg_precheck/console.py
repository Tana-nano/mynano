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


def enable_color(stream: TextIO) -> bool:
    """Turn on ANSI colors for a real console; False for pipes, files and old consoles."""
    try:
        if not stream.isatty():
            return False
    except (AttributeError, ValueError):
        return False
    if sys.platform != "win32":
        return True
    # UNVERIFIED: Windows Terminal handles ANSI by itself; for the classic console this asks for
    # virtual terminal processing and gives up (plain text) if Windows refuses.
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = wintypes.DWORD()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    except Exception:
        return False
