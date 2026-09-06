"""外界の取り込み。

`soul/inbox/` に置いたファイルを読み、`role='world'` のイベントとして記録する。
そのあとは通常の書き込みパイプラインが処理するので、
「自分で話したこと」と「外から入ってきたこと」が同じ記憶として扱われる。

同じファイルを二度記憶しないよう、内容のダイジェストで管理する。
"""

from __future__ import annotations

import hashlib
import shutil
from datetime import datetime
from pathlib import Path

from ...store import events as events_store
from ...store.db import Database, now

SUFFIXES = {".txt", ".md", ".json", ".log", ".csv"}
MAX_CHARS = 20_000
MAX_FILES_PER_RUN = 5


def _already_ingested(db: Database, path: Path, digest: str) -> bool:
    row = db.one("SELECT digest FROM ingested_files WHERE path=?", (str(path),))
    return row is not None and row["digest"] == digest


def _record(db: Database, path: Path, digest: str, size: int, mtime: float) -> None:
    db.execute(
        """INSERT INTO ingested_files(path, size, mtime, digest, ingested_at) VALUES(?,?,?,?,?)
           ON CONFLICT(path) DO UPDATE SET size=excluded.size, mtime=excluded.mtime,
                                           digest=excluded.digest, ingested_at=excluded.ingested_at""",
        (str(path), size, mtime, digest, now()),
    )


def candidates(inbox: Path) -> list[Path]:
    if not inbox.exists():
        return []
    found = [
        path
        for path in sorted(inbox.iterdir())
        if path.is_file() and path.suffix.lower() in SUFFIXES
    ]
    return found[:MAX_FILES_PER_RUN]


def run(app, job) -> str:
    inbox = app.config.inbox_dir
    processed = inbox / "processed"
    processed.mkdir(parents=True, exist_ok=True)

    taken = 0
    for path in candidates(inbox):
        try:
            text = path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError as error:
            return f"{path.name} を読めなかった: {error}"
        if not text:
            path.unlink(missing_ok=True)
            continue

        digest = hashlib.blake2b(text.encode("utf-8"), digest_size=16).hexdigest()
        stat = path.stat()
        if not _already_ingested(app.db, path, digest):
            event = events_store.append(
                app.db,
                session_id="inbox",
                role=events_store.ROLE_WORLD,
                content=f"{path.name} より:\n{text[:MAX_CHARS]}",
                meta={"source": path.name, "digest": digest},
            )
            from ...store import archive

            archive.mirror_event(app.config.archive_dir, event)
            _record(app.db, path, digest, stat.st_size, stat.st_mtime)
            taken += 1

        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.move(str(path), str(processed / f"{stamp}-{path.name}"))

    if not taken:
        return "取り込むものは無かった"

    # 取り込んだものは、次の write ジョブで記憶に変わる
    from ...store import jobs as jobs_store

    jobs_store.enqueue(app.db, "write", priority=5)
    return f"{taken} 件を外界から取り込んだ"
