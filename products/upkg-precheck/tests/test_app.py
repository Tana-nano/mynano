"""A01-A10: the drop screen (local web server the browser uploads dropped files to)."""

import http.client
import io
import json
import urllib.error
import urllib.request
from urllib.parse import urlsplit

import pytest

from up_builders import make_zip, simple_package
from upkg_precheck import known
from upkg_precheck.app import App
from upkg_precheck.archive import Limits
from upkg_precheck.checks import Options
from upkg_precheck.cli import Env, main
from upkg_precheck.pipeline import Settings
from test_cli import NOW, good_zip

PKG = simple_package()
ZIP = make_zip({"Karin.unitypackage": PKG, "README.txt": b"x", "利用規約.txt": b"x"})


@pytest.fixture
def app(tmp_path):
    said, opened = [], []
    a = App(known.load(), Settings(Limits(), Options()), tmp_path / "docs" / "UpkgPrecheck",
            "ドキュメント\\UpkgPrecheck", lambda: NOW, said.append, opened.append)
    a.start()
    a.said, a.opened = said, opened
    yield a
    a.stop()


def req(app, method, path, body=None, *, headers=None, raw=False):
    h = {"X-Upkg": "1", **(headers or {})}
    if body is not None and not isinstance(body, bytes):
        body, h["Content-Type"] = json.dumps(body).encode(), "application/json"
    r = urllib.request.Request(app.url(path), data=body, method=method, headers=h)
    try:
        with urllib.request.urlopen(r) as resp:
            data = resp.read()
            return resp.status, (data.decode() if raw else json.loads(data or b"{}"))
    except urllib.error.HTTPError as e:
        data = e.read()
        try:
            return e.code, json.loads(data)
        except ValueError:
            return e.code, data.decode()


def check(app, roots, uploads):
    """roots like the page sends; uploads: {(i, j): bytes}. Returns (status, json)."""
    _, j = req(app, "POST", "/jobs")
    for (i, k), data in uploads.items():
        assert req(app, "PUT", f"/jobs/{j['job']}/{i}/{k}", data)[0] == 200
    return req(app, "POST", f"/jobs/{j['job']}/run", {"roots": roots})


def page(app, path):
    status, text = req(app, "GET", path, raw=True)
    assert status == 200
    return text


def test_a01_home_page_needs_the_token(app):
    home = page(app, "/")
    assert "ここにドロップ" in home and f'data-base="{app.base}"' in home and "<script>" in home
    port = app.port
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{app.base}") as r:  # no slash: redirected
        assert r.status == 200
    for path in ("/", "/" + "0" * 32 + "/", "/favicon.ico"):
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(f"http://127.0.0.1:{port}{path}")
        assert e.value.code == 404


def test_a02_foreign_host_is_refused(app):
    c = http.client.HTTPConnection("127.0.0.1", app.port)
    c.request("GET", app.base + "/", headers={"Host": f"evil.example:{app.port}"})
    assert c.getresponse().status == 403


def test_a03_writes_need_the_page_header_and_origin(app):
    assert req(app, "POST", "/jobs", headers={"X-Upkg": "0"})[0] == 403
    assert req(app, "POST", "/jobs", headers={"Origin": "https://evil.example"})[0] == 403
    assert req(app, "POST", "/jobs", headers={"Origin": f"http://127.0.0.1:{app.port}"})[0] == 200


def test_a04_dropped_zip_is_checked_saved_and_shown(app, tmp_path):
    status, res = check(app, [{"name": "Outfit_v1.0.zip", "dir": False,
                              "files": [{"rel": "Outfit_v1.0.zip", "size": len(ZIP)}]}], {(0, 0): ZIP})
    assert status == 200 and res["url"].startswith(app.base + "/results/")
    html = page(app, res["url"][len(app.base):])
    assert "Outfit_v1.0.zip" in html and 'class="verdict' in html and 'id="drop"' in html
    assert "ドキュメント\\UpkgPrecheck\\Outfit_v1.0-20260930-221530" in html and str(tmp_path) not in html
    saved = tmp_path / "docs" / "UpkgPrecheck" / "Outfit_v1.0-20260930-221530"
    assert {p.name for p in saved.iterdir()} == {"report.txt", "report.html", "readme-draft.md"}
    assert "調べています: Outfit_v1.0.zip" in app.said and any(s.startswith("結果: ") for s in app.said)
    assert list(app.tmp.iterdir()) == []  # uploads are gone once checked


def test_a05_folder_names_match_the_command_line(app):
    roots = [{"name": "Shop", "dir": True, "files": [
        {"rel": "b/Karin.unitypackage", "size": len(PKG)},
        {"rel": "a/Karin.unitypackage", "size": len(PKG)},
    ]}, {"name": "Empty", "dir": True, "files": []}]
    status, res = check(app, roots, {(0, 0): PKG, (0, 1): PKG})
    assert status == 200
    looked = [s for s in app.said if s.startswith("調べています: ")]
    assert looked == ["調べています: a\\Karin.unitypackage", "調べています: b\\Karin.unitypackage"]
    assert "Empty: zip も unitypackage も見つかりませんでした" in app.said
    assert any(p.name.startswith("Shop-") for p in app.root.iterdir())


def test_a06_unusable_requests_are_explained(app):
    one = [{"name": "A.zip", "dir": False, "files": [{"rel": "A.zip", "size": len(ZIP)}]}]
    status, res = check(app, one, {})
    assert status == 400 and "届いていません" in res["error"]
    status, res = check(app, one, {(0, 0): ZIP[:-5]})
    assert status == 400 and "途中までしか" in res["error"]
    bad = [{"name": "S", "dir": True, "files": [{"rel": "../x.zip", "size": 1}]}]
    assert check(app, bad, {})[0] == 400
    status, res = check(app, [{"name": "memo.txt", "dir": False, "files": [{"rel": "memo.txt", "size": 1}]}], {})
    assert status == 422 and "対応していない形式" in res["error"] and "調べられるファイルがありませんでした" in res["error"]
    assert req(app, "POST", "/jobs/" + "0" * 16 + "/run", {"roots": one})[0] == 404
    assert req(app, "PUT", "/jobs/x/0/0", b"abc")[0] == 404


def test_a07_open_folder_button(app, tmp_path):
    status, res = check(app, [{"name": "A.zip", "dir": False, "files": [{"rel": "A.zip", "size": len(ZIP)}]}],
                        {(0, 0): ZIP})
    rid = res["url"].rsplit("/", 1)[1]
    assert req(app, "POST", f"/results/{rid}/open")[0] == 200
    assert app.opened == [tmp_path / "docs" / "UpkgPrecheck" / "A-20260930-221530"]
    assert req(app, "POST", "/results/nothing/open")[0] == 404


def test_a08_stop_closes_the_server_and_removes_uploads(tmp_path):
    a = App(known.load(), Settings(Limits(), Options()), tmp_path, "x", lambda: NOW, lambda s: None, lambda p: None)
    url = a.start()
    tmp = a.tmp
    _, j = req(a, "POST", "/jobs")
    req(a, "PUT", f"/jobs/{j['job']}/0/0", b"half")
    a.stop()
    assert not tmp.exists()
    with pytest.raises(OSError):
        urllib.request.urlopen(url, timeout=2)


def test_a09_double_click_then_drop_in_the_browser(tmp_path):
    out, urls, checked = io.StringIO(), [], []

    def use_page(prompt):
        # While the console waits for Enter, the page sends a zip.
        base = urlsplit(urls[0])
        a = type("A", (), {"url": lambda self, p: f"{base.scheme}://{base.netloc}{base.path.rstrip('/')}{p}"})()
        checked.append(check(a, [{"name": "A.zip", "dir": False, "files": [{"rel": "A.zip", "size": len(ZIP)}]}],
                             {(0, 0): ZIP}))
        return ""

    env = Env(out=out, now=lambda: NOW, input=use_page, isatty=lambda: True,
              environ={"UPKG_PRECHECK_DOCS": str(tmp_path)}, open_url=urls.append, open_file=lambda p: None)
    assert main([], env) == 0
    assert checked[0][0] == 200 and "調べています: A.zip" in out.getvalue()
    assert (tmp_path / "UpkgPrecheck" / "A-20260930-221530" / "report.html").is_file()
    with pytest.raises(OSError):  # Enter closed the screen
        urllib.request.urlopen(urls[0], timeout=2)


def test_a10_drag_onto_icon_then_drop_more(tmp_path):
    z = good_zip(tmp_path)
    out, urls = io.StringIO(), []

    def look(prompt):
        with urllib.request.urlopen(urls[0]) as r:
            html = r.read().decode()
        assert "Outfit_v1.0.zip" in html and "別のファイルを調べる" in html
        return ""

    env = Env(out=out, now=lambda: NOW, input=look, isatty=lambda: True,
              environ={"UPKG_PRECHECK_DOCS": str(tmp_path / "docs")}, open_url=urls.append)
    assert main([str(z)], env) == 0 and len(urls) == 1
