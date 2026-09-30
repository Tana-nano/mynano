"""Classify every referenced GUID: internal, other package, builtin, known tool, DLL part, missing."""

from __future__ import annotations

from dataclasses import dataclass, field

from .known import KnownAssets
from .unitypackage import Package

INTERNAL = "internal"
OTHER_PACKAGE = "other_package"
BUILTIN = "builtin"
KNOWN = "known"
DLL = "dll"
MISSING_SCRIPT = "missing_script"
MISSING_SHADER = "missing_shader"
MISSING_OTHER = "missing_other"

MONOSCRIPT_FILE_ID = 11500000
BUILTIN_PREFIX = "0" * 16

CATEGORY_LABELS = {
    INTERNAL: "内部", OTHER_PACKAGE: "同梱の別パッケージ", BUILTIN: "Unity 組み込み", KNOWN: "既知の前提ツール",
    DLL: "DLL 内の部品", MISSING_SCRIPT: "見つからないスクリプト", MISSING_SHADER: "見つからないシェーダー",
    MISSING_OTHER: "見つからないアセット",
}

KIND_BY_FILE_ID = {
    2100000: "マテリアル", 2800000: "テクスチャ", 4300000: "メッシュ", 7400000: "アニメーション",
    9100000: "アニメーターコントローラー", 4800000: "シェーダー", 8300000: "オーディオ", 100100000: "プレハブ",
}
KIND_BY_KEY = {
    "m_SourcePrefab": "プレハブ", "m_Mesh": "メッシュ", "m_Avatar": "モデル（FBX）", "m_Controller": "アニメーターコントローラー",
    "m_Material": "マテリアル", "m_Texture": "テクスチャ", "asmdef": "アセンブリ定義（asmdef）",
}


@dataclass
class ExtRef:
    """One referenced GUID outside the referring package, as seen from one package."""

    guid: str
    category: str
    known_id: str | None = None
    kind: str = ""
    count: int = 0  # number of references
    referrers: list[str] = field(default_factory=list)  # unique referring pathnames, in order
    packages: list[str] = field(default_factory=list)  # OTHER_PACKAGE: where it lives

    @property
    def missing(self) -> bool:
        return self.category in (MISSING_SCRIPT, MISSING_SHADER, MISSING_OTHER)


@dataclass
class PackageRefs:
    package: str
    internal: int = 0
    builtin: int = 0
    external: dict[str, ExtRef] = field(default_factory=dict)  # guid -> ExtRef (not internal, not builtin)


def kind_of(key: str | None, file_id: int) -> str:
    if file_id in KIND_BY_FILE_ID:
        return KIND_BY_FILE_ID[file_id]
    if key in KIND_BY_KEY:
        return KIND_BY_KEY[key]  # type: ignore[index]
    if abs(file_id) >= 10**9:
        # Objects inside prefabs and models (FBX) have large hashed fileIDs.
        return "プレハブかモデル（FBX）の中身"
    return "アセット"


def classify(packages: list[Package], known: KnownAssets) -> list[PackageRefs]:
    where: dict[str, list[str]] = {}
    for p in packages:
        for g in p.entries:
            where.setdefault(g, []).append(p.name)

    result = []
    for p in packages:
        pr = PackageRefs(p.name)
        for e in p.entries.values():
            for r in e.refs:
                if r.guid in p.entries:
                    pr.internal += 1
                    continue
                if r.guid.startswith(BUILTIN_PREFIX):
                    pr.builtin += 1
                    continue
                x = pr.external.get(r.guid)
                if x is None:
                    x = pr.external[r.guid] = ExtRef(r.guid, "")
                x.count += 1
                if e.pathname not in x.referrers:
                    x.referrers.append(e.pathname)
                cat, kind = _category(r.guid, r.key, r.file_id, where, p.name, known)
                if _rank(cat) > _rank(x.category):
                    x.category, x.kind = cat, kind
                    x.known_id = known.by_guid(r.guid) if cat == KNOWN else None
                    x.packages = where.get(r.guid, []) if cat == OTHER_PACKAGE else []
        result.append(pr)
    return result


_RANKS = {"": 0, MISSING_OTHER: 1, MISSING_SHADER: 2, MISSING_SCRIPT: 3, DLL: 4, KNOWN: 5, OTHER_PACKAGE: 6}


def _rank(cat: str) -> int:
    return _RANKS.get(cat, 0)


def _category(guid: str, key: str | None, file_id: int, where: dict[str, list[str]], own: str,
              known: KnownAssets) -> tuple[str, str]:
    if any(n != own for n in where.get(guid, [])):
        return OTHER_PACKAGE, kind_of(key, file_id)
    if known.by_guid(guid):
        return KNOWN, ""
    if key == "m_Script":
        if file_id != MONOSCRIPT_FILE_ID:
            return DLL, "DLL 内の部品"
        return MISSING_SCRIPT, "スクリプト"
    if key == "m_Shader":
        return MISSING_SHADER, "シェーダー"
    return MISSING_OTHER, kind_of(key, file_id)
