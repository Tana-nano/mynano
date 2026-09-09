"""平文ミラー。

このプロジェクトのコードが全部消えても、記憶が読める状態を保つための保険。
「一生自分のもの」を成立させているのは、実のところこのモジュールである。

  archive/YYYY-MM.jsonl   生ログの追記ミラー（1行1イベント）
  archive/stars.jsonl     ⭐ の追記ミラー（1行1操作。教師データの一次資料）
  export/notes/*.md       ノートの Markdown 書き出し（YAMLフロントマター付き）
"""

from __future__ import annotations

import json
from pathlib import Path

from .db import Database, now as db_now, to_iso
from .events import Event
from . import episodes as episodes_store
from . import notes as notes_store


def mirror_event(archive_dir: str | Path, event: Event) -> None:
    archive_dir = Path(archive_dir)
    archive_dir.mkdir(parents=True, exist_ok=True)
    target = archive_dir / f"{to_iso(event.ts)[:7]}.jsonl"
    record = {
        "id": event.id,
        "ts": event.ts,
        "time": to_iso(event.ts),
        "session_id": event.session_id,
        "role": event.role,
        "content": event.content,
        "meta": event.meta,
    }
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def mirror_star(
    archive_dir: str | Path,
    action: str,
    event_id: int,
    session_id: str,
    user_text: str,
    answer: str,
    rating: int = 0,
    reason: str = "",
    prompt: list[dict[str, str]] | None = None,
    model: str = "",
    adapter: str = "",
    ts: float | None = None,
) -> None:
    """⭐ の操作を追記する。付けたときも外したときも1行増える（消えない）。

    プロンプトごと平文で残すのは、DB が失われても教師データを組み直せるようにするため。
    ここが埋まっていれば、nano のコードが全部消えても QLoRA は回せる。
    """
    archive_dir = Path(archive_dir)
    archive_dir.mkdir(parents=True, exist_ok=True)
    ts = db_now() if ts is None else ts
    record = {
        "ts": ts,
        "time": to_iso(ts),
        "action": action,          # star | avoid | unstar
        "rating": rating,
        "event_id": event_id,
        "session_id": session_id,
        "reason": reason,
        "user": user_text,
        "answer": answer,
        "prompt": prompt or [],
        # 誰が出した応答への印か。DB が失われてもここから世代を分けられる。
        "model": model,
        "adapter": adapter,
    }
    with (archive_dir / "stars.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _yaml_scalar(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def export_notes(db: Database, export_dir: str | Path) -> int:
    """全ノートを Markdown に書き出す。Obsidian でもそのまま開ける形にしておく。"""
    export_dir = Path(export_dir)
    notes_dir = export_dir / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)

    all_notes = notes_store.iter_notes(
        db, states=(notes_store.STATE_ACTIVE, notes_store.STATE_COLD, notes_store.STATE_MERGED)
    )
    for note in all_notes:
        links = db.query(
            "SELECT dst_id, relation, weight FROM links WHERE src_id=? ORDER BY weight DESC",
            (note.id,),
        )
        front = {
            "id": note.id,
            "kind": note.kind,
            "category": note.category,
            "state": note.state,
            "importance": round(note.importance, 3),
            "half_life_days": round(note.half_life_days, 3),
            "access_count": note.access_count,
            "created": to_iso(note.created_at),
            "last_accessed": to_iso(note.last_accessed_at),
        }
        lines = ["---"]
        lines += [f"{key}: {_yaml_scalar(value)}" for key, value in front.items()]
        lines.append("tags: [" + ", ".join(json.dumps(t, ensure_ascii=False) for t in note.tags) + "]")
        lines.append(
            "keywords: [" + ", ".join(json.dumps(k, ensure_ascii=False) for k in note.keywords) + "]"
        )
        lines.append("---")
        lines.append("")
        lines.append(note.content)
        if note.context:
            lines += ["", "> " + note.context.replace("\n", "\n> ")]
        if links:
            lines += ["", "## links"]
            lines += [
                f"- {row['relation']} ({row['weight']:.2f}) → [[note-{row['dst_id']}]]"
                for row in links
            ]
        (notes_dir / f"note-{note.id:06d}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    index = ["# 記憶インデックス", ""]
    for episode in episodes_store.recent(db, limit=10_000):
        index.append(f"## {to_iso(episode.started_at)} — {episode.summary or '(未要約)'}")
        for note in db.query(
            "SELECT id, content, state FROM notes WHERE source_episode_id=? ORDER BY id",
            (episode.id,),
        ):
            mark = "" if note["state"] == "active" else f" _({note['state']})_"
            index.append(f"- [[note-{note['id']}]] {note['content']}{mark}")
        index.append("")
    (export_dir / "index.md").write_text("\n".join(index) + "\n", encoding="utf-8")
    return len(all_notes)
