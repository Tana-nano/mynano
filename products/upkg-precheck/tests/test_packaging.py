"""The Windows build must bundle the dictionary (a frozen exe without it exits with code 2)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_pyinstaller_args_bundle_the_dictionary():
    args = (ROOT / "pyinstaller.args").read_text(encoding="utf-8").split()
    i = args.index("--add-data")
    src, dest = args[i + 1].split(";")
    assert (ROOT / src).is_file()
    assert dest == "upkg_precheck/data"


def test_smoke_args_run_the_dictionary_load():
    # --version prints the dictionary date, so the smoke run fails if the JSON is missing.
    assert (ROOT / "smoke.args").read_text(encoding="utf-8").split() == ["--version"]
