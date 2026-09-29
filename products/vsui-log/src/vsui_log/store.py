"""SQLite storage (%APPDATA%\\VsuiLog\\vsui.db).

Other people's display names / user ids live only here and in files the user
explicitly exports. ``people`` rows are created only for confirmed co-sleepers
and visitors.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS nights (
    id INTEGER PRIMARY KEY,
    night_date TEXT NOT NULL,
    mode TEXT NOT NULL,
    source TEXT NOT NULL,
    world_id TEXT,
    world_name TEXT,
    instance_access TEXT,
    instance_key TEXT,
    stay_start TEXT,
    stay_end TEXT,
    sleep_start TEXT,
    sleep_end TEXT,
    sleep_minutes INTEGER,
    awakenings INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE (source, instance_key, stay_start),
    UNIQUE (sleep_start)
);
CREATE TABLE IF NOT EXISTS people (
    id INTEGER PRIMARY KEY,
    display_name TEXT NOT NULL,
    user_id TEXT UNIQUE,
    first_seen TEXT NOT NULL,
    is_self INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS presence (
    night_id INTEGER NOT NULL REFERENCES nights(id) ON DELETE CASCADE,
    person_id INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    joined_at TEXT NOT NULL,
    left_at TEXT,
    role TEXT NOT NULL,
    thanked INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (night_id, person_id)
);
CREATE TABLE IF NOT EXISTS samples (ts TEXT PRIMARY KEY, motion REAL);
CREATE TABLE IF NOT EXISTS achievements (key TEXT PRIMARY KEY, unlocked_at TEXT NOT NULL, night_date TEXT);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def _iso(v: datetime | date | None) -> str | None:
    return v.isoformat(timespec="seconds") if isinstance(v, datetime) else (v.isoformat() if v else None)


def _dt(v: str | None) -> datetime | None:
    return datetime.fromisoformat(v) if v else None


@dataclass
class PersonRecord:
    display_name: str
    user_id: str | None
    joined_at: datetime
    left_at: datetime | None
    role: str  # co_sleeper | visitor


@dataclass
class NightRecord:
    night_date: date
    mode: str  # vr | log_only
    source: str  # motion | oyasumi | log
    world_id: str | None = None
    world_name: str | None = None
    instance_access: str | None = None
    instance_key: str | None = None
    stay_start: datetime | None = None
    stay_end: datetime | None = None
    sleep_start: datetime | None = None
    sleep_end: datetime | None = None
    sleep_minutes: int | None = None
    awakenings: int = 0
    people: list[PersonRecord] = field(default_factory=list)
    id: int | None = None


class Store:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path) if path != ":memory:" else None
        self.recovered_from: Path | None = None
        self.conn = self._open(path)

    def _open(self, path: Path | str) -> sqlite3.Connection:
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            conn = self._connect(path)
            if conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise sqlite3.DatabaseError("quick_check failed")
            conn.executescript(SCHEMA)
            return conn
        except sqlite3.DatabaseError:
            if self.path is None:
                raise
            try:
                conn.close()
            except Exception:
                pass
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            broken = self.path.with_name(f"{self.path.name}.broken-{stamp}")
            self.path.replace(broken)
            self.recovered_from = broken
            conn = self._connect(path)
            conn.executescript(SCHEMA)
            return conn

    @staticmethod
    def _connect(path: Path | str) -> sqlite3.Connection:
        conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def close(self) -> None:
        self.conn.close()

    # --- meta / checkpoint ---------------------------------------------------

    def get_meta(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    def set_meta(self, key: str, value: str | None) -> None:
        if value is None:
            self.conn.execute("DELETE FROM meta WHERE key=?", (key,))
        else:
            self.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", (key, value))

    def save_checkpoint(self, data: dict[str, Any]) -> None:
        self.set_meta("checkpoint", json.dumps(data, ensure_ascii=False))

    def load_checkpoint(self) -> dict[str, Any] | None:
        raw = self.get_meta("checkpoint")
        return json.loads(raw) if raw else None

    def clear_checkpoint(self) -> None:
        self.set_meta("checkpoint", None)

    # --- nights ------------------------------------------------------------

    def _person_id(self, p: PersonRecord, seen: datetime) -> int:
        if p.user_id:
            row = self.conn.execute("SELECT id FROM people WHERE user_id=?", (p.user_id,)).fetchone()
            if row:
                self.conn.execute("UPDATE people SET display_name=? WHERE id=?", (p.display_name, row["id"]))
                return row["id"]
        else:
            row = self.conn.execute(
                "SELECT id FROM people WHERE user_id IS NULL AND display_name=?", (p.display_name,)
            ).fetchone()
            if row:
                return row["id"]
        cur = self.conn.execute(
            "INSERT INTO people(display_name, user_id, first_seen) VALUES (?, ?, ?)",
            (p.display_name, p.user_id, _iso(seen)),
        )
        return int(cur.lastrowid)

    def save_night(self, n: NightRecord) -> int | None:
        """Insert a night and its people. Returns None if it was already stored."""
        with self.conn:
            self.conn.execute("BEGIN")
            try:
                cur = self.conn.execute(
                    """INSERT INTO nights(night_date, mode, source, world_id, world_name, instance_access,
                       instance_key, stay_start, stay_end, sleep_start, sleep_end, sleep_minutes, awakenings, created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        _iso(n.night_date), n.mode, n.source, n.world_id, n.world_name, n.instance_access,
                        n.instance_key, _iso(n.stay_start), _iso(n.stay_end), _iso(n.sleep_start),
                        _iso(n.sleep_end), n.sleep_minutes, n.awakenings, _iso(datetime.now()),
                    ),
                )
            except sqlite3.IntegrityError:
                return None
            night_id = int(cur.lastrowid)
            for p in n.people:
                pid = self._person_id(p, p.joined_at)
                self.conn.execute(
                    "INSERT OR IGNORE INTO presence(night_id, person_id, joined_at, left_at, role) VALUES (?,?,?,?,?)",
                    (night_id, pid, _iso(p.joined_at), _iso(p.left_at), p.role),
                )
        n.id = night_id
        return night_id

    def _row_to_night(self, r: sqlite3.Row) -> NightRecord:
        n = NightRecord(
            night_date=date.fromisoformat(r["night_date"]), mode=r["mode"], source=r["source"],
            world_id=r["world_id"], world_name=r["world_name"], instance_access=r["instance_access"],
            instance_key=r["instance_key"], stay_start=_dt(r["stay_start"]), stay_end=_dt(r["stay_end"]),
            sleep_start=_dt(r["sleep_start"]), sleep_end=_dt(r["sleep_end"]),
            sleep_minutes=r["sleep_minutes"], awakenings=r["awakenings"], id=r["id"],
        )
        return n

    def nights_between(self, start: date, end: date) -> list[NightRecord]:
        rows = self.conn.execute(
            "SELECT * FROM nights WHERE night_date BETWEEN ? AND ? ORDER BY night_date, COALESCE(sleep_start, stay_start)",
            (start.isoformat(), end.isoformat()),
        ).fetchall()
        return [self._row_to_night(r) for r in rows]

    def nights_on(self, d: date) -> list[NightRecord]:
        return self.nights_between(d, d)

    def all_night_dates(self) -> list[date]:
        rows = self.conn.execute("SELECT DISTINCT night_date FROM nights ORDER BY night_date").fetchall()
        return [date.fromisoformat(r[0]) for r in rows]

    def latest_night_date(self) -> date | None:
        row = self.conn.execute("SELECT MAX(night_date) FROM nights").fetchone()
        return date.fromisoformat(row[0]) if row and row[0] else None

    def total_sleep_minutes(self) -> int:
        return int(self.conn.execute("SELECT COALESCE(SUM(sleep_minutes), 0) FROM nights").fetchone()[0])

    def presence_for(self, night_ids: Iterable[int]) -> list[dict[str, Any]]:
        ids = list(night_ids)
        if not ids:
            return []
        q = ",".join("?" * len(ids))
        rows = self.conn.execute(
            f"""SELECT pr.night_id, pr.person_id, pe.display_name, pe.user_id, pr.joined_at, pr.left_at,
                       pr.role, pr.thanked
                FROM presence pr JOIN people pe ON pe.id = pr.person_id
                WHERE pr.night_id IN ({q}) ORDER BY pr.joined_at""",
            ids,
        ).fetchall()
        return [
            {**dict(r), "joined_at": _dt(r["joined_at"]), "left_at": _dt(r["left_at"]), "thanked": bool(r["thanked"])}
            for r in rows
        ]

    def co_sleeper_counts(self, start: date | None = None, end: date | None = None) -> list[tuple[str, int]]:
        sql = """SELECT pe.display_name, COUNT(DISTINCT n.night_date) AS c
                 FROM presence pr JOIN people pe ON pe.id = pr.person_id JOIN nights n ON n.id = pr.night_id
                 WHERE pr.role = 'co_sleeper'"""
        args: list[str] = []
        if start and end:
            sql += " AND n.night_date BETWEEN ? AND ?"
            args += [start.isoformat(), end.isoformat()]
        sql += " GROUP BY pe.id ORDER BY c DESC, pe.display_name"
        return [(r[0], r[1]) for r in self.conn.execute(sql, args).fetchall()]

    def set_thanked(self, night_id: int, person_id: int, value: bool = True) -> None:
        self.conn.execute(
            "UPDATE presence SET thanked=? WHERE night_id=? AND person_id=?", (int(value), night_id, person_id)
        )

    def forget(self, display_name: str | None = None) -> int:
        """Delete one person (by display name) or everyone. Returns people removed."""
        with self.conn:
            self.conn.execute("BEGIN")
            if display_name is None:
                n = self.conn.execute("SELECT COUNT(*) FROM people").fetchone()[0]
                self.conn.execute("DELETE FROM presence")
                self.conn.execute("DELETE FROM people")
                return int(n)
            ids = [r[0] for r in self.conn.execute("SELECT id FROM people WHERE display_name=?", (display_name,))]
            for pid in ids:
                self.conn.execute("DELETE FROM presence WHERE person_id=?", (pid,))
                self.conn.execute("DELETE FROM people WHERE id=?", (pid,))
            return len(ids)

    def count_people(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM people").fetchone()[0])

    # --- samples ---------------------------------------------------------------

    def add_sample(self, ts: datetime, motion: float | None) -> None:
        self.conn.execute("INSERT OR REPLACE INTO samples(ts, motion) VALUES (?, ?)", (_iso(ts), motion))

    def prune_samples(self, now: datetime, keep_days: int) -> None:
        self.conn.execute("DELETE FROM samples WHERE ts < ?", (_iso(now - timedelta(days=keep_days)),))

    # --- achievements ------------------------------------------------------------

    def unlocked(self) -> dict[str, dict[str, Any]]:
        rows = self.conn.execute("SELECT key, unlocked_at, night_date FROM achievements").fetchall()
        return {r["key"]: {"unlocked_at": _dt(r["unlocked_at"]), "night_date": r["night_date"]} for r in rows}

    def unlock(self, key: str, when: datetime, night_date: date) -> bool:
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO achievements(key, unlocked_at, night_date) VALUES (?,?,?)",
            (key, _iso(when), night_date.isoformat()),
        )
        return cur.rowcount == 1
