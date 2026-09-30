"""Known third-party assets: GUID dictionary and path prefixes (data/known_assets.json)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources

# Order used in the draft's "導入に必要なもの" and in P19.
ORDER = ("vrchat-sdk", "liltoon", "poiyomi", "modular-avatar", "ndmf", "vrcfury")

# Bundle policy per distributor (see spec "同梱ルールの根拠").
BUNDLE_FORBIDDEN = "forbidden"      # vrcfury, vrchat-sdk
BUNDLE_DISCOURAGED = "discouraged"  # modular-avatar, ndmf
BUNDLE_SEPARATE = "separate"        # liltoon, poiyomi: allowed as their own package


class DictionaryError(Exception):
    pass


@dataclass(frozen=True)
class KnownId:
    id: str
    name: str
    prefixes: tuple[str, ...]
    bundle: str
    guidance: str
    source_url: str
    get_url: str
    draft: str


@dataclass(frozen=True)
class Match:
    id: str
    exact: bool  # True: GUID hit. False: path prefix only.


class KnownAssets:
    # UNVERIFIED: VRChat SDK is recognized by 6 avatar DLL GUIDs from secondary sources and path prefixes only.
    def __init__(self, doc: dict) -> None:
        try:
            self.built: str = doc["built"]
            self.ids: dict[str, KnownId] = {
                k: KnownId(k, v["name"], tuple(v["prefixes"]), v["bundle"], v["guidance"],
                           v["source_url"], v["get_url"], v["draft"])
                for k, v in doc["ids"].items()
            }
            self.guids: dict[str, str] = {g: v[0] for g, v in doc["guids"].items()}
            self.paths: dict[str, str] = {g: v[1] for g, v in doc["guids"].items()}
        except (KeyError, TypeError, IndexError) as e:
            raise DictionaryError(f"辞書の形式が正しくありません: {e}") from e
        missing = [i for i in ORDER if i not in self.ids]
        if missing:
            raise DictionaryError(f"辞書に項目がありません: {', '.join(missing)}")
        # Longest prefix first so a specific prefix wins over a general one.
        self._prefixes = sorted(((p, k) for k, v in self.ids.items() for p in v.prefixes),
                                key=lambda t: -len(t[0]))

    def by_guid(self, guid: str) -> str | None:
        return self.guids.get(guid)

    def by_path(self, pathname: str) -> str | None:
        for prefix, kid in self._prefixes:
            if pathname.startswith(prefix):
                return kid
        return None

    def identify(self, guid: str, pathname: str) -> Match | None:
        kid = self.by_guid(guid)
        if kid:
            return Match(kid, True)
        kid = self.by_path(pathname)
        return Match(kid, False) if kid else None

    def name(self, kid: str) -> str:
        return self.ids[kid].name


def _no_duplicates(pairs: list[tuple[str, object]]) -> dict:
    out: dict = {}
    for k, v in pairs:
        if k in out:
            raise DictionaryError(f"辞書のキーが重複しています: {k}")
        out[k] = v
    return out


def parse(text: str) -> KnownAssets:
    try:
        doc = json.loads(text, object_pairs_hook=_no_duplicates)
    except json.JSONDecodeError as e:
        raise DictionaryError(f"辞書を読めません: {e}") from e
    return KnownAssets(doc)


_cache: KnownAssets | None = None


def load() -> KnownAssets:
    """The bundled dictionary (cached)."""
    global _cache
    if _cache is None:
        try:
            text = resources.files("upkg_precheck").joinpath("data/known_assets.json").read_text(encoding="utf-8")
        except OSError as e:
            raise DictionaryError(f"辞書を読めません: {e}") from e
        _cache = parse(text)
    return _cache
