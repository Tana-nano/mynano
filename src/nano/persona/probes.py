"""プローブ定義の読み込み。

YAML ライブラリを入れずに、自前の最小パーサで済ませる。
外部依存を1つ減らすことは、10年後に動く確率を1つ上げること。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class Probe:
    id: str
    category: str
    prompt: str


def load(path: str | Path) -> list[Probe]:
    path = Path(path)
    if not path.exists():
        return []
    probes: list[Probe] = []
    current: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        stripped = line.strip()
        if stripped.startswith("- "):
            if current.get("id"):
                probes.append(_build(current))
            current = {}
            stripped = stripped[2:]
        key, _, value = stripped.partition(":")
        if value or key:
            current[key.strip()] = value.strip().strip('"')
    if current.get("id"):
        probes.append(_build(current))
    return probes


def _build(data: dict[str, str]) -> Probe:
    return Probe(
        id=data.get("id", ""), category=data.get("category", ""), prompt=data.get("prompt", "")
    )
