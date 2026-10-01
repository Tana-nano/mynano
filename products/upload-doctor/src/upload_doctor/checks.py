"""Judge: facts in, findings out. Pure; no I/O."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from .editorlog import LogFacts
from .project import ProjectFacts
from .rules import Rules
from .versions import compare, parse_version, satisfies, unity_major_minor

OK, INFO, WARN, NG = "ok", "info", "warn", "ng"
STATUS_LABEL = {NG: "NG", WARN: "注意", INFO: "情報", OK: "OK"}
CONF_LABEL = {"high": "高", "mid": "中", "low": "低"}
_LEVEL_RANK = {NG: 0, WARN: 1, INFO: 2, OK: 3}
_CONF_RANK = {"high": 0, "mid": 1, "low": 2}

STALE_DAYS = 90
OLD_LOG_DAYS = 7
LONG_PATH = 120

LOW_NOTE = "公式以外の情報にもとづく、または前提を確かめられない推測です。断定はできません"
LOG_NOTE = "ログにある＝今も出ているとは限りません。Unity を開いてコンソールで再確認してください"
OTHER_PROJECT_NOTE = "別のプロジェクトのログのため、確からしさを「低」に下げています"
GONE_NOTE = "ログにあるファイルは、今はもうありません。直した後なら、Unity で開き直してから再実行してください"
GONE_MARK = "（このファイルは今はありません）"


@dataclass
class Finding:
    id: str
    level: str
    title: str
    confidence: str | None = None
    evidence: list[str] = field(default_factory=list)
    evidence_total: int | None = None
    advice: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    log_derived: bool = False
    low_explained: bool = False  # confidence was lowered for a stated reason; skip LOW_NOTE

    @property
    def total(self) -> int:
        return self.evidence_total if self.evidence_total is not None else len(self.evidence)

    @property
    def status(self) -> str:
        return STATUS_LABEL[self.level]


def sort_key(f: Finding) -> tuple:
    return (_LEVEL_RANK[f.level], _CONF_RANK.get(f.confidence or "", 3), -f.total, f.id)


def candidates(findings: list[Finding]) -> list[Finding]:
    return [f for f in findings if f.level != OK]


def exit_code(findings: list[Finding]) -> int:
    return 1 if any(f.level == NG for f in findings) else 0


def summary(findings: list[Finding]) -> str:
    ng = sum(f.level == NG for f in findings)
    warn = sum(f.level == WARN for f in findings)
    if not ng and not warn:
        return "結果: 問題は見つかりませんでした（NG・注意なし）"
    parts = [f"NG {ng} 件"] if ng else []
    if warn:
        parts.append(f"注意 {warn} 件")
    return "結果: " + "、".join(parts)


# --- project ------------------------------------------------------------------------


def _unity(pf: ProjectFacts, rules: Rules) -> list[Finding]:
    rec = rules.recommended_unity
    v = pf.unity_version
    if v is None:
        return [Finding("P_UNITY_UNREADABLE", INFO, "Unity のバージョンを確認できませんでした（ProjectSettings/ProjectVersion.txt）")]
    ev = [f"ProjectSettings/ProjectVersion.txt: m_EditorVersion: {v}"]
    if v in rules.unity_supported:
        return [Finding("P_UNITY_VERSION", OK, f"Unity のバージョンが推奨と一致（{v}）")]
    if unity_major_minor(v) == unity_major_minor(rec):
        return [
            Finding(
                "P_UNITY_VERSION", WARN, f"Unity のバージョンが推奨と少し違います（{v} / 推奨 {rec}）", "mid", ev,
                advice=[
                    f"推奨版（{rec}）の Unity で開き直してください（VCC からインストールできます）",
                    "Unity Hub がセキュリティ警告でアップグレードを勧めても、VRChat 用のプロジェクトでは無視してよい、と VRChat が案内しています",
                ],
            )
        ]
    return [
        Finding(
            "P_UNITY_VERSION", NG, f"Unity のバージョンが VRChat の推奨と違います（{v} / 推奨 {rec}）", "high", ev,
            advice=[
                f"推奨版（{rec}）の Unity で開き直してください（VCC からインストールできます）",
                "推奨版以外にアップグレードするとアップロードに失敗する、と VRChat が案内しています",
            ],
        )
    ]


def _vpm(pf: ProjectFacts) -> list[Finding]:
    out: list[Finding] = []
    if pf.upm_manifest_broken:
        out.append(
            Finding(
                "P_UPM_BROKEN", NG, "Unity のパッケージ設定（Packages/manifest.json）が壊れています", "mid",
                ["Packages/manifest.json: JSON として読めません"],
                advice=["この状態だと Unity がプロジェクトを開けません。バックアップから戻すか、VCC でプロジェクトを開き直してください"],
            )
        )
    if pf.vpm_manifest_broken:
        out.append(
            Finding(
                "P_VPM_BROKEN", NG, "VCC のパッケージ一覧（Packages/vpm-manifest.json）が壊れています", "mid",
                ["Packages/vpm-manifest.json: JSON として読めません"],
                advice=["VCC でプロジェクトを開き直すか、バックアップから戻してください"],
            )
        )
    elif not pf.vpm_manifest_present:
        if pf.vrchat_packages:
            out.append(Finding("P_VPM_NO_MANIFEST", INFO, "VCC の管理外のプロジェクトです（Packages/vpm-manifest.json がありません）"))
    else:
        missing = [(pid, ver) for pid, ver in sorted(pf.vpm_expected.items()) if pid not in pf.packages]
        if missing:
            level = NG if any(pid.startswith("com.vrchat.") for pid, _ in missing) else WARN
            out.append(
                Finding(
                    "P_VPM_MISSING_PACKAGE", level,
                    f"VCC のパッケージ一覧にあるのに、実体がないパッケージがあります（{len(missing)} 個）", "mid",
                    [f"{pid} {ver or ''}".rstrip() + "（Packages/ にありません）" for pid, ver in missing],
                    advice=["VCC でこのプロジェクトを開き直してください（足りないパッケージを入れ直す仕組みがあります）"],
                )
            )
        drift = []
        if pf.vpm_expected_from_locked:
            for pid, want in sorted(pf.vpm_expected.items()):
                pkg = pf.packages.get(pid)
                if pkg and want and pkg.version and pkg.version != want:
                    drift.append(f"{pid}: 一覧の記録 {want} / 実体 {pkg.version}")
        if drift:
            out.append(
                Finding(
                    "P_VPM_VERSION_DRIFT", WARN, f"VCC の記録と実際のパッケージのバージョンが違います（{len(drift)} 個）", "low", drift,
                    advice=["VCC でこのプロジェクトを開き直してください"],
                )
            )
        if pf.vpm_expected and not missing and not drift:
            out.append(Finding("P_VPM_OK", OK, f"VCC のパッケージ {len(pf.vpm_expected)} 個が一覧と一致"))

    unsatisfied, unknown = [], []
    for pkg in sorted(pf.packages.values(), key=lambda p: p.id):
        for dep, spec in sorted(pkg.vpm_deps.items()):
            have = pf.packages.get(dep)
            if have is None:
                unsatisfied.append(f"{pkg.id} は {dep} {spec} が必要ですが、入っていません")
                continue
            ok = satisfies(have.version, spec)
            if ok is False:
                unsatisfied.append(f"{pkg.id} は {dep} {spec} が必要ですが、{have.version} です")
            elif ok is None:
                unknown.append(f"{pkg.id} → {dep} {spec}（入っているのは {have.version or '?'}）")
    if unsatisfied:
        out.append(
            Finding(
                "P_VPM_DEP_UNSATISFIED", WARN, f"パッケージ同士のバージョンの条件が合っていません（{len(unsatisfied)} 件）", "mid",
                unsatisfied,
                advice=[
                    "VCC で、条件を出している側のパッケージを最新に更新してください（新しい版で条件が直っていることがあります）",
                    "足りないパッケージは VCC で追加してください",
                ],
            )
        )
    if unknown:
        out.append(
            Finding(
                "P_VPM_DEP_UNKNOWN", INFO, f"判定できない書き方のバージョン条件があります（{len(unknown)} 件）", evidence=unknown,
                advice=["このツールでは合っているか判定していません。気になる場合は VCC の画面で警告が出ていないか確認してください"],
            )
        )
    return out


def _sdk(pf: ProjectFacts, rules: Rules) -> list[Finding]:
    out: list[Finding] = []
    vrc = pf.vrchat_packages
    if not pf.assets_vrcsdk and not vrc and not pf.manifest_lists_vrchat:
        out.append(
            Finding(
                "P_NO_SDK", NG, "VRChat SDK が入っていません", "high",
                ["Assets/VRCSDK も Packages/com.vrchat.* もありません"],
                advice=["VCC（VRChat Creator Companion）でこのプロジェクトを開き、SDK（Avatars）を追加してください"],
            )
        )
    elif vrc or pf.assets_vrcsdk:
        names = ", ".join(f"{p} {pf.packages[p].version or '?'}" for p in vrc) or "Assets/VRCSDK"
        out.append(Finding("P_SDK_FOUND", OK, f"VRChat SDK が入っています（{names}）"))

    if pf.assets_vrcsdk and "com.vrchat.base" in pf.packages:
        out.append(
            Finding(
                "P_SDK_DUPLICATE", WARN, "旧方式の SDK（Assets/VRCSDK）と VCC 方式の SDK が二重に入っている可能性があります", "mid",
                ["Assets/VRCSDK", "Packages/com.vrchat.base"],
                advice=["プロジェクトをバックアップしてから、VCC 方式にそろえてください（VRChat は VCC を推奨しています）"],
            )
        )

    if pf.settings_state == "text":
        sdk3 = "com.vrchat.avatars" in pf.packages or "com.vrchat.worlds" in pf.packages
        if "VRC_SDK_VRCSDK2" in pf.settings_symbols and sdk3:
            out.append(
                Finding(
                    "P_DEFINE_SYMBOLS", WARN, "SDK2 の設定（VRC_SDK_VRCSDK2）が残っています", "mid",
                    ["ProjectSettings/ProjectSettings.asset: VRC_SDK_VRCSDK2"],
                    advice=[
                        "Unity の Project Settings → Player → Scripting Define Symbols から VRC_SDK_VRCSDK2 を消してください",
                        "VRChat の案内: そのプロジェクトの SDK に関係ないシンボルは消す",
                    ],
                )
            )
    elif pf.settings_state in ("binary", "unreadable"):
        out.append(Finding("P_SETTINGS_UNREADABLE", INFO, "ProjectSettings.asset を読めませんでした（テキスト形式ではないか、開けません）"))

    avatars = pf.packages.get("com.vrchat.avatars")
    have, need = parse_version(avatars.version if avatars else None), parse_version(rules.sdk_min_avatars)
    if have is not None and need is not None and compare(have, need) < 0:
        out.append(
            Finding(
                "P_SDK_OLD", WARN, f"VRChat SDK（Avatars）が古い可能性があります（{avatars.version} / 目安 {rules.sdk_min_avatars} 以上）",
                rules.sdk_confidence, [f"Packages/com.vrchat.avatars/package.json: version {avatars.version}"],
                advice=[
                    f"SDK {rules.sdk_min_avatars} 未満では新しいアバターを上げられない、という案内が解説記事にあります",
                    "プロジェクトをバックアップしてから、VCC で SDK を最新に更新してください",
                ],
            )
        )
    return out


def _folders_and_paths(pf: ProjectFacts, rules: Rules) -> list[Finding]:
    out: list[Finding] = []
    for r in rules.folder_rules:
        hits = pf.folder_hits.get(r.id)
        if hits:
            out.append(Finding(f"P_{r.id.upper()}", r.level, f"{r.title}（{hits[0]}）", r.confidence, list(hits), advice=list(r.advice)))
    if pf.scan_truncated:
        out.append(Finding("P_SCAN_TRUNCATED", INFO, f"Assets の走査を {pf.scan_limit:,} 件で打ち切りました（一部のフォルダは見ていません）"))
    if pf.non_ascii:
        ev = []
        if "project" in pf.non_ascii:
            ev.append("プロジェクトのフォルダ: <PROJECT>")
        if "userprofile" in pf.non_ascii:
            ev.append("Windows のユーザーフォルダ: %USERPROFILE%")
        out.append(
            Finding(
                "P_PATH_NON_ASCII", INFO, "フォルダのパスに日本語などの文字が含まれています", "low", ev,
                advice=[
                    "日本語のパスがエラーの原因になった例が解説記事にあります",
                    "英数字だけの名前のフォルダ（例: C:\\VRC\\MyAvatar）に移して開き直してください",
                ],
            )
        )
    if pf.path_length > LONG_PATH:
        out.append(
            Finding(
                "P_PATH_LONG", INFO, f"プロジェクトのパスが長めです（{pf.path_length} 文字）", "low",
                advice=["パスが長いと Windows のパス長の上限に当たり、パッケージのファイルが読めなくなる例があります（Unity フォーラムの報告）。短いパスに移すと避けられます"],
            )
        )
    if pf.unity_open:
        out.append(
            Finding(
                "P_UNITY_OPEN", INFO, "Unity でこのプロジェクトを開いている最中のようです", "low",
                ["Temp/UnityLockfile があります"],
                advice=["Editor.log は書き込みの途中かもしれません。エラーを直した後なら、Unity を終了してから再実行すると確実です"],
            )
        )
    return out


# --- log ----------------------------------------------------------------------------


def _mark_gone(f: Finding, files: list[str], root: Path | None) -> Finding:
    """Annotate compile errors whose file no longer exists; if none exist, the log predates a fix."""
    if root is None or not files:
        return f
    gone = [x for x in files if not (root / x.replace("\\", "/")).exists()]
    if not gone:
        return f
    f.evidence = [e + GONE_MARK if any(e.startswith(x + "(") for x in gone) else e for e in f.evidence]
    if len(gone) == len(files):
        f.confidence = "low"
        f.low_explained = True
        f.notes.append(GONE_NOTE)
    return f


def _log(lf: LogFacts, rules: Rules, today: date, root: Path | None = None) -> list[Finding]:
    if not lf.found:
        return [
            Finding(
                "L_NOT_FOUND", INFO, "Editor.log が見つかりませんでした", evidence=[str(lf.path)],
                advice=["Unity でこのプロジェクトを一度開いてから再実行するか、--editor-log で場所を指定してください"],
            )
        ]
    if lf.unreadable:
        return [Finding("L_UNREADABLE", INFO, "Editor.log を開けませんでした", evidence=[str(lf.path)], advice=["Unity を終了してから再実行してください"])]

    out: list[Finding] = []
    if lf.project_match == "mismatch":
        out.append(
            Finding(
                "L_OTHER_PROJECT", WARN, "この Editor.log は別のプロジェクトのものです", "high",
                advice=["このプロジェクトを Unity で開いてから再実行してください", "ログ由来の候補は確からしさを「低」に下げています"],
            )
        )
    if lf.mtime is not None:
        age = (today - lf.mtime.date()).days
        if age > OLD_LOG_DAYS:
            out.append(
                Finding("L_OLD_LOG", INFO, f"この Editor.log は {age} 日前のものです", advice=["このプロジェクトを Unity で開き直してから再実行してください"])
            )
    if lf.truncated:
        out.append(Finding("L_TRUNCATED", INFO, "Editor.log が大きいため、末尾の 50 MB だけを読みました"))

    def counts(cat: str) -> str:
        g = lf.compile[cat]
        return f"{g.unique} 件、延べ {g.total} 回"

    g = lf.compile["assets"]
    if g.unique:
        out.append(
            _mark_gone(
                Finding(
                    "L_COMPILE_ASSETS", NG, f"Assets 内のスクリプトがコンパイルエラーです（{counts('assets')}。SDK パネルが出ない原因になります）",
                    "high", list(g.samples), g.unique,
                    advice=[
                        "エラーの出ているファイルがどのアセット（商品）のものか確かめ、導入手順の抜け（必要なパッケージ）を確認してください",
                        "不要なアセットなら削除してください（先にバックアップ）",
                    ],
                    log_derived=True,
                ),
                g.files,
                root,
            )
        )
    g = lf.compile["sdk"]
    if g.unique:
        out.append(
            _mark_gone(
                Finding(
                    "L_COMPILE_SDK", NG, f"VRChat SDK のスクリプトがコンパイルエラーです（{counts('sdk')}）", "mid", list(g.samples), g.unique,
                    advice=[
                        "SDK の一部が欠けているか、必要なパッケージのバージョンが合っていません",
                        "プロジェクトをバックアップしてから、VCC で SDK を入れ直す・更新してください",
                    ],
                    log_derived=True,
                ),
                g.files,
                root,
            )
        )
    g = lf.compile["other"]
    if g.unique:
        advice = []
        if lf.other_packages:
            advice.append("Packages/ のパッケージは、そのパッケージの導入手順を確認してください")
        if lf.packagecache:
            advice.append(
                "Library/PackageCache のエラーは Unity 側のパッケージの不整合です。Unity を閉じて Library フォルダを削除してから開き直すか、Package Manager でリセットする対処が Unity フォーラムで案内されています"
            )
        out.append(
            _mark_gone(
                Finding(
                    "L_COMPILE_OTHER", WARN, f"パッケージのスクリプトがコンパイルエラーです（{counts('other')}）", "mid", list(g.samples), g.unique,
                    advice=advice, log_derived=True,
                ),
                g.files,
                root,
            )
        )
    if lf.missing_types:
        ev = []
        for name in lf.missing_types:
            h = rules.hint_for(name)
            ev.append(f"'{name}' → {h.hint}（確からしさ:低）" if h else f"'{name}'")
        out.append(
            Finding(
                "L_MISSING_TYPE", WARN, f"足りない型・名前空間があります（{len(lf.missing_types)} 個）", "mid", ev,
                advice=["その名前を提供するパッケージやアセットを入れてください。どれかは、使っている商品の導入手順に従ってください"],
                log_derived=True,
            )
        )
    for r in rules.log_rules:
        h = lf.rule_hits.get(r.id)
        if h and h.count:
            out.append(
                Finding(
                    f"L_UPLOAD_MSGS/{r.id}", r.level, f"{r.title}（{h.count} 回）", r.confidence, list(h.samples), h.count,
                    advice=list(r.advice), log_derived=True,
                )
            )
    if lf.unclassified:
        ev = [f"{kind}: {cnt} 回（最初の行: {first}）" for kind, (cnt, first) in sorted(lf.unclassified.items(), key=lambda kv: (-kv[1][0], kv[0]))]
        out.append(
            Finding(
                "L_UNCLASSIFIED", INFO, f"分類できないエラー・例外が {len(lf.unclassified)} 種類あります", evidence=ev,
                advice=["このレポートを貼って、詳しい人や商品の作者に相談してください"], log_derived=True,
            )
        )
    if not lf.compile_unique:
        out.append(Finding("L_NO_COMPILE_ERRORS", OK, "Editor.log にコンパイルエラーの記録なし"))
    return out


# --- entry --------------------------------------------------------------------------


def judge(pf: ProjectFacts, lf: LogFacts | None, rules: Rules, today: date) -> list[Finding]:
    findings: list[Finding] = []
    findings += _unity(pf, rules)
    findings += _vpm(pf)
    findings += _sdk(pf, rules)
    findings += _folders_and_paths(pf, rules)
    if lf is not None:
        findings += _log(lf, rules, today, pf.root)
    if today - rules.checked_on > timedelta(days=STALE_DAYS):
        findings.append(
            Finding(
                "R_STALE", INFO, f"規則表は {rules.checked_on.isoformat()} 時点です。古い可能性があります",
                advice=["配布ページで新しい版が出ていないか確認してください"],
            )
        )

    other_project = lf is not None and lf.project_match == "mismatch"
    for f in findings:
        ov = rules.overrides.get(f.id) or rules.overrides.get(f.id.split("/")[0])
        if ov:
            f.level = ov.get("level", f.level)
            f.confidence = ov.get("confidence", f.confidence)
        if f.level == OK:
            continue
        downgraded = other_project and f.id.startswith("L_") and f.id != "L_OTHER_PROJECT" and bool(f.confidence)
        if downgraded:
            f.confidence = "low"
            f.notes.append(OTHER_PROJECT_NOTE)
        if f.log_derived:
            f.notes.append(LOG_NOTE)
        if f.confidence == "low" and not downgraded and not f.low_explained:
            f.notes.append(LOW_NOTE)
    return sorted(findings, key=sort_key)
