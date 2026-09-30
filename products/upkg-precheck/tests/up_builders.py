"""Build unitypackages and zips in memory for tests (no binary fixtures in the repo)."""

from __future__ import annotations

import gzip
import io
import tarfile
import zipfile
from typing import Iterable

# Real GUIDs from the bundled dictionary. If a rebuild drops them, tests fail on purpose.
LIL_SHADER = "df12117ecd77c31469c224178886498e"  # lilToon Shader/lts.shader
VRC_CORE_EDITOR = "4ecd63eff847044b68db9453ce219299"  # VRCCore-Editor.dll
VRC_PHYSBONE = "2a2c05204084d904aa4945ccff20d8e5"


def g(n: int) -> str:
    """A deterministic fake GUID."""
    return f"a{n:031x}"


def meta(guid: str, refs: Iterable[str] = (), folder: bool = False) -> str:
    lines = ["fileFormatVersion: 2", f"guid: {guid}"]
    if folder:
        lines.append("folderAsset: yes")
    lines += list(refs)
    return "\n".join(lines) + "\n"


def yaml_doc(*body: str) -> bytes:
    return ("%YAML 1.1\n%TAG !u! tag:unity3d.com,2011:\n--- !u!21 &2100000\n" + "\n".join(body) + "\n").encode()


def mat(shader_guid: str, tex_guids: Iterable[str] = (), shader_file_id: int = 4800000) -> bytes:
    body = ["Material:", f"  m_Shader: {{fileID: {shader_file_id}, guid: {shader_guid}, type: 3}}", "  m_SavedProperties:",
            "    m_TexEnvs:"]
    for i, t in enumerate(tex_guids):
        body += [f"    - _Tex{i}:", f"        m_Texture: {{fileID: 2800000, guid: {t}, type: 3}}"]
    return yaml_doc(*body)


def prefab(script_refs: Iterable[tuple[int, str]] = (), material_guids: Iterable[str] = ()) -> bytes:
    body = ["GameObject:", "  m_Name: Root"]
    for fid, sg in script_refs:
        body += ["MonoBehaviour:", f"  m_Script: {{fileID: {fid}, guid: {sg}, type: 3}}"]
    if material_guids:
        body.append("  m_Materials:")
        body += [f"  - {{fileID: 2100000, guid: {m}, type: 2}}" for m in material_guids]
    return yaml_doc(*body)


PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + b"\x00" * 32


def _add(tf: tarfile.TarFile, name: str, data: bytes) -> None:
    ti = tarfile.TarInfo(name)
    ti.size = len(data)
    tf.addfile(ti, io.BytesIO(data))


def make_unitypackage(entries: Iterable[tuple[str, str, bytes | None, str | None]], *,
                      extra_members: Iterable[tarfile.TarInfo | tuple[str, bytes]] = (),
                      asset_first: bool = False, prefix: str = "") -> bytes:
    """entries: (guid, pathname, asset bytes or None for a folder, meta text or None for default)."""
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.GNU_FORMAT) as tf:
        for guid, pathname, asset, meta_text in entries:
            members = [(f"{prefix}{guid}/pathname", pathname.encode("utf-8")),
                       (f"{prefix}{guid}/asset.meta", (meta_text or meta(guid, folder=asset is None)).encode())]
            if asset is not None:
                members.append((f"{prefix}{guid}/asset", asset))
            if asset_first:
                members.reverse()
            for name, data in members:
                _add(tf, name, data)
        for m in extra_members:
            if isinstance(m, tarfile.TarInfo):
                tf.addfile(m, io.BytesIO(b"") if m.isfile() else None)
            else:
                _add(tf, m[0], m[1])
    return gzip.compress(raw.getvalue())


class _SjisInfo(zipfile.ZipInfo):
    """Writes the name as raw cp932 without the UTF-8 flag, like Japanese Windows zippers.

    Relies on the private _encodeFilenameFlags hook; used only in tests.
    """

    def _encodeFilenameFlags(self):  # noqa: N802
        return self.filename.encode("cp932"), self.flag_bits & ~0x800


def make_zip(files: dict[str, bytes], *, sjis_names: Iterable[str] = (), encrypted: Iterable[str] = (),
             deflate64: Iterable[str] = ()) -> bytes:
    sjis, enc = set(sjis_names), set(encrypted)
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            info = _SjisInfo(name) if name in sjis else zipfile.ZipInfo(name)
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, data)
    data = raw.getvalue()
    if enc:
        data = _patch_central(data, enc, flags_or=1)
    if deflate64:
        data = _patch_central(data, set(deflate64), method=9)
    return data


def _patch_central(data: bytes, names: set[str], *, flags_or: int = 0, method: int | None = None) -> bytes:
    """Patch flags / compression method of the central directory entries of the given names."""
    buf = bytearray(data)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        infos = zf.infolist()
    pos = buf.rfind(b"PK\x05\x06")
    cd = int.from_bytes(buf[pos + 16: pos + 20], "little")
    for info in infos:
        assert buf[cd:cd + 4] == b"PK\x01\x02"
        n = int.from_bytes(buf[cd + 28: cd + 30], "little")
        m = int.from_bytes(buf[cd + 30: cd + 32], "little")
        k = int.from_bytes(buf[cd + 32: cd + 34], "little")
        if info.filename in names:
            flags = int.from_bytes(buf[cd + 8: cd + 10], "little") | flags_or
            buf[cd + 8: cd + 10] = flags.to_bytes(2, "little")
            if method is not None:
                buf[cd + 10: cd + 12] = method.to_bytes(2, "little")
        cd += 46 + n + m + k
    return bytes(buf)


def simple_package(extra: Iterable[tuple[str, str, bytes | None, str | None]] = ()) -> bytes:
    """A small, clean outfit package: folder, prefab -> mat -> png, all internal."""
    return make_unitypackage([
        (g(1), "Assets/Shop", None, None),
        (g(2), "Assets/Shop/Outfit.prefab", prefab(material_guids=[g(3)]), None),
        (g(3), "Assets/Shop/Outfit.mat", mat(LIL_SHADER, [g(4)]), None),
        (g(4), "Assets/Shop/Body.png", PNG, None),
        *extra,
    ])

LIL_CS = "ed167612c2b102c46b9c3015d3f5f5df"  # lilToon Editor/GifParser/GifFile.cs
LIL_CS2 = "4770a8d246cd7bf4a860c51a75e7dc0f"
MA_CS = "7ebce0ceba4d48c48992702b5c446936"  # Modular Avatar Editor/ActiveAnimationRetargeter.cs
NDMF_CS = "f13c53def200423bbf3324b26652a61b"
VRCFURY_CS = "00a574f97ce2414bbdfdea0ebffb6c90"
POI_CS = "384236c783ed181459334431beb0f971"


def own(n: int, path: str, data: bytes = PNG) -> tuple[str, str, bytes, None]:
    return (g(n), path, data, None)
