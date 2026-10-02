"""The drop screen: a small web server on this PC that the browser hands dropped files to.

A browser page cannot read file paths, so the page uploads each zip / unitypackage to this
server, which keeps them in a temporary folder only while it checks them. Nothing leaves the PC:
- the server listens on 127.0.0.1 only, on a port the OS picks;
- every URL starts with a random token, so other pages cannot guess it;
- the Host header must be 127.0.0.1 / localhost (guards against DNS rebinding);
- every POST / PUT needs the X-Upkg header, which another site cannot send without a CORS
  preflight that this server never answers, and a foreign Origin is refused.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import socket
import socketserver
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from .archive import SUPPORTED
from .html_report import AppChrome, render_home
from .known import KnownAssets
from .pipeline import Outcome, Settings, app_page, inspect, save_outcome
from .report import run_dir_label

CHUNK = 1 << 20
_ID = re.compile(r"[0-9a-f]{16}")
_CSP = ("default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; "
        "img-src data:; form-action 'none'; frame-ancestors 'none'; base-uri 'none'")


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False  # never share the port (CLAUDE.md: UDP/TCP port takeover on Windows)

    def server_bind(self) -> None:
        if os.name == "nt":
            # UNVERIFIED on Windows: keeps any other program off this port.
            self.socket.setsockopt(socket.SOL_SOCKET, getattr(socket, "SO_EXCLUSIVEADDRUSE", -5), 1)
        # HTTPServer.server_bind also looks up the host name (getfqdn), which can stall on Windows.
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = "127.0.0.1", self.server_address[1]


class Refused(Exception):
    """A request the page should explain to the user (status, message)."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


@dataclass
class _Job:
    folder: Path
    uploads: dict[tuple[int, int], Path] = field(default_factory=dict)


class App:
    def __init__(self, known: KnownAssets, settings: Settings, root: Path, root_label: str,
                 now: Callable[[], datetime], say: Callable[[str], None],
                 open_folder: Callable[[Path], None]):
        self.known, self.settings, self.root, self.root_label = known, settings, root, root_label
        self.now, self.say, self.open_folder = now, say, open_folder
        self.token = secrets.token_hex(16)
        self.base = f"/{self.token}"
        self.pages: dict[str, str] = {}
        self.folders: dict[str, Path] = {}
        self.jobs: dict[str, _Job] = {}
        self.busy = threading.Lock()
        self.httpd: ThreadingHTTPServer | None = None
        self.tmp: Path | None = None

    # -------------------------------------------------------------- lifecycle

    def start(self) -> str:
        """Listen on 127.0.0.1 and return the address of the first screen. Raises OSError."""
        handler = type("Handler", (_Handler,), {"app": self})
        self.httpd = _Server(("127.0.0.1", 0), handler)
        self.port = self.httpd.server_address[1]
        self.hosts = {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}
        self.origins = {f"http://{h}" for h in self.hosts}
        self.tmp = Path(tempfile.mkdtemp(prefix="upkg-precheck-"))
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return self.url("/")

    def stop(self) -> None:
        if self.httpd is not None:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None
        if self.tmp is not None:
            shutil.rmtree(self.tmp, ignore_errors=True)
            self.tmp = None

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{self.base}{path}"

    # -------------------------------------------------------------- results

    def add_result(self, o: Outcome, now: datetime) -> str:
        """Keep the page for a finished check; returns its path below the token."""
        rid = secrets.token_hex(8)
        label = f"{self.root_label}\\{o.folder.name}" if o.folder is not None else None
        chrome = AppChrome(self.base, rid, label)
        self.pages[rid] = app_page(o, self.settings, self.known, now, chrome)
        if o.folder is not None:
            self.folders[rid] = o.folder
        return f"/results/{rid}"

    def home(self) -> str:
        return render_home(self.known, AppChrome(self.base))

    # -------------------------------------------------------------- jobs

    def new_job(self) -> str:
        assert self.tmp is not None
        jid = secrets.token_hex(8)
        folder = self.tmp / jid
        folder.mkdir()
        self.jobs[jid] = _Job(folder)
        return jid

    def job(self, jid: str) -> _Job:
        job = self.jobs.get(jid) if _ID.fullmatch(jid) else None
        if job is None:
            raise Refused(404, "受け付けが見つかりません。ページを開き直して、もう一度ドロップしてください。")
        return job

    def run_job(self, jid: str, roots: object) -> str:
        job = self.job(jid)
        if not self.busy.acquire(blocking=False):
            raise Refused(409, "ほかの検品が終わるまでお待ちください。")
        try:
            files, messages, first = self._files_of(job, roots)
            self.say("")
            for m in messages:
                self.say(m)
            o = inspect(files, self.settings, self.known, self.say) if files else None
            if o is None:
                if not files:
                    self.say("調べられるファイルがありませんでした。")
                raise Refused(422, "\n".join(messages + ["調べられるファイルがありませんでした。"]))
            now = self.now()
            folder = self.root / run_dir_label(first, now)
            try:
                save_outcome(o, self.settings, self.known, now, folder)
                self.say(f"保存先: {self.root_label}\\{folder.name}")
            except OSError as e:
                o.folder = None
                self.say(f"保存できませんでした: {folder}（{e.strerror or e}）")
            return self.add_result(o, now)
        finally:
            self.busy.release()
            self.jobs.pop(jid, None)
            shutil.rmtree(job.folder, ignore_errors=True)

    def _files_of(self, job: _Job, roots: object) -> tuple[list[tuple[Path, str]], list[str], str]:
        """Same names and order as expand_inputs gives for the same files on the command line."""
        if not isinstance(roots, list) or not roots:
            raise Refused(400, "ファイルの一覧が空です。")
        files: list[tuple[Path, str]] = []
        messages: list[str] = []
        first = ""
        for i, r in enumerate(roots):
            if not isinstance(r, dict) or not isinstance(r.get("name"), str) or not isinstance(r.get("files"), list):
                raise Refused(400, "ファイルの一覧が読めません。")
            name, is_dir = _clean_name(r["name"]), bool(r.get("dir"))
            entries = []
            for j, f in enumerate(r["files"]):
                if not isinstance(f, dict) or not isinstance(f.get("rel"), str) or not isinstance(f.get("size"), int):
                    raise Refused(400, "ファイルの一覧が読めません。")
                rel = [_clean_name(part) for part in f["rel"].split("/")]
                if Path(rel[-1]).suffix.lower() in SUPPORTED:
                    entries.append((j, rel, f["size"]))
            if is_dir:
                if not entries:
                    messages.append(f"{name}: zip も unitypackage も見つかりませんでした")
                if not first:
                    first = name
                entries.sort(key=lambda e: "/".join(e[1]).lower())
            elif not entries:
                messages.append(f"{name}: 対応していない形式です（zip か unitypackage を指定してください）")
            elif not first:
                first = Path(name).stem
            for j, rel, size in entries:
                files.append((self._arrived(job, i, j, rel[-1], size), "\\".join(rel) if is_dir else name))
        return files, messages, first or "input"

    def _arrived(self, job: _Job, i: int, j: int, base: str, size: int) -> Path:
        part = job.uploads.get((i, j))
        if part is None:
            raise Refused(400, f"{base}: 届いていません。もう一度ドロップしてください。")
        if part.stat().st_size != size:
            raise Refused(400, f"{base}: 途中までしか届きませんでした。もう一度ドロップしてください。")
        # read_input tells zips from unitypackages by the suffix; the display name is passed separately.
        return part.rename(part.with_suffix(Path(base).suffix.lower()))

    def receive(self, jid: str, i: int, j: int, length: int, stream) -> None:
        job = self.job(jid)
        part = job.folder / f"{i}-{j}.part"
        left = length
        try:
            with part.open("wb") as out:
                while left > 0:
                    chunk = stream.read(min(CHUNK, left))
                    if not chunk:
                        raise Refused(400, "読み込みが途中で止まりました。もう一度ドロップしてください。")
                    out.write(chunk)
                    left -= len(chunk)
        except OSError as e:
            raise Refused(507, f"一時フォルダに置けませんでした（{e.strerror or e}）。空き容量を確かめてください。") from None
        job.uploads[(i, j)] = part

    def open_result_folder(self, rid: str) -> None:
        folder = self.folders.get(rid)
        if folder is None:
            raise Refused(404, "保存先が見つかりません。")
        try:
            self.open_folder(folder)
        except OSError as e:
            raise Refused(500, f"フォルダを開けませんでした（{e.strerror or e}）。") from None


def _clean_name(s: str) -> str:
    """A file or folder name as the browser gave it; anything path-like is refused."""
    if not s or s in (".", "..") or any(c in s for c in '/\\:\x00') or len(s) > 255:
        raise Refused(400, "ファイル名が読めません。")
    return s


class _Handler(BaseHTTPRequestHandler):
    app: App
    server_version = "upkg-precheck"
    sys_version = ""

    def log_message(self, format: str, *args: object) -> None:  # keep the console for results
        pass

    # ---------------------------------------------------------- responses

    def _send(self, status: int, body: bytes, ctype: str, extra: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", _CSP)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, obj: dict) -> None:
        self._send(status, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def _html(self, text: str) -> None:
        self._send(200, text.encode(), "text/html; charset=utf-8")

    def _route(self) -> list[str] | None:
        """Path parts below the token, or None after answering a request that is not ours."""
        if self.headers.get("Host", "") not in self.app.hosts:
            self._send(403, b"forbidden", "text/plain")
            return None
        path = urlsplit(self.path).path
        if path == self.app.base:
            self._send(303, b"", "text/plain", {"Location": self.app.base + "/"})
            return None
        if not path.startswith(self.app.base + "/"):
            self._send(404, b"not found", "text/plain")
            return None
        return [p for p in path[len(self.app.base) + 1:].split("/") if p]

    def _write_allowed(self) -> bool:
        origin = self.headers.get("Origin")
        if self.headers.get("X-Upkg") != "1" or (origin is not None and origin not in self.app.origins):
            self._send(403, b"forbidden", "text/plain")
            return False
        return True

    # ---------------------------------------------------------- methods

    def do_GET(self) -> None:
        parts = self._route()
        if parts is None:
            return
        if not parts:
            return self._html(self.app.home())
        if len(parts) == 2 and parts[0] == "results" and parts[1] in self.app.pages:
            return self._html(self.app.pages[parts[1]])
        self._send(404, "ページが見つかりません。".encode(), "text/plain; charset=utf-8")

    do_HEAD = do_GET

    def do_POST(self) -> None:
        parts = self._route()
        if parts is None or not self._write_allowed():
            return
        try:
            if parts == ["jobs"]:
                return self._json(200, {"job": self.app.new_job()})
            if len(parts) == 3 and parts[0] == "jobs" and parts[2] == "run":
                body = self._body_json()
                return self._json(200, {"url": self.app.base + self.app.run_job(parts[1], body.get("roots"))})
            if len(parts) == 3 and parts[0] == "results" and parts[2] == "open":
                self.app.open_result_folder(parts[1])
                return self._json(200, {})
            raise Refused(404, "見つかりません。")
        except Refused as e:
            self._json(e.status, {"error": str(e)})
        except Exception as e:  # never leave the page waiting
            self._json(500, {"error": f"予期しないエラーが起きました: {type(e).__name__}: {e}"})

    def do_PUT(self) -> None:
        parts = self._route()
        if parts is None or not self._write_allowed():
            return
        try:
            if len(parts) != 4 or parts[0] != "jobs" or not (parts[2].isdigit() and parts[3].isdigit()):
                raise Refused(404, "見つかりません。")
            length = self._length()
            self.app.receive(parts[1], int(parts[2]), int(parts[3]), length, self.rfile)
            self._json(200, {})
        except Refused as e:
            self.close_connection = True  # the rest of an unread body must not be taken as a request
            self._json(e.status, {"error": str(e)})

    def _length(self) -> int:
        try:
            n = int(self.headers.get("Content-Length", ""))
        except ValueError:
            raise Refused(411, "大きさのわからないデータは受け取れません。") from None
        if n < 0:
            raise Refused(400, "大きさが正しくありません。")
        return n

    def _body_json(self) -> dict:
        n = self._length()
        if n > 4 << 20:
            raise Refused(413, "ファイルの一覧が大きすぎます。")
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            raise Refused(400, "ファイルの一覧が読めません。") from None
        if not isinstance(body, dict):
            raise Refused(400, "ファイルの一覧が読めません。")
        return body
