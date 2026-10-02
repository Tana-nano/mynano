import sys, time
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "src"))
from datetime import datetime
from pathlib import Path
from upkg_precheck import known
from upkg_precheck.app import App
from upkg_precheck.archive import Limits
from upkg_precheck.checks import Options
from upkg_precheck.pipeline import Settings
root = Path(sys.argv[1])
a = App(known.load(), Settings(Limits(), Options()), root, "ドキュメント\\UpkgPrecheck", datetime.now,
        lambda s: print("say:", s, file=sys.stderr, flush=True), lambda p: print("open:", p, file=sys.stderr, flush=True))
print(a.start(), flush=True)
sys.stdin.read()
a.stop()
