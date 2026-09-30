"""Build src/upkg_precheck/data/known_assets.json from the distributors' git repositories.

Development tool only (not shipped). It stores GUIDs and paths from `.meta` files, never
the distributors' code or shaders. See tools/README.md for how to run it.

    python tools/build_known_assets.py --work <scratch dir> [--date YYYY-MM-DD]

The network part (git fetch) is kept apart from the pure part that turns `.meta` texts
into the dictionary, so the pure part can be tested without network access.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable, Iterable, Iterator

log = logging.getLogger("build_known_assets")

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "src" / "upkg_precheck" / "data" / "known_assets.json"

GUID_LINE = re.compile(r"^guid:\s*([0-9a-fA-F]{32})\s*$", re.MULTILINE)
STABLE_TAG = re.compile(r"^[vV]?(\d+)\.(\d+)\.(\d+)$")

# Avatar SDK3 DLL GUIDs. Two independent sources agree on each: Modular Avatar prefabs
# reference them via m_Script, and the .dll.meta files of
# https://github.com/CMoyuer/VRChatAvatarSDK3Container carry the same GUIDs.
VRCHAT_SDK_DLLS = {
    "67cc4cb7839cd3741b63733d5adf0442": "Packages/com.vrchat.avatars/Runtime/VRCSDK/Plugins/VRCSDK3A.dll",
    "db48663b319a020429e3b1265f97aff1": "Packages/com.vrchat.base/Runtime/VRCSDK/Plugins/VRCSDKBase.dll",
    "cdfe97a8253414b4bb5dd295880489bd": "Packages/com.vrchat.base/Runtime/VRCSDK/Plugins/VRC.Dynamics.dll",
    "2a2c05204084d904aa4945ccff20d8e5": "Packages/com.vrchat.base/Runtime/VRCSDK/Plugins/VRC.SDK3.Dynamics.PhysBone.dll",
    "80f1b8067b0760e4bb45023bc2e9de66": "Packages/com.vrchat.base/Runtime/VRCSDK/Plugins/VRC.SDK3.Dynamics.Contact.dll",
    "4ecd63eff847044b68db9453ce219299": "Packages/com.vrchat.base/Editor/VRCSDK/Plugins/VRCCore-Editor.dll",
}


# ---------------------------------------------------------------- pure part

def guid_of_meta(text: str) -> str | None:
    m = GUID_LINE.search(text)
    return m.group(1).lower() if m else None


def iter_metas_in_dir(root: Path) -> Iterator[tuple[str, str]]:
    """(repo-relative path of the asset, .meta text) for every .meta under root."""
    for p in sorted(root.rglob("*.meta")):
        rel = p.relative_to(root).as_posix()
        yield rel[: -len(".meta")], p.read_text(encoding="utf-8", errors="replace")


def union_tags(tags: Iterable[tuple[str, Iterable[tuple[str, str]]]],
               mapper: Callable[[str], str | None]) -> dict[str, str]:
    """Union of GUIDs over tags (oldest first). A later tag's path wins for the same GUID."""
    out: dict[str, str] = {}
    for tag, metas in tags:
        for rel, text in metas:
            unity_path = mapper(rel)
            if unity_path is None:
                continue
            guid = guid_of_meta(text)
            if guid is None:
                log.warning("no guid line: %s (%s)", rel, tag)
                continue
            out[guid] = unity_path
    return out


class DuplicateGuidError(Exception):
    pass


def merge_sources(per_source: dict[str, dict[str, str]]) -> dict[str, list[str]]:
    """{guid: [id, path]}; stop when two distributors share a GUID."""
    merged: dict[str, list[str]] = {}
    for sid, guids in per_source.items():
        for guid, path in guids.items():
            if guid in merged and merged[guid][0] != sid:
                raise DuplicateGuidError(f"{guid}: {merged[guid][0]} {merged[guid][1]} / {sid} {path}")
            merged[guid] = [sid, path]
    return dict(sorted(merged.items()))


def _hidden(rel: str) -> bool:
    # Unity ignores folders ending with "~" and starting with "."
    return any(seg.endswith("~") or seg.startswith(".") for seg in rel.split("/"))


def project_mapper(rel: str) -> str | None:
    """Repo laid out as a Unity project: keep Assets/ and Packages/ paths."""
    if _hidden(rel):
        return None
    return rel if rel.startswith(("Assets/", "Packages/")) else None


def package_mapper(package: str, assets_roots: tuple[str, ...] = ()) -> Callable[[str], str | None]:
    """Repo root is a UPM package (or, in old tags, a Unity project containing it)."""

    def mapper(rel: str) -> str | None:
        if _hidden(rel):
            return None
        own = f"Packages/{package}/"
        if rel.startswith("Packages/"):
            # Old tags were a Unity project: keep only this package, not vendored ones.
            return rel if rel.startswith(own) else None
        if rel.startswith("Assets/"):
            # Old tags: the dev project's own assets (tests, samples) were never distributed.
            return rel if rel.split("/")[1] in assets_roots else None
        for root in assets_roots:
            if rel == root or rel.startswith(root + "/"):
                return "Assets/" + rel
        return own + rel

    return mapper


def select_tags(tags: Iterable[str], rule: str) -> list[str]:
    """Stable tags chosen by rule, oldest first.

    minor  : every x.y.0 plus the newest
    majors : the newest of each of the given majors plus the newest ("majors:8,9,10")
    """
    parsed = sorted(((tuple(map(int, m.groups())), t) for t in tags if (m := STABLE_TAG.match(t))))
    if not parsed:
        return []
    chosen = {parsed[-1][1]}
    if rule == "minor":
        chosen |= {t for v, t in parsed if v[2] == 0}
    elif rule.startswith("majors:"):
        for major in map(int, rule.split(":", 1)[1].split(",")):
            last = [t for v, t in parsed if v[0] == major]
            if last:
                chosen.add(last[-1])
    return [t for _, t in parsed if t in chosen]


# ---------------------------------------------------------------- source list

@dataclass
class Source:
    id: str
    name: str
    repo: str | None
    rule: str  # tag rule, or "HEAD"
    mapper: Callable[[str], str | None] | None
    prefixes: list[str]
    bundle: str
    guidance: str
    source_url: str
    get_url: str
    draft: str
    tag_list: list[str] = field(default_factory=list)


SOURCES = [
    Source(
        "vrchat-sdk", "VRChat SDK", None, "", None,
        ["Packages/com.vrchat.", "Assets/VRCSDK/", "Assets/Udon/", "Assets/VRChat Examples/"],
        "forbidden",
        "VRChat SDK は VCC（VRChat Creator Companion）からのみ入手するもので、ライセンス上、第三者に配布できません。",
        "https://hello.vrchat.com/legal/sdk",
        "https://vcc.docs.vrchat.com/",
        "VRChat Creator Companion（VCC）で作ったアバター用プロジェクト（VRChat SDK - Avatars）: https://vcc.docs.vrchat.com/",
    ),
    Source(
        "liltoon", "lilToon", "https://github.com/lilxyzw/lilToon", "minor", project_mapper,
        ["Assets/lilToon/", "Packages/jp.lilxyzw.liltoon/"],
        "separate",
        "lilToon の配布元は「シェーダー本体と制作物を 1 つの unitypackage にまとめる方法は、古いバージョンで上書きしてしまう"
        "問題が発生する可能性があるため非推奨」としています（別の unitypackage のまま同梱するか、VCC からの導入を案内するのがおすすめです）。",
        "https://github.com/lilxyzw/lilToon/blob/Document/docs/ja_JP/first.md",
        "https://booth.pm/ja/items/3087170",
        "lilToon: https://booth.pm/ja/items/3087170 （公式は VCC からの導入を推奨しています）",
    ),
    Source(
        "poiyomi", "Poiyomi Toon Shader", "https://github.com/poiyomi/PoiyomiToonShader", "majors:8,9,10",
        package_mapper("com.poiyomi.toon", ("_PoiyomiShaders",)),
        ["Assets/_PoiyomiShaders/", "Packages/com.poiyomi.toon/"],
        "separate",
        "Poiyomi の配布元は「_PoiyomiShaders フォルダをアセットのパッケージに入れないでください」としています"
        "（リリースページへ案内するか、アセットとは別のパッケージとして同梱します）。",
        "https://github.com/poiyomi/PoiyomiToonShader",
        "https://github.com/poiyomi/PoiyomiToonShader/releases",
        "Poiyomi Toon Shader: https://github.com/poiyomi/PoiyomiToonShader/releases",
    ),
    Source(
        "modular-avatar", "Modular Avatar", "https://github.com/bdunderscore/modular-avatar", "minor",
        package_mapper("nadena.dev.modular-avatar"),
        ["Packages/nadena.dev.modular-avatar/"],
        "discouraged",
        "Modular Avatar の配布元は、同梱はライセンス上許可されるものの、古い版を入れて他のプレハブを壊す恐れがあるため、"
        "公式の配布元へ案内することを強く勧めています。",
        "https://github.com/bdunderscore/modular-avatar/blob/main/docs~/docs/distributing-prefabs/index.md",
        "https://modular-avatar.nadena.dev/",
        "Modular Avatar: https://modular-avatar.nadena.dev/ （NDMF も一緒に入ります）",
    ),
    Source(
        "ndmf", "NDMF", "https://github.com/bdunderscore/ndmf", "minor",
        package_mapper("nadena.dev.ndmf"),
        ["Packages/nadena.dev.ndmf/"],
        "discouraged",
        "NDMF は Modular Avatar などの土台になるツールです。Modular Avatar と同じく、同梱せず公式の配布元へ案内することが勧められています。",
        "https://github.com/bdunderscore/modular-avatar/blob/main/docs~/docs/distributing-prefabs/index.md",
        "https://modular-avatar.nadena.dev/",
        "NDMF（Modular Avatar と一緒に入ります）: https://modular-avatar.nadena.dev/",
    ),
    Source(
        "vrcfury", "VRCFury", "https://github.com/VRCFury/VRCFury", "HEAD",
        package_mapper("com.vrcfury.vrcfury"),
        ["Packages/com.vrcfury.vrcfury/"],
        "forbidden",
        "VRCFury の商用ライセンスは「購入者が公式の配布元から直接ダウンロードすること」「製品と一緒に再配布しないこと」を条件にしています。",
        "https://github.com/VRCFury/VRCFury/blob/main/LICENSE.md",
        "https://vcc.vrcfury.com",
        "VRCFury: https://vcc.vrcfury.com",
    ),
]


def vrcfury_mapper(rel: str) -> str | None:
    # The package lives in com.vrcfury.vrcfury/ at the repo root.
    head = "com.vrcfury.vrcfury/"
    if _hidden(rel) or not rel.startswith(head):
        return None
    return "Packages/" + rel


SOURCES[-1].mapper = vrcfury_mapper


def build_document(per_source: dict[str, dict[str, str]], tags: dict[str, list[str]], built: str) -> dict:
    ids = {}
    for s in SOURCES:
        ids[s.id] = {
            "name": s.name, "prefixes": s.prefixes, "bundle": s.bundle, "guidance": s.guidance,
            "source_url": s.source_url, "get_url": s.get_url, "draft": s.draft,
            "repo": s.repo, "tags": tags.get(s.id, []),
        }
    return {"format": 1, "built": built, "ids": ids, "guids": merge_sources(per_source)}


# ---------------------------------------------------------------- network part

def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


def remote_tags(url: str) -> list[str]:
    out = subprocess.run(["git", "ls-remote", "--tags", url], check=True, capture_output=True, text=True).stdout
    return [line.split("refs/tags/", 1)[1] for line in out.splitlines() if "refs/tags/" in line and "^{}" not in line]


def metas_at(repo: Path, ref: str) -> list[tuple[str, str]]:
    names = [n for n in git(repo, "ls-tree", "-r", "--name-only", ref).splitlines() if n.endswith(".meta")]
    if not names:
        return []
    batch = "".join(f"{ref}:{n}\n" for n in names).encode("utf-8")
    raw = subprocess.run(["git", "-C", str(repo), "cat-file", "--batch"], input=batch, check=True,
                         capture_output=True).stdout
    out: list[tuple[str, str]] = []
    pos = 0
    for n in names:
        header_end = raw.index(b"\n", pos)
        size = int(raw[pos:header_end].split()[2])
        body = raw[header_end + 1: header_end + 1 + size]
        pos = header_end + 1 + size + 1
        out.append((n[: -len(".meta")], body.decode("utf-8", errors="replace")))
    return out


def fetch_source(s: Source, work: Path) -> tuple[dict[str, str], list[str]]:
    repo = work / s.id
    if not (repo / ".git").exists():
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        git(repo, "remote", "add", "origin", s.repo)
    if s.rule == "HEAD":
        git(repo, "fetch", "-q", "--depth", "1", "origin", "HEAD")
        sha = git(repo, "rev-parse", "FETCH_HEAD").strip()
        refs = [(f"HEAD@{sha[:12]}", sha)]
    else:
        refs = [(t, t) for t in select_tags(remote_tags(s.repo), s.rule)]
        for tag, _ in refs:
            log.info("fetch %s %s", s.id, tag)
            git(repo, "fetch", "-q", "--depth", "1", "origin", "tag", tag)
    assert s.mapper is not None
    guids = union_tags(((tag, metas_at(repo, ref)) for tag, ref in refs), s.mapper)
    return guids, [tag for tag, _ in refs]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--work", required=True, help="scratch directory for the git clones")
    ap.add_argument("--date", default=date.today().isoformat())
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)
    per_source: dict[str, dict[str, str]] = {"vrchat-sdk": dict(VRCHAT_SDK_DLLS)}
    tags: dict[str, list[str]] = {}
    for s in SOURCES:
        if s.repo is None:
            continue
        per_source[s.id], tags[s.id] = fetch_source(s, work)
        log.info("%s: %d guids from %d refs", s.id, len(per_source[s.id]), len(tags[s.id]))
    doc = build_document(per_source, tags, args.date)
    Path(args.out).write_text(json.dumps(doc, ensure_ascii=False, indent=0, sort_keys=False) + "\n", encoding="utf-8")
    log.info("wrote %s (%d guids)", args.out, len(doc["guids"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
