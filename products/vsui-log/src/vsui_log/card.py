"""Share card PNG (1200x675). Text, numbers and flat shapes only; no image assets.

Fonts are looked up on the user's Windows install at runtime and never shipped.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw, ImageFont

from .report import TonightView, fmt_date, fmt_duration, fmt_time

SIZE = (1200, 675)
FONT_CANDIDATES = [
    r"C:\Windows\Fonts\YuGothM.ttc",
    r"C:\Windows\Fonts\meiryo.ttc",
    r"C:\Windows\Fonts\msgothic.ttc",
]
BG = (27, 24, 45)
PANEL = (40, 36, 64)
FG = (236, 235, 245)
MUTED = (161, 159, 182)
ACCENT = (168, 156, 245)


class FontNotFound(Exception):
    pass


FontLoader = Callable[[int], ImageFont.FreeTypeFont | ImageFont.ImageFont]


def find_font(candidates: list[str] | None = None) -> str | None:
    for c in candidates if candidates is not None else FONT_CANDIDATES:
        if Path(c).exists():
            return c
    return None


def card_lines(v: TonightView, streak: int, show_names: bool) -> list[tuple[str, int, tuple[int, int, int]]]:
    """(text, font size, color) from top to bottom. Names appear only if show_names."""
    lines = [(f"{fmt_date(v.date)}の夜", 40, MUTED)]
    if v.measured:
        lines.append((fmt_duration(v.sleep_minutes), 120, ACCENT))
        lines.append((f"入眠 {fmt_time(v.sleep_start)}  →  起床 {fmt_time(v.sleep_end)}", 44, FG))
    else:
        lines.append(("V睡した夜", 96, ACCENT))
        lines.append(("睡眠時間は計測していません", 36, MUTED))
    lines.append((f"一緒に寝た人 {len(v.co_sleepers)}人 ・ 来客 {len(v.visitors)}人", 44, FG))
    if show_names:
        if v.co_sleepers:
            lines.append(("一緒に: " + "、".join(v.co_sleepers), 30, MUTED))
        if v.visitors:
            lines.append(("来客: " + "、".join(x.name for x in v.visitors), 30, MUTED))
    if streak >= 2:
        lines.append((f"{streak}日連続", 36, ACCENT))
    return lines


def render_card(
    v: TonightView,
    streak: int = 0,
    show_names: bool = False,
    font_path: str | None = None,
    font_loader: FontLoader | None = None,
) -> tuple[Image.Image, list[str]]:
    if font_loader is None:
        path = font_path or find_font()
        if path is None:
            raise FontNotFound
        font_loader = lambda size: ImageFont.truetype(path, size)  # noqa: E731
    img = Image.new("RGB", SIZE, BG)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((40, 40, SIZE[0] - 40, SIZE[1] - 40), radius=32, fill=PANEL)
    d.ellipse((SIZE[0] - 190, 70, SIZE[0] - 90, 170), fill=ACCENT)
    d.ellipse((SIZE[0] - 165, 58, SIZE[0] - 65, 158), fill=PANEL)  # crescent
    texts: list[str] = []
    y = 80
    for text, size, color in card_lines(v, streak, show_names):
        font = font_loader(size)
        d.text((90, y), text, font=font, fill=color)
        texts.append(text)
        y += int(size * 1.35)
    footer = "V睡ログ"
    d.text((90, SIZE[1] - 100), footer, font=font_loader(28), fill=MUTED)
    texts.append(footer)
    return img, texts
