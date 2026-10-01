"""Judge the records: pure functions from input records to findings (no I/O)."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from . import classify as cl
from .archive import InputRecord, ZipRecord
from .known import BUNDLE_DISCOURAGED, BUNDLE_FORBIDDEN, ORDER, KnownAssets, Match
from .refs import ASMDEF_EXTS, SERIALIZED_EXTS
from .unitypackage import Entry, Package

RED, YELLOW, GREEN = "赤", "黄", "緑"
_SEV_RANK = {RED: 0, YELLOW: 1, GREEN: 2}

EXE_EXTS = frozenset(".exe .bat .cmd .ps1 .vbs .scr .msi .com .jar .sh".split())
SCRIPT_EXTS = frozenset((".cs", ".dll"))
ARCHIVE_EXTS = frozenset((".zip", ".unitypackage"))
RESERVED_NAMES = frozenset(["CON", "PRN", "AUX", "NUL"] + [f"COM{i}" for i in range(1, 10)] + [f"LPT{i}" for i in range(1, 10)])
INVALID_CHARS = re.compile(r'[<>:"|?*\x00-\x1f]')

README_WORDS = ("readme", "read_me", "read me", "説明", "はじめに", "導入", "manual", "howto", "how_to")
README_EXTS = (".txt", ".md", ".pdf", ".html", ".url")
TERMS_WORDS = ("規約", "terms", "license", "licence", "eula", "vn3", "利用")
JUNK_NAMES = (".ds_store", "thumbs.db", "desktop.ini")

KIND_ORDER = ("プレハブ", "マテリアル", "テクスチャ", "メッシュ", "アニメーション", "スクリプト", "その他")
_KIND_BY_EXT = {
    ".prefab": "プレハブ", ".mat": "マテリアル",
    **{e: "テクスチャ" for e in ".png .jpg .jpeg .tga .psd .tif .tiff .bmp .exr .hdr .gif .dds".split()},
    **{e: "メッシュ" for e in ".fbx .obj .blend .dae .3ds .max .ma .mb".split()},
    **{e: "アニメーション" for e in ".anim .controller .overridecontroller .mask .playable".split()},
    **{e: "スクリプト" for e in ".cs .dll .asmdef .asmref".split()},
}

HEDGE = "パッケージの外を参照しています。Unity の標準パッケージや購入者の環境にあるものなら問題ありません。入れ忘れでないか確認してください。"


@dataclass
class Finding:
    code: str
    severity: str
    title: str
    advice: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)
    count: int = 0
    target: str | None = None


@dataclass
class Options:
    max_path: int = 150
    max_referrers: int = 5
    allow_exe: bool = False


@dataclass
class PackageSummary:
    name: str
    kinds: dict[str, int]
    total_size: int
    top_folders: list[str]
    files: int
    folders: int


@dataclass
class Analysis:
    findings: list[Finding]
    refs: list[cl.PackageRefs]
    matches: dict[str, dict[str, Match | None]]  # package -> guid -> match (files only)
    summaries: dict[str, PackageSummary]
    required: list[str]  # known ids the product needs (P19), in ORDER
    bundled: set[str]  # known ids found inside the packages
    common_packages: list[str]  # packages other packages depend on (P23)

    @property
    def not_bundled(self) -> list[str]:
        return [i for i in self.required if i not in self.bundled]


def human_size(n: int) -> str:
    for unit, div in (("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)):
        if n >= div:
            return f"{n / div:.1f} {unit}"
    return f"{n} B"


def kind_of_ext(ext: str) -> str:
    return _KIND_BY_EXT.get(ext, "その他")


def exit_code(findings: list[Finding]) -> int:
    return 1 if any(f.severity == RED for f in findings) else 0


def summary(findings: list[Finding]) -> str:
    c = Counter(f.severity for f in findings)
    return f"赤 {c[RED]} / 黄 {c[YELLOW]} / 緑 {c[GREEN]}"


def sort_findings(findings: list[Finding]) -> list[Finding]:
    return sorted(findings, key=lambda f: (_SEV_RANK[f.severity], f.code))


def _referrers(x: cl.ExtRef, limit: int) -> str:
    shown = ", ".join(x.referrers[:limit])
    more = len(x.referrers) - limit
    return shown + (f" ほか {more} 件" if more > 0 else "")


def is_readme(name: str) -> bool:
    base = name.rsplit("/", 1)[-1].lower()
    return base.endswith(README_EXTS) and any(w in base for w in README_WORDS)


def is_terms(name: str) -> bool:
    base = name.rsplit("/", 1)[-1].lower()
    return any(w in base for w in TERMS_WORDS)


def is_junk(name: str) -> bool:
    low = name.lower()
    base = low.rsplit("/", 1)[-1]
    return "__macosx/" in f"/{low}" or base in JUNK_NAMES or base.endswith(".blend1")


def ext_of(name: str) -> str:
    base = name.rsplit("/", 1)[-1]
    dot = base.rfind(".")
    return base[dot:].lower() if dot > 0 else ""


def zip_counts(z: ZipRecord) -> str:
    readme = sum(1 for f in z.files if is_readme(f.name))
    terms = sum(1 for f in z.files if is_terms(f.name) and not is_readme(f.name))
    other = len(z.files) - readme - terms
    return f"unitypackage {len(z.packages)} 個 / 説明書 {readme} / 規約 {terms} / その他 {other}"


# ---------------------------------------------------------------- per package

def windows_name_problems(path: str) -> list[str]:
    out = []
    for seg in path.split("/"):
        if not seg:
            continue
        stem = seg.split(".", 1)[0].upper()
        if stem in RESERVED_NAMES:
            out.append(f"予約名 {seg}")
        if seg.endswith((" ", ".")):
            out.append(f"末尾が空白かドット「{seg}」")
        if INVALID_CHARS.search(seg):
            out.append(f"使えない文字「{seg}」")
    return out


def summarize(pkg: Package) -> PackageSummary:
    files = pkg.files()
    kinds = Counter(kind_of_ext(e.ext) for e in files)
    top = sorted({e.pathname.split("/")[1] for e in files if e.pathname.startswith("Assets/") and e.pathname.count("/") >= 2})
    return PackageSummary(pkg.name, {k: kinds[k] for k in KIND_ORDER if kinds[k]}, sum(e.size for e in files), top,
                          len(files), len(pkg.entries) - len(files))


def kinds_text(s: PackageSummary) -> str:
    return "、".join(f"{k} {n}" for k, n in s.kinds.items()) or "ファイルなし"


def _package_findings(pkg: Package, pr: cl.PackageRefs, matches: dict[str, Match | None], known: KnownAssets,
                      opts: Options, out: list[Finding]) -> None:
    n = pkg.name
    anomalies: dict[str, list[str]] = {}
    for a in pkg.anomalies:
        anomalies.setdefault(a.code, []).append(a.detail)
    if "P01" in anomalies:
        out.append(Finding("P01", RED, f"{n} を読めません", ["壊れています。Unity で書き出し直してください。"],
                           anomalies["P01"], 1, n))
    if "P02" in anomalies:
        out.append(Finding("P02", RED, f"{n} に危険なインポート先のパスがあります（{len(anomalies['P02'])} 個）",
                           ["絶対パスや「..」を含むパスは、攻撃や破損の疑いがあります。Unity で書き出し直してください。"],
                           anomalies["P02"], len(anomalies["P02"]), n))
    if "P03" in anomalies:
        out.append(Finding("P03", RED, f"{n} に通常のファイル以外（リンクなど）が入っています（{len(anomalies['P03'])} 個）",
                           ["Unity の通常の書き出しでは起きません。書き出し直してください。"],
                           anomalies["P03"], len(anomalies["P03"]), n))
    if "P14" in anomalies:
        out.append(Finding("P14", YELLOW, f"{n} の中身に想定外の形があります（{len(anomalies['P14'])} 個）",
                           ["Unity 以外のツールで作ったか、途中で壊れた可能性があります。Unity で書き出し直すことをおすすめします。"],
                           anomalies["P14"], len(anomalies["P14"]), n))

    files = pkg.files()
    own = [e for e in files if matches[e.guid] is None]
    exact: dict[str, list[Entry]] = {}
    prefix_only: dict[str, list[Entry]] = {}
    for e in files:
        m = matches[e.guid]
        if m is not None:
            (exact if m.exact else prefix_only).setdefault(m.id, []).append(e)

    if files and not own:
        # Only distributor files: judge the package as "bundled as its own package".
        for kid in ORDER:
            es = exact.get(kid, []) + prefix_only.get(kid, [])
            if not es:
                continue
            k = known.ids[kid]
            if k.bundle == BUNDLE_FORBIDDEN:
                out.append(Finding("P05", RED, f"{n} は {k.name} だけでできています",
                                   [f"ライセンス上、同梱できません。削除して、説明書で入手先（{k.get_url}）を案内してください。", k.guidance],
                                   [e.pathname for e in es], len(es), n))
            elif k.bundle == BUNDLE_DISCOURAGED:
                out.append(Finding("P06", YELLOW, f"{n} は {k.name} だけでできています",
                                   [f"同梱は許可されていますが非推奨です。入手先（{k.get_url}）の案内に替えることを検討してください。", k.guidance],
                                   [e.pathname for e in es], len(es), n))
            else:
                out.append(Finding("P07", GREEN, f"{n} は {k.name} だけの別パッケージです",
                                   ["配布元が認める「別パッケージのまま同梱」の形です。版が古くないか確認してください。"],
                                   [e.pathname for e in es], len(es), n))
    else:
        for kid in ORDER:
            es = exact.get(kid)
            if not es:
                continue
            k = known.ids[kid]
            out.append(Finding("P04", RED, f"{n} に {k.name} のファイルが {len(es)} 個入っています",
                               [f"書き出し時に「Include dependencies」で一緒に選ばれた可能性があります。{k.name} を外して書き出し直してください。",
                                k.guidance],
                               [e.pathname for e in es], len(es), n))
        # UNVERIFIED: the folder Poiyomi's "lock" writes optimized shaders to is assumed to be under _PoiyomiShaders/.
        po = [e for kid in ORDER for e in prefix_only.get(kid, [])]
        if po:
            names = "、".join(known.name(kid) for kid in ORDER if kid in prefix_only)
            out.append(Finding("P22", YELLOW, f"{n} に、{names} のフォルダの下にある辞書に無いファイルが {len(po)} 個あります",
                               ["配布元のファイル（新しい版で増えたもの）なら外してください。自分で作ったもの（ロックしたシェーダーなど）なら、"
                                "自分のフォルダに移すことを検討してください。"],
                               [e.pathname for e in po], len(po), n))

    exe = [e for e in files if e.ext in EXE_EXTS]
    if exe:
        sev = YELLOW if opts.allow_exe else RED
        out.append(Finding("P08", sev, f"{n} に実行ファイルが {len(exe)} 個入っています",
                           ["アバター・衣装の unitypackage には通常入りません。意図したものでなければ外してください。"],
                           [e.pathname for e in exe], len(exe), n))

    not_exact = [e for e in files if not (matches[e.guid] and matches[e.guid].exact)]  # type: ignore[union-attr]
    scripts = [e for e in not_exact if e.ext in SCRIPT_EXTS]
    if scripts:
        out.append(Finding("P09", YELLOW, f"{n} にスクリプト（.cs / .dll）が {len(scripts)} 個入っています",
                           ["衣装やアバターには通常入りません。ギミックなら意図どおりか確認してください。"],
                           [e.pathname for e in scripts], len(scripts), n))
    flagged = [e for e in scripts if e.keywords]
    if flagged:
        out.append(Finding("P10", YELLOW, f"{n} に、自動で動く・外部を起動する・通信する処理を含むスクリプトが {len(flagged)} 個あります",
                           ["Unity の起動時に自動で動く、外部プログラムを起動する、ネットワークに接続する処理が書かれています。"
                            "自分で入れたものか確認してください（危険と判定したわけではありません）。"],
                           [f"{e.pathname}（{', '.join(sorted(e.keywords))}）" for e in flagged], len(flagged), n))

    missing: dict[str, list[cl.ExtRef]] = {}
    for x in pr.external.values():
        if x.missing:
            missing.setdefault(x.category, []).append(x)
    lim = opts.max_referrers
    for cat, head, lead in ((cl.MISSING_SCRIPT, "スクリプト", "Missing (Script) の原因になります。"),
                            (cl.MISSING_SHADER, "シェーダー", "ピンク表示の原因になります。"),
                            (cl.MISSING_OTHER, "アセット", "")):
        xs = missing.get(cat)
        if not xs:
            continue
        refs_n = len({r for x in xs for r in x.referrers})
        detail = f"{len(xs)} 種類、参照元 {refs_n} 個"
        if cat == cl.MISSING_OTHER:
            kinds = Counter(x.kind for x in xs)
            detail = f"{len(xs)} 種類: " + "、".join(f"{k} {c}" for k, c in kinds.most_common()) + f"。参照元 {refs_n} 個"
        out.append(Finding("P11", YELLOW, f"{n} がパッケージの外の{head}を参照しています（{detail}）",
                           [s for s in (lead, HEDGE) if s],
                           [f"{x.kind} {x.guid}（参照元: {_referrers(x, lim)}）" for x in xs], len(xs), n))

    binary = [e for e in not_exact if e.ext in SERIALIZED_EXTS and not e.starts_yaml and e.size > 0]
    if binary:
        out.append(Finding("P12", YELLOW, f"{n} にバイナリ形式で保存された Unity のアセットが {len(binary)} 個あります",
                           ["参照を調べられません。Unity の Project Settings > Editor > Asset Serialization Mode を"
                            "「Force Text」にして書き出し直すと調べられます。"],
                           [e.pathname for e in binary], len(binary), n))
    big = [e for e in not_exact if e.too_large and (e.starts_yaml or e.ext in ASMDEF_EXTS or e.ext == ".cs")]
    if big:
        out.append(Finding("P13", YELLOW, f"{n} に大きすぎて参照を調べていないファイルが {len(big)} 個あります",
                           ["--max-text-mb で上限を上げると調べられます。"],
                           [f"{e.pathname}（{human_size(e.size)}）" for e in big], len(big), n))

    long_ = [e for e in own if len(e.pathname) > opts.max_path]
    if long_:
        out.append(Finding("P15", YELLOW, f"{n} にインポート先のパスが {opts.max_path} 文字を超えるファイルが {len(long_)} 個あります",
                           ["Windows ではパスが長いと Unity が扱えないことがあります（Unity Asset Store の投稿規約も 150 文字未満）。"
                            "フォルダ名やファイル名を短くしてください。"],
                           [f"{e.pathname}（{len(e.pathname)} 文字）" for e in long_], len(long_), n))

    win: list[str] = []
    groups: dict[str, list[str]] = {}
    for e in own:
        groups.setdefault(e.pathname.lower(), []).append(e.pathname)
        win += [f"{e.pathname}（{p}）" for p in windows_name_problems(e.pathname)]
    win += [" と ".join(sorted(v)) + "（大文字小文字だけが違う）" for v in groups.values() if len(set(v)) > 1]
    if win:
        out.append(Finding("P16", YELLOW, f"{n} に Windows で扱えない名前が {len(win)} 個あります",
                           ["Windows では同じ名前として扱われるか、作れません。名前を変えてください。"], win, len(win), n))

    direct = [e.pathname for e in own if e.pathname.startswith("Assets/") and e.pathname.count("/") == 1]
    tops = sorted({e.pathname.split("/")[1] for e in own if e.pathname.startswith("Assets/") and e.pathname.count("/") >= 2})
    if direct or len(tops) >= 2:
        out.append(Finding("P17", YELLOW, f"{n} のインポート先が Assets/ の直下に散らばっています",
                           ["購入者がどこに入ったか見失いやすくなります。自分のフォルダ（例: Assets/ショップ名/商品名/）1 つにまとめてください。"],
                           [f"Assets/{t}/" for t in tops] + direct, len(tops) + len(direct), n))

    nested = [e for e in own if e.ext in ARCHIVE_EXTS]
    if nested:
        out.append(Finding("P18", YELLOW, f"{n} の中に zip か unitypackage が {len(nested)} 個入っています",
                           ["意図どおりか確認してください。"], [e.pathname for e in nested], len(nested), n))

    others = [x for x in pr.external.values() if x.category == cl.OTHER_PACKAGE]
    if others:
        by_pkg = {pn for x in others for pn in x.packages}
        out.append(Finding("P23", YELLOW, f"{n} が同梱の別パッケージ（{'、'.join(sorted(by_pkg))}）のファイルを参照しています（{len(others)} 個）",
                           ["購入者が両方インポートする前提です。説明書にインポートの順番を書いてください（共通パッケージ → アバター別パッケージ など）。"],
                           [f"{x.kind} {x.guid}（{'、'.join(x.packages)} にあります。参照元: {_referrers(x, lim)}）" for x in others],
                           len(others), n))

    s = summarize(pkg)
    out.append(Finding("P21", GREEN, f"{n}: {kinds_text(s)}（合計 {human_size(s.total_size)}）",
                       ["説明書の下書きの「同梱物」に載せます。"],
                       [f"Assets/{t}/" for t in s.top_folders], s.files, n))


# ---------------------------------------------------------------- whole run

def _cross(packages: list[Package], matches: dict[str, dict[str, Match | None]], out: list[Finding]) -> None:
    by_guid: dict[str, list[tuple[str, Entry]]] = {}
    by_path: dict[str, set[str]] = {}
    for p in packages:
        for e in p.files():
            if matches[p.name][e.guid] is not None:
                continue
            by_guid.setdefault(e.guid, []).append((p.name, e))
            by_path.setdefault(e.pathname, set()).add(e.guid)
    x01, x02 = [], []
    for g, lst in by_guid.items():
        if len(lst) < 2:
            continue
        if len({e.sha256 for _, e in lst}) > 1:
            x01.append(f"{lst[0][1].pathname}（{' と '.join(pn for pn, _ in lst)}）")
        if len({e.pathname for _, e in lst}) > 1:
            x02.append(" / ".join(f"{e.pathname}（{pn}）" for pn, e in lst))
    x03 = []
    for path, guids in by_path.items():
        if len(guids) > 1:
            where = sorted({pn for g in guids for pn, _ in by_guid[g]})
            x03.append(f"{path}（{' と '.join(where)}）")
    if x01:
        out.append(Finding("X01", RED, f"同じ ID で中身が違うファイルが {len(x01)} 個あります",
                           ["購入者が複数インポートすると、後から入れた方で上書きされます。対応アバター別パッケージで版がずれていないか確認してください。"],
                           x01, len(x01)))
    # UNVERIFIED: how Unity actually imports X02 / X03 collisions was not tried (no Unity here).
    if x02:
        out.append(Finding("X02", YELLOW, f"同じ ID でインポート先が違うファイルが {len(x02)} 個あります",
                           ["後から入れた方の場所に移動される可能性があります（Unity の実際の動作は未検証）。"], x02, len(x02)))
    if x03:
        out.append(Finding("X03", YELLOW, f"同じインポート先で ID が違うファイルが {len(x03)} 個あります",
                           ["別のアセットとして、別の名前で入る可能性があります（Unity の実際の動作は未検証）。"], x03, len(x03)))
    sets = {p.name: {e.guid for e in p.files() if matches[p.name][e.guid] is None} for p in packages}
    if not any(sets.values()):
        return  # only known assets (e.g. lilToon itself): nothing of the seller's own to compare
    common = set.intersection(*sets.values())
    only = []
    for pn, s in sets.items():
        others = set().union(*(v for k, v in sets.items() if k != pn))
        only.append(f"{pn} だけにあるもの: {len(s - others)} 個")
    out.append(Finding("X04", GREEN, f"全パッケージに共通のアセット: {len(common)} 個",
                       ["対応アバター別パッケージの差分の目安です（lilToon などの既知アセットとフォルダは数えていません）。"],
                       only, len(common)))


def _zip_findings(z: ZipRecord, opts: Options, out: list[Finding]) -> None:
    n = z.name
    if z.broken:
        out.append(Finding("Z01", RED, f"{n} を zip として読めません", ["zip を作り直してください。"], z.broken, len(z.broken), n))
    if not z.packages and not z.broken:
        out.append(Finding("Z02", YELLOW, f"{n} に unitypackage が 1 つもありません", ["入れ忘れでないか確認してください。"], [], 0, n))
    if not z.broken:
        if not any(is_readme(f.name) for f in z.files):
            out.append(Finding("Z03", YELLOW, f"{n} に説明書らしいファイルがありません",
                               ["名前に readme・説明・はじめに・導入 などを含む txt / md / pdf / html / url が見つかりませんでした。"
                                "説明書が無いと購入者の導入トラブルが増えます。"], [], 0, n))
        if not any(is_terms(f.name) for f in z.files):
            out.append(Finding("Z04", YELLOW, f"{n} に利用規約らしいファイルがありません",
                               ["規約を同梱するか、商品ページに書いているか確認してください（VN3 ライセンスなどのテンプレートがあります）。"],
                               [], 0, n))
    names = z.sjis_names + z.garbled_names
    if names:
        out.append(Finding("Z05", YELLOW, f"{n} に日本語のファイル名が Shift_JIS で保存されています（{len(names)} 個）",
                           ["海外の Windows や Mac で文字化けすることがあります。英数字の名前にするか、UTF-8 で圧縮し直してください。"],
                           names, len(names), n))
    if z.unreadable:
        out.append(Finding("Z06", YELLOW, f"{n} に読めないファイルがあります（{len(z.unreadable)} 個）",
                           ["パスワード付きか、対応していない圧縮方式（Deflate64 など）のため、検品していません。"
                            "中身を調べるには、パスワードなし・通常の圧縮で zip を作り直してください。"], z.unreadable, len(z.unreadable), n))
    if z.budget_exceeded:
        out.append(Finding("Z07", YELLOW, f"{n} は読み取り量の上限を超えたため、途中までしか調べていません",
                           ["--max-read-mb で上限を上げると最後まで調べられます。"], [], 0, n))
    exe = [f.name for f in z.files if ext_of(f.name) in EXE_EXTS]
    if exe:
        sev = YELLOW if opts.allow_exe else RED
        out.append(Finding("Z08", sev, f"{n} に実行ファイルが {len(exe)} 個入っています",
                           ["衣装・アバターの zip には通常入りません。意図したものでなければ外してください。"
                            "ツール商品で意図どおりなら --allow-exe で黄に下げられます。"], exe, len(exe), n))
    junk = [f.name for f in z.files if is_junk(f.name)]
    if junk:
        out.append(Finding("Z09", GREEN, f"{n} に不要なファイルが {len(junk)} 個あります",
                           ["Mac や Windows が自動で作るファイルやバックアップです。消してかまいません。"], junk, len(junk), n))
    listing = [f"{m.name}（{human_size(m.size)}）" for m in z.packages + z.files]
    out.append(Finding("Z10", GREEN, f"{n}: {zip_counts(z)}", ["説明書の下書きの「同梱物」に載せます。"], listing, len(listing), n))


def analyze(inputs: list[InputRecord], known: KnownAssets, opts: Options | None = None) -> Analysis:
    opts = opts or Options()
    packages = [p for r in inputs for p in r.packages]
    refs = cl.classify(packages, known)
    matches = {p.name: {e.guid: known.identify(e.guid, e.pathname) for e in p.files()} for p in packages}
    findings: list[Finding] = []
    for p, pr in zip(packages, refs):
        _package_findings(p, pr, matches[p.name], known, opts, findings)

    referenced: Counter[str] = Counter()
    dll: list[cl.ExtRef] = []
    for pr in refs:
        for x in pr.external.values():
            if x.category == cl.KNOWN and x.known_id:
                referenced[x.known_id] += x.count
            elif x.category == cl.DLL:
                dll.append(x)
    bundled = {m.id for pm in matches.values() for m in pm.values() if m is not None}
    required = [i for i in ORDER if i in referenced or i in bundled]
    if required:
        ex = []
        for i in required:
            note = []
            if i in bundled:
                note.append("同梱しています")
            if referenced[i]:
                note.append(f"参照 {referenced[i]} か所")
            ex.append(f"{known.name(i)}（{'、'.join(note)}）")
        findings.append(Finding("P19", GREEN, "購入者に必要なもの: " + ", ".join(known.name(i) for i in required),
                                ["説明書の下書きの「導入に必要なもの」に載せます。"], ex, len(required)))
    if dll:
        total = sum(x.count for x in dll)
        findings.append(Finding("P20", GREEN, f"辞書に無い DLL の部品を使っています（{len(dll)} 種類、{total} か所）",
                                ["購入者に別途導入してもらうツールがあれば、説明書に書いてください"
                                 "（VRChat SDK のワールド向けの部品など、よく使われるものの場合もあります）。"],
                                [f"{x.guid}（参照元: {_referrers(x, opts.max_referrers)}）" for x in dll], len(dll)))

    if len(packages) >= 2:
        _cross(packages, matches, findings)
    for r in inputs:
        if r.zip is not None:
            _zip_findings(r.zip, opts, findings)

    common = sorted({pn for pr in refs for x in pr.external.values() if x.category == cl.OTHER_PACKAGE for pn in x.packages})
    summaries = {p.name: summarize(p) for p in packages}
    return Analysis(sort_findings(findings), refs, matches, summaries, required, bundled, common)
