import os
import time

from ud_helpers import FIXTURES, bundled_rules, write_log
from upload_doctor import editorlog

PROJ = "C:/Users/FixtureUser/VRC/FixtureAvatar"


def parse(path, project=PROJ, **kw):
    from pathlib import Path

    return editorlog.parse(path, bundled_rules(), Path(project) if project else None, **kw)


def test_missing_log(tmp_path):
    f = parse(tmp_path / "nope.log")
    assert not f.found and not f.unreadable


def test_directory_is_unreadable(tmp_path):
    f = parse(tmp_path)
    assert f.found and f.unreadable


def test_compile_fixture():
    f = parse(FIXTURES / "editor_log_compile_error.txt")
    assert f.project_match == "match"
    a, s, o = f.compile["assets"], f.compile["sdk"], f.compile["other"]
    assert (a.unique, a.total) == (3, 6)
    assert (s.unique, s.total) == (1, 1)
    assert (o.unique, o.total) == (1, 1)
    assert f.packagecache and not f.other_packages
    assert a.samples[0].startswith("Assets/FixtureShop/Scripts/FixtureBone.cs(10,5) error CS0246:")
    assert f.missing_types == ["DynamicBone", "DynamicBoneCollider", "nadena.dev.modular_avatar", "Cinemachine"]
    assert f.unclassified == {"DllNotFoundException": [1, f.unclassified["DllNotFoundException"][1]]}
    assert not f.rule_hits


def test_upload_fixture():
    f = parse(FIXTURES / "editor_log_upload_failed.txt", project="C:\\Users\\FixtureUser\\VRC\\Fixture Avatar\\")
    assert f.project_match == "match"  # quoted value on the next line, separators and trailing slash normalized
    assert {k: v.count for k, v in f.rule_hits.items()} == {
        "upload.blueprint_not_owned": 1,
        "upload.build_failed": 1,
        "upload.validation_failed": 1,
        "upload.contentinfo_nre": 1,
    }
    assert f.compile_unique == 0


def test_clean_fixture():
    f = parse(FIXTURES / "editor_log_clean.txt")
    assert f.compile_unique == 0 and not f.rule_hits and not f.unclassified and not f.missing_types


def test_project_match_variants(tmp_path):
    assert parse(write_log(tmp_path / "a.log", "x", project="c:\\users\\fixtureuser\\vrc\\fixtureavatar")).project_match == "match"
    assert parse(write_log(tmp_path / "b.log", "x", project="C:/Other/Proj")).project_match == "mismatch"
    assert parse(write_log(tmp_path / "c.log", "x")).project_match == "unknown"
    p = tmp_path / "d.log"
    p.write_text(f'Unity.exe -projectPath "{PROJ}" -useHub\n', encoding="utf-8")
    assert parse(p).project_match == "match"
    p = tmp_path / "e.log"
    p.write_text("-projectpath\n\n" + PROJ + "\n", encoding="utf-8")
    assert parse(p).project_match == "match"
    p = tmp_path / "f.log"
    p.write_text("x\n" * 200 + f"-projectpath {PROJ}\n", encoding="utf-8")
    assert parse(p).project_match == "unknown"  # only the first 200 lines are looked at
    assert parse(write_log(tmp_path / "g.log", "x", project=PROJ), project=None).project_match == "unknown"


def test_dedupe_and_distinct_lines(tmp_path):
    e = "Assets/A.cs({}): error CS0103: The name 'x' does not exist"
    f = parse(write_log(tmp_path / "l.log", [e.format("1,1")] * 4 + [e.format("2,1")]))
    assert (f.compile["assets"].unique, f.compile["assets"].total) == (2, 5)


def test_origin_classification():
    o = editorlog.origin_of
    assert o("Assets/VRCSDK/SDK3/X.cs") == "sdk"
    assert o("Packages/com.vrchat.base/Runtime/X.cs") == "sdk"
    assert o("Assets/Foo/X.cs") == "assets"
    assert o(r"Assets\Foo\X.cs") == "assets"
    assert o("Packages/nadena.dev.modular-avatar/X.cs") == "other"
    assert o("Library/PackageCache/com.unity.x@1.0.0/X.cs") == "other"


def test_other_packages_flag(tmp_path):
    f = parse(write_log(tmp_path / "l.log", ["Packages/com.foo/Runtime/X.cs(1,1): error CS0103: nope"]))
    assert f.other_packages and not f.packagecache


def test_missing_name_extraction():
    assert editorlog.missing_name("CS0246", "The type or namespace name 'DynamicBone' could not be found") == "DynamicBone"
    assert editorlog.missing_name("CS0234", "The type or namespace name 'SDK3' does not exist in the namespace 'VRC'") == "VRC.SDK3"
    assert editorlog.missing_name("CS0246", "no quotes") is None


def test_missing_types_capped_and_unique(tmp_path):
    lines = [f"Assets/A.cs({i},1): error CS0246: The type or namespace name 'T{i % 25}' could not be found" for i in range(60)]
    lines.append("Assets/B.cs(1,1): error CS0246: The type or namespace name 't0' could not be found")
    f = parse(write_log(tmp_path / "l.log", lines))
    assert len(f.missing_types) == 20 and f.missing_types[0] == "T0" and len({x.casefold() for x in f.missing_types}) == 20


def test_near_rule_window(tmp_path):
    def run(gap):
        body = ["NullReferenceException: boom"] + ["  at X.Y ()"] * (gap - 1) + ["  at A.CreateContentInfoGUI ()"]
        return parse(write_log(tmp_path / f"n{gap}.log", body)).rule_hits.get("upload.contentinfo_nre")

    assert run(5).count == 1
    assert run(6) is None
    # near pattern after the main one also counts
    f = parse(write_log(tmp_path / "rev.log", ["  at A.CreateContentInfoGUI ()", "x", "NullReferenceException"]))
    assert f.rule_hits["upload.contentinfo_nre"].count == 1


def test_crlf_and_bad_bytes(tmp_path):
    p = tmp_path / "l.log"
    p.write_bytes(b"Assets/A.cs(1,2): error CS0246: The type or namespace name 'Q' could not be found\r\n\xff\xfe junk \r\n")
    f = parse(p)
    assert f.compile["assets"].unique == 1 and f.missing_types == ["Q"] and f.lines == 2


def test_unclassified_skips_stack_frames_and_counts_bare_cs(tmp_path):
    f = parse(
        write_log(
            tmp_path / "l.log",
            [
                "IOException: disk",
                "  at Foo.Bar () IOException",
                "IOException: again",
                "C:/Elsewhere/X.cs(1,1): error CS0246: The type 'Q' could not be found",
                "[Error] something failed",
            ],
        )
    )
    assert f.unclassified["IOException"][0] == 2
    assert f.unclassified["error CS0246"][0] == 1
    assert len(f.unclassified) == 2


def test_truncated_reads_tail_only(tmp_path):
    p = tmp_path / "big.log"
    head = f"-projectpath {PROJ}\n" + "Assets/Early.cs(1,1): error CS0103: early\n"
    tail = "filler line\n" * 50 + "Assets/Late.cs(1,1): error CS0103: late\n"
    p.write_text(head + tail, encoding="utf-8")
    f = parse(p, limit_bytes=len(tail.encode()) + 5)
    assert f.truncated and f.project_match == "unknown"
    assert [s.split("(")[0] for s in f.compile["assets"].samples] == ["Assets/Late.cs"]


def test_empty_log_and_mtime(tmp_path):
    p = tmp_path / "e.log"
    p.write_text("", encoding="utf-8")
    old = time.time() - 3 * 86400
    os.utime(p, (old, old))
    f = parse(p)
    assert f.found and f.lines == 0 and f.mtime is not None and f.project_match == "unknown"
