"""Extract asset references from Unity YAML, .meta and .asmdef texts."""

from __future__ import annotations

import re
from dataclasses import dataclass

# Unity writes cross-asset references as {fileID: N, guid: <32 hex>, type: N} on one line.
YAML_REF = re.compile(r"(?:(\w+):\s*)?\{fileID:\s*(-?\d+),\s*guid:\s*([0-9a-fA-F]{32}),\s*type:\s*(\d+)\}")
# .asmdef / .asmref: "references": ["GUID:<32 hex>"], "reference": "GUID:<32 hex>"
ASMDEF_REF = re.compile(r'"GUID:([0-9a-fA-F]{32})"')

ASMDEF_KEY = "asmdef"
ZERO_GUID = "0" * 32

# Unity serialized-asset extensions: text if "Force Text", otherwise binary.
SERIALIZED_EXTS = frozenset(
    ".prefab .mat .asset .controller .overrideController .anim .mask .unity .physicMaterial .playable .signal "
    ".lighting .renderTexture .flare .guiskin .fontsettings .spriteatlas .terrainlayer .brush .cubemap".lower().split()
)
ASMDEF_EXTS = frozenset((".asmdef", ".asmref"))


@dataclass(frozen=True)
class Ref:
    key: str | None  # m_Shader, m_Script, ... or None for list items
    file_id: int
    guid: str
    type: int


def is_yaml(head: bytes) -> bool:
    return head.lstrip(b"\xef\xbb\xbf").startswith(b"%YAML")


def extract_yaml(text: str) -> list[Ref]:
    out = []
    for m in YAML_REF.finditer(text):
        guid = m.group(3).lower()
        if guid == ZERO_GUID:
            continue
        out.append(Ref(m.group(1), int(m.group(2)), guid, int(m.group(4))))
    return out


def extract_asmdef(text: str) -> list[Ref]:
    return [Ref(ASMDEF_KEY, 0, g.lower(), 0) for g in ASMDEF_REF.findall(text) if g.strip("0")]
