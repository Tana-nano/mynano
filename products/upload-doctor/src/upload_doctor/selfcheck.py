"""--self-check: prove the bundled rules load and a full diagnosis runs (used by the Windows CI smoke run).

Writes only to a temporary folder that is removed afterwards.
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime
from pathlib import Path
from typing import TextIO

from . import checks, editorlog, project, rules as rules_mod
from .mask import Masker
from .report import render_report


def build_fake_project(root: Path, unity_version: str) -> Path:
    (root / "Assets").mkdir(parents=True)
    (root / "ProjectSettings").mkdir()
    (root / "ProjectSettings" / "ProjectVersion.txt").write_text(f"m_EditorVersion: {unity_version}\n", encoding="utf-8")
    for pid in ("com.vrchat.base", "com.vrchat.avatars"):
        d = root / "Packages" / pid
        d.mkdir(parents=True)
        (d / "package.json").write_text(json.dumps({"name": pid, "version": "3.10.1"}), encoding="utf-8")
    manifest = {
        "dependencies": {"com.vrchat.avatars": {"version": "3.10.1"}},
        "locked": {"com.vrchat.base": {"version": "3.10.1"}, "com.vrchat.avatars": {"version": "3.10.1"}},
    }
    (root / "Packages" / "vpm-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (root / "Packages" / "manifest.json").write_text("{}", encoding="utf-8")
    return root


def run(out: TextIO) -> int:
    rules = rules_mod.load()
    with tempfile.TemporaryDirectory(prefix="upload-doctor-") as tmp:
        root = build_fake_project(Path(tmp) / "proj", rules.recommended_unity)
        log = Path(tmp) / "Editor.log"
        log.write_text(f"-projectpath {root}\nStarting compilation\n", encoding="utf-8")
        pf = project.collect(root, rules)
        lf = editorlog.parse(log, rules, pf.root)
        findings = checks.judge(pf, lf, rules, datetime.now().date())
        render_report(findings, pf, lf, rules, Masker([str(root)]), datetime.now())
    bad = [f.id for f in findings if f.level in (checks.NG, checks.WARN) and not f.id.startswith("P_PATH_")]
    if bad or lf.project_match != "match":
        print(f"自己診断: 失敗（{', '.join(bad) or 'ログの対象プロジェクト判定'}）", file=out)
        return 2
    print(f"自己診断: OK（規則表 {rules.checked_on.isoformat()}、ログ規則 {len(rules.log_rules)} 件）", file=out)
    return 0
