import copy
import json
import re

import pytest

from ud_helpers import bundled_rules, rules_data
from upload_doctor import rules as rules_mod
from upload_doctor.rules import RulesError
from upload_doctor.versions import compare, parse_version, satisfies, unity_major_minor


def test_bundled_rules_are_valid_and_complete():
    r = bundled_rules()
    assert r.recommended_unity == "2022.3.22f1"
    assert r.origin == "同梱"
    for rule in (*r.folder_rules, *r.log_rules):
        assert rule.source and rule.advice
        assert rule.confidence in ("high", "mid", "low")
    for h in r.type_hints:
        assert h.source and h.confidence == "low"
    ids = [x.id for x in r.log_rules]
    assert ids == ["upload.build_failed", "upload.validation_failed", "upload.blueprint_not_owned", "upload.contentinfo_nre"]
    assert set(r.compile_error.groupindex) >= {"file", "line", "col", "code", "msg"}


def test_rules_file_swap(tmp_path):
    d = rules_data()
    d["unity"]["supported"] = ["2022.3.99f1"]
    p = tmp_path / "r.json"
    p.write_text(json.dumps(d), encoding="utf-8")
    r = rules_mod.load(p)
    assert r.recommended_unity == "2022.3.99f1"
    assert r.origin == str(p)


def _mutate(fn):
    d = copy.deepcopy(rules_data())
    fn(d)
    return d


@pytest.mark.parametrize(
    "mutate, where",
    [
        (lambda d: d.update(schema=2), "rules.schema"),
        (lambda d: d.update(checked_on="30/09/2026"), "rules.checked_on"),
        (lambda d: d["unity"].update(supported=[]), "unity.supported"),
        (lambda d: d["sdk"].update(min_avatars_for_new_upload="abc"), "sdk.min_avatars_for_new_upload"),
        (lambda d: d["log_rules"][1].update(level="error"), "log_rules[1].level"),
        (lambda d: d["log_rules"][0].update(regex="(unclosed"), "log_rules[0].regex"),
        (lambda d: d["log_rules"][0].pop("advice"), "log_rules[0].advice"),
        (lambda d: d["log_rules"][0].pop("source"), "log_rules[0].source"),
        (lambda d: d["log_rules"][3].update(near_lines=0), "log_rules[3].near_lines"),
        (lambda d: d["log_rules"].append(dict(d["log_rules"][0])), "log_rules.id"),
        (lambda d: d["folder_rules"][0].update(confidence="certain"), "folder_rules[0].confidence"),
        (lambda d: d["folder_rules"][0].update(under="Packages"), "folder_rules[0].under"),
        (lambda d: d["folder_rules"][0].update(max_depth=3), "folder_rules[0].max_depth"),
        (lambda d: d.update(compile_error_regex="(?P<file>x)"), "rules.compile_error_regex"),
        (lambda d: d["missing_type_hints"][0].update(match=[]), "missing_type_hints[0].match"),
        (lambda d: d.update(overrides={"P_X": {"title": "x"}}), "overrides.P_X"),
        (lambda d: d.update(overrides={"P_X": {"level": "fatal"}}), "overrides.P_X.level"),
    ],
)
def test_invalid_rules_name_the_place(mutate, where):
    with pytest.raises(RulesError) as e:
        rules_mod.parse(_mutate(mutate))
    assert where.split(".")[0].split("[")[0] in str(e.value)
    assert where.replace(".id", "") in str(e.value) or where in str(e.value)


def test_unreadable_and_broken_json(tmp_path):
    with pytest.raises(RulesError, match="読めません"):
        rules_mod.load(tmp_path / "missing.json")
    p = tmp_path / "bad.json"
    p.write_text("{", encoding="utf-8")
    with pytest.raises(RulesError, match="JSON"):
        rules_mod.load(p)


def test_type_hints_order_and_matching():
    r = bundled_rules()
    assert "VRCFury" in r.hint_for("VRCFury.Model").hint
    assert "VRChat SDK" in r.hint_for("VRC").hint
    assert "VRChat SDK" in r.hint_for("VRC.SDK3.Avatars").hint
    assert "Dynamic Bone" in r.hint_for("dynamicbonecollider").hint  # case-insensitive
    assert "Modular Avatar" in r.hint_for("nadena.dev.modular_avatar").hint
    assert r.hint_for("Foo.Bar") is None
    assert r.hint_for("VRCLens") is None


def test_versions():
    assert parse_version("3.1.4-beta.1") == (3, 1, 4)
    assert parse_version("x") is None
    assert compare((3, 9), (3, 9, 0)) == 0
    assert satisfies("3.1.4", "3.1.x") is True
    assert satisfies("3.2.0", "3.1.x") is False
    assert satisfies("3.1.4", "3.1.4") is True
    assert satisfies("3.1.5", "3.1.4") is False
    assert satisfies("3.2.0", ">=3.1.0") is True
    assert satisfies("3.0.9", ">= 3.1.0") is False
    assert satisfies("3.1.4", "^3.1.0") is None
    assert satisfies("3.1.4", ">=3.1.0 <4.0.0") is None
    assert satisfies(None, "3.1.x") is None
    assert unity_major_minor("2022.3.22f1") == "2022.3"
    assert unity_major_minor("6000.0.23f1") == "6000.0"


def test_compile_regex_shapes():
    rx = bundled_rules().compile_error
    m = rx.search("[Error] 21:40:12 Assets/My Folder (1)/Foo.cs(10,5): error CS0246: The type 'X' could not be found")
    assert m and m.group("file") == "Assets/My Folder (1)/Foo.cs" and m.group("code") == "CS0246"
    m = rx.search(r"Assets\Foo\Bar.cs(1,2): error CS1002: ; expected")
    assert m and m.group("file") == r"Assets\Foo\Bar.cs"
    assert rx.search("C:/Other/Foo.cs(1,2): error CS0246: x") is None
    assert rx.search("Assets/Foo.cs(1,2): warning CS0618: obsolete") is None
    assert re.search(rx, "Library/PackageCache/com.unity.ugui@1.0.0/Runtime/A.cs(5,1): error CS0101: dup")


def test_bundled_rules_fallback(monkeypatch):
    def broken(_pkg):
        raise ModuleNotFoundError("no resource reader")

    monkeypatch.setattr(rules_mod.resources, "files", broken)
    assert rules_mod.load().recommended_unity == "2022.3.22f1"
