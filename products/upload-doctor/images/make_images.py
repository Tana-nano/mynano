"""Compose Booth product images (1000x1000) from real screenshots.

No generated artwork: the only pictures are screenshots taken on Windows (images/screens/),
plus three pieces of text on the first image (name, one-line purpose, supported platform).
Renders with the Chromium that Playwright installs (PLAYWRIGHT_BROWSERS_PATH) or $CHROMIUM.

    python products/upload-doctor/images/make_images.py
"""

from __future__ import annotations

import html
import os
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCREENS = Path(os.environ.get("UD_SCREENS", HERE / "screens"))
OUT = Path(os.environ.get("UD_OUT", HERE / "out"))
SIZE = 1000

NAME = "アップロードドクター for VRChat"
PURPOSE = "アバターが上がらない原因を、Unity を開かずに診断"
PLATFORM = "Windows PC 用（Quest 単機では使えません）"

# (output name, screenshot file, crop box (left, top, right, bottom) or None, with text).
# Only the first image carries text. Crops drop the empty console area so the text stays legible;
# they are tuned to the screenshots taken on 2026-10-02 (ng.png 1115x998).
IMAGES = [
    ("01-thumbnail.png", "ng.png", (0, 0, 1115, 541), True),
    ("02-result.png", "ng.png", (0, 0, 1115, 600), False),
    ("03-report.png", "report.png", None, False),
    ("04-clean.png", "clean.png", None, False),
]

# Noto Sans JP (SIL Open Font License), fetched once into images/.fonts/ (not committed).
FONT_DIR = Path(os.environ.get("UD_FONT_DIR", HERE / ".fonts"))
FONT_URL = "https://raw.githubusercontent.com/notofonts/noto-cjk/main/Sans/SubsetOTF/JP/NotoSansJP-{}.otf"
FONT_WEIGHTS = {"Medium": 500, "Bold": 700}

PAGE = """<!doctype html><html lang="ja"><head><meta charset="utf-8">
<style>
{faces}
  html, body {{ margin: 0; width: {size}px; height: {size}px; overflow: hidden; }}
  body {{ background: #10151f; color: #f4f6fa; font-family: 'Noto Sans JP', 'IPAGothic', sans-serif;
         display: flex; flex-direction: column; box-sizing: border-box; padding: {pad}px; gap: 28px; }}
  h1 {{ margin: 0; font-size: 66px; font-weight: 700; line-height: 1.15; }}
  h1 small {{ display: block; font-size: 40px; color: #9fb0c8; }}
  .purpose {{ margin: 0; font-size: 36px; font-weight: 500; color: #ffd166; line-height: 1.35; }}
  .shot {{ flex: 1; min-height: 0; position: relative; }}
  .shot img {{ position: absolute; inset: 0; margin: auto; max-width: 100%; max-height: 100%; border-radius: 10px;
               box-shadow: 0 0 0 2px #2c3647, 0 18px 40px rgba(0,0,0,.45); }}
  .platform {{ margin: 0; font-size: 30px; font-weight: 500; color: #c9d2e0; }}
</style></head><body>
{head}
<div class="shot"><img src="{img}" alt=""></div>
{foot}
</body></html>"""


def chromium() -> str:
    if env := os.environ.get("CHROMIUM"):
        return env
    base = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers"))
    # The headless shell's viewport equals --window-size; full Chrome loses ~90 px to window chrome.
    for pattern in ("chromium_headless_shell-*/chrome-linux/headless_shell", "chromium-*/chrome-linux/chrome"):
        for cand in sorted(base.glob(pattern), reverse=True):
            return str(cand)
    sys.exit("Chromium not found; set CHROMIUM=/path/to/chrome")


def font_faces() -> str:
    FONT_DIR.mkdir(parents=True, exist_ok=True)
    faces = []
    for name, weight in FONT_WEIGHTS.items():
        path = FONT_DIR / f"NotoSansJP-{name}.otf"
        if not path.exists():
            urllib.request.urlretrieve(FONT_URL.format(name), path)
        faces.append(f"@font-face {{ font-family: 'Noto Sans JP'; font-weight: {weight}; src: url('{path.as_uri()}'); }}")
    return "\n".join(faces)


def cropped(shot: Path, box: tuple[int, int, int, int] | None, tmp: Path) -> Path:
    if box is None:
        return shot
    from PIL import Image  # dev-only dependency, used just for cropping

    out = tmp / f"crop-{shot.stem}-{'-'.join(map(str, box))}.png"
    with Image.open(shot) as im:
        im.crop(box).save(out)
    return out


def render(page: str, dest: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "page.html"
        src.write_text(page, encoding="utf-8")
        subprocess.run(
            [chromium(), "--headless", "--no-sandbox", "--hide-scrollbars", "--force-device-scale-factor=1",
             f"--window-size={SIZE},{SIZE}", "--virtual-time-budget=8000", f"--screenshot={dest}", src.as_uri()],
            check=True, capture_output=True,
        )


def main() -> int:
    missing = sorted({s for _, s, _, _ in IMAGES if not (SCREENS / s).exists()})
    if missing:
        print("missing screenshots in images/screens/: " + ", ".join(missing))
        return 1
    OUT.mkdir(exist_ok=True)
    faces = font_faces()
    tmp = Path(tempfile.mkdtemp())
    for out_name, shot, box, with_text in IMAGES:
        title, _, suffix = NAME.partition(" for ")
        head = (
            f'<h1>{html.escape(title)}<small>for {html.escape(suffix)}</small></h1><p class="purpose">{html.escape(PURPOSE)}</p>'
            if with_text else ""
        )
        foot = f'<p class="platform">{html.escape(PLATFORM)}</p>' if with_text else ""
        page = PAGE.format(faces=faces, size=SIZE, pad=56 if with_text else 40, head=head, foot=foot,
                           img=cropped(SCREENS / shot, box, tmp).as_uri())
        render(page, OUT / out_name)
        print(OUT / out_name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
