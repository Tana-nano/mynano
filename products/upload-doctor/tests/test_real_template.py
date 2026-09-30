"""VRChat's official avatar template project (github.com/vrchat-community/template-avatar):
real vpm-manifest.json and ProjectVersion.txt, copied into shared/fixtures/unity/template-avatar/."""

import json
import shutil

from ud_helpers import FIXTURES, TODAY, bundled_rules, ids
from upload_doctor import checks, project

TPL = FIXTURES / "template-avatar"


def make_template(root, resolved: bool):
    (root / "Assets").mkdir(parents=True)
    (root / "ProjectSettings").mkdir()
    (root / "Packages").mkdir()
    shutil.copy(TPL / "ProjectVersion.txt", root / "ProjectSettings" / "ProjectVersion.txt")
    shutil.copy(TPL / "vpm-manifest.json", root / "Packages" / "vpm-manifest.json")
    if resolved:  # what VCC leaves after resolving
        for pid in ("com.vrchat.base", "com.vrchat.avatars"):
            (root / "Packages" / pid).mkdir()
            (root / "Packages" / pid / "package.json").write_text(json.dumps({"name": pid, "version": "3.10.1"}))
    return root


def test_real_files_are_read(tmp_path):
    f = project.collect(make_template(tmp_path / "t", True), bundled_rules(), {})
    assert f.unity_version == "2022.3.22f1"
    assert f.vpm_expected == {"com.vrchat.base": "3.x.x", "com.vrchat.avatars": "3.x.x"}
    assert not f.vpm_expected_from_locked


def test_fresh_clone_before_vcc_resolve(tmp_path):
    fs = ids(checks.judge(project.collect(make_template(tmp_path / "t", False), bundled_rules(), {}), None, bundled_rules(), TODAY))
    assert fs["P_UNITY_VERSION"].level == "ok"
    miss = fs["P_VPM_MISSING_PACKAGE"]
    assert miss.level == "ng" and "VCC" in miss.advice[0]
    assert "P_NO_SDK" not in fs  # the manifest names the SDK, so this is "not resolved yet", not "no SDK"


def test_resolved_template_is_healthy(tmp_path):
    fs = checks.judge(project.collect(make_template(tmp_path / "t", True), bundled_rules(), {}), None, bundled_rules(), TODAY)
    assert checks.candidates(fs) == []
