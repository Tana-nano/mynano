"""Tonight / weekly summaries as console text, standalone HTML, CSV and chapters.

HTML is self-contained: inline CSS and SVG, no external URLs.
"""

from __future__ import annotations

import csv
import html
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path

from .achievements import ACHIEVEMENTS, current_streak
from .store import NightRecord, Store

NOTE_DESKTOP = "睡眠時間は計測していません（デスクトップモード）"
NOTE_UNDETECTED = '動きからは入眠を判定できませんでした。設定の detect.sensitivity = "high" を試してください'


def fmt_duration(minutes: int | None) -> str:
    if minutes is None:
        return "―"
    h, m = divmod(int(minutes), 60)
    return f"{h}時間{m:02d}分" if h else f"{m}分"


def fmt_time(t: datetime | time | None) -> str:
    return f"{t.hour}:{t.minute:02d}" if t is not None else "―"


def fmt_date(d: date) -> str:
    return f"{d.year}年{d.month}月{d.day}日"


def mean_clock_time(times: list[datetime]) -> time | None:
    """Average clock time around midnight: 23:30 and 0:30 average to 0:00."""
    if not times:
        return None
    # Offset from noon so the night is contiguous (noon=0 ... midnight=720 ... next noon=1440).
    offs = [((t.hour * 60 + t.minute) - 12 * 60) % 1440 for t in times]
    avg = round(sum(offs) / len(offs))
    total = (avg + 12 * 60) % 1440
    return time(total // 60, total % 60)


@dataclass
class Visitor:
    time: datetime
    name: str
    thanked: bool
    night_id: int
    person_id: int


@dataclass
class TonightView:
    date: date
    nights: list[NightRecord]
    world_names: list[str]
    sleep_start: datetime | None
    sleep_end: datetime | None
    sleep_minutes: int | None
    awakenings: int
    co_sleepers: list[str]
    visitors: list[Visitor]
    achievements: list[str] = field(default_factory=list)
    note: str | None = None

    @property
    def measured(self) -> bool:
        return self.sleep_minutes is not None


def tonight_view(store: Store, d: date | None = None) -> TonightView | None:
    d = d or store.latest_night_date()
    if d is None:
        return None
    nights = store.nights_on(d)
    if not nights:
        return None
    measured = [n for n in nights if n.sleep_minutes is not None]
    pres = store.presence_for([n.id for n in nights if n.id is not None])
    co: list[str] = []
    visitors: list[Visitor] = []
    for p in pres:
        if p["role"] == "co_sleeper":
            if p["display_name"] not in co:
                co.append(p["display_name"])
        else:
            visitors.append(Visitor(p["joined_at"], p["display_name"], p["thanked"], p["night_id"], p["person_id"]))
    worlds: list[str] = []
    for n in nights:
        if n.world_name and n.world_name not in worlds:
            worlds.append(n.world_name)
    note = None
    if not measured:
        note = NOTE_DESKTOP if all(n.mode == "log_only" for n in nights) else NOTE_UNDETECTED
    ach = [ACHIEVEMENTS[k] for k, v in store.unlocked().items() if v["night_date"] == d.isoformat()]
    return TonightView(
        date=d,
        nights=nights,
        world_names=worlds,
        sleep_start=min((n.sleep_start for n in measured if n.sleep_start), default=None),
        sleep_end=max((n.sleep_end for n in measured if n.sleep_end), default=None),
        sleep_minutes=sum(n.sleep_minutes or 0 for n in measured) if measured else None,
        awakenings=sum(n.awakenings for n in nights),
        co_sleepers=co,
        visitors=sorted(visitors, key=lambda v: v.time),
        achievements=ach,
        note=note,
    )


def tonight_text(v: TonightView) -> str:
    lines = [f"■ {fmt_date(v.date)}の夜", f"  ワールド   : {' / '.join(v.world_names) or '―'}"]
    if v.measured:
        lines += [
            f"  入眠       : {fmt_time(v.sleep_start)}",
            f"  起床       : {fmt_time(v.sleep_end)}",
            f"  睡眠時間   : {fmt_duration(v.sleep_minutes)}（途中で起きた回数 {v.awakenings}）",
        ]
    if v.note:
        lines.append(f"  ※ {v.note}")
    lines.append(f"  一緒に寝た人: {len(v.co_sleepers)}人 {('（' + '、'.join(v.co_sleepers) + '）') if v.co_sleepers else ''}")
    lines.append(f"  寝ている間に来た人: {len(v.visitors)}人")
    for i, vis in enumerate(v.visitors, 1):
        mark = "✓お礼済み" if vis.thanked else ""
        lines.append(f"    {i}. {fmt_time(vis.time)} {vis.name} {mark}".rstrip())
    if v.achievements:
        lines.append(f"  実績解除   : {'、'.join(v.achievements)}")
    return "\n".join(lines)


_CSS = """
:root{--bg:#f7f6fb;--fg:#1d1b2e;--muted:#6b6880;--card:#ffffff;--accent:#5b4bc4;--line:#e2dff0}
@media (prefers-color-scheme: dark){:root{--bg:#14121f;--fg:#ecebf5;--muted:#a19fb6;--card:#1e1b2e;--accent:#a89cf5;--line:#2e2a45}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font-family:"Yu Gothic UI","Meiryo",system-ui,sans-serif;line-height:1.6}
main{max-width:720px;margin:0 auto;padding:24px 16px}
h1{font-size:1.4rem;margin:0 0 4px}.sub{color:var(--muted);margin:0 0 20px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 20px;margin-bottom:16px}
.big{font-size:2.2rem;font-weight:700;color:var(--accent)}
dl{display:grid;grid-template-columns:max-content 1fr;gap:4px 16px;margin:0}dt{color:var(--muted)}dd{margin:0}
ul{margin:0;padding-left:1.2em}.note{color:var(--muted)}svg text{fill:var(--muted);font-size:11px}
.bar{fill:var(--accent)}
"""


def _page(title: str, body: str) -> str:
    return (
        '<!doctype html><html lang="ja"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{html.escape(title)}</title><style>{_CSS}</style></head>"
        f"<body><main>{body}</main></body></html>"
    )


def tonight_html(v: TonightView) -> str:
    e = html.escape
    parts = [f"<h1>{e(fmt_date(v.date))}の夜</h1>", f'<p class="sub">{e(" / ".join(v.world_names) or "ワールド不明")}</p>']
    if v.measured:
        parts.append(
            f'<section class="card"><div class="big">{e(fmt_duration(v.sleep_minutes))}</div>'
            f"<dl><dt>入眠</dt><dd>{fmt_time(v.sleep_start)}</dd><dt>起床</dt><dd>{fmt_time(v.sleep_end)}</dd>"
            f"<dt>途中で起きた回数</dt><dd>{v.awakenings}</dd></dl></section>"
        )
    if v.note:
        parts.append(f'<p class="card note">{e(v.note)}</p>')
    co = "".join(f"<li>{e(n)}</li>" for n in v.co_sleepers) or "<li>―</li>"
    vis = "".join(
        f"<li>{fmt_time(x.time)} {e(x.name)}{' ✓' if x.thanked else ''}</li>" for x in v.visitors
    ) or "<li>―</li>"
    parts.append(f'<section class="card"><h2>一緒に寝た人（{len(v.co_sleepers)}人）</h2><ul>{co}</ul></section>')
    parts.append(f'<section class="card"><h2>寝ている間に来た人（{len(v.visitors)}人）</h2><ul>{vis}</ul></section>')
    if v.achievements:
        parts.append(f'<section class="card"><h2>実績解除</h2><ul>{"".join(f"<li>{e(a)}</li>" for a in v.achievements)}</ul></section>')
    return _page(f"V睡ログ {fmt_date(v.date)}", "".join(parts))


# --- week ----------------------------------------------------------------------


@dataclass
class WeekView:
    year: int
    week: int
    days: list[tuple[date, int | None, bool]]  # (date, minutes, recorded)
    total_minutes: int
    avg_minutes: int | None
    avg_onset: time | None
    avg_wake: time | None
    nights: int
    streak: int
    top: list[tuple[str, int]]

    @property
    def label(self) -> str:
        return f"{self.year}-W{self.week:02d}"


def week_bounds(year: int, week: int) -> tuple[date, date]:
    start = date.fromisocalendar(year, week, 1)
    return start, start + timedelta(days=6)


def week_view(store: Store, year: int, week: int) -> WeekView:
    start, end = week_bounds(year, week)
    nights = store.nights_between(start, end)
    days: list[tuple[date, int | None, bool]] = []
    for i in range(7):
        d = start + timedelta(days=i)
        ns = [n for n in nights if n.night_date == d]
        mins = [n.sleep_minutes for n in ns if n.sleep_minutes is not None]
        days.append((d, sum(mins) if mins else None, bool(ns)))
    measured = [m for _, m, _ in days if m is not None]
    onsets = [n.sleep_start for n in nights if n.sleep_start]
    wakes = [n.sleep_end for n in nights if n.sleep_end]
    recorded = [d for d, _, r in days if r]
    return WeekView(
        year=year, week=week, days=days,
        total_minutes=sum(measured),
        avg_minutes=round(sum(measured) / len(measured)) if measured else None,
        avg_onset=mean_clock_time(onsets), avg_wake=mean_clock_time(wakes),
        nights=len(recorded),
        streak=current_streak(store.all_night_dates(), recorded[-1]) if recorded else 0,
        top=store.co_sleeper_counts(start, end)[:5],
    )


def week_text(v: WeekView) -> str:
    lines = [
        f"■ {v.label}（{fmt_date(v.days[0][0])}〜{fmt_date(v.days[-1][0])}）",
        f"  合計睡眠   : {fmt_duration(v.total_minutes)}",
        f"  1日平均    : {fmt_duration(v.avg_minutes)}",
        f"  平均入眠   : {fmt_time(v.avg_onset)}   平均起床: {fmt_time(v.avg_wake)}",
        f"  V睡した日  : {v.nights}/7   連続: {v.streak}日",
    ]
    wd = "月火水木金土日"
    for i, (d, m, r) in enumerate(v.days):
        bar = "█" * round((m or 0) / 30)
        lines.append(f"    {wd[i]} {d.month}/{d.day:<2} {bar} {fmt_duration(m) if m is not None else ('記録のみ' if r else '')}")
    if v.top:
        lines.append("  よく一緒に寝た人: " + "、".join(f"{n}（{c}回）" for n, c in v.top))
    return "\n".join(lines)


def week_html(v: WeekView) -> str:
    e = html.escape
    wd = "月火水木金土日"
    maxm = max([m or 0 for _, m, _ in v.days] + [480])
    bw, gap, h = 60, 20, 160
    bars = []
    for i, (d, m, _) in enumerate(v.days):
        bh = round(h * (m or 0) / maxm)
        x = i * (bw + gap)
        bars.append(
            f'<rect class="bar" x="{x}" y="{h - bh}" width="{bw}" height="{bh}" rx="4"><title>{e(fmt_duration(m))}</title></rect>'
            f'<text x="{x + bw / 2}" y="{h + 16}" text-anchor="middle">{wd[i]} {d.month}/{d.day}</text>'
        )
    width = 7 * bw + 6 * gap
    svg = f'<svg viewBox="0 0 {width} {h + 24}" width="100%" role="img" aria-label="日別の睡眠時間">{"".join(bars)}</svg>'
    top = "".join(f"<li>{e(n)}（{c}回）</li>" for n, c in v.top) or "<li>―</li>"
    body = (
        f"<h1>週次レポート {e(v.label)}</h1>"
        f'<p class="sub">{e(fmt_date(v.days[0][0]))}〜{e(fmt_date(v.days[-1][0]))}</p>'
        f'<section class="card"><div class="big">{e(fmt_duration(v.total_minutes))}</div>'
        f"<dl><dt>1日平均</dt><dd>{e(fmt_duration(v.avg_minutes))}</dd>"
        f"<dt>平均入眠</dt><dd>{fmt_time(v.avg_onset)}</dd><dt>平均起床</dt><dd>{fmt_time(v.avg_wake)}</dd>"
        f"<dt>V睡した日</dt><dd>{v.nights}/7</dd><dt>連続</dt><dd>{v.streak}日</dd></dl></section>"
        f'<section class="card">{svg}</section>'
        f'<section class="card"><h2>よく一緒に寝た人</h2><ul>{top}</ul></section>'
    )
    return _page(f"V睡ログ {v.label}", body)


# --- files -----------------------------------------------------------------------

CSV_HEADER = [
    "night_date", "mode", "source", "world_name", "instance_access", "sleep_start", "sleep_end",
    "sleep_minutes", "awakenings", "co_sleepers", "visitors",
]


def export_csv(store: Store, start: date, end: date, path: Path) -> int:
    nights = store.nights_between(start, end)
    pres = store.presence_for([n.id for n in nights if n.id is not None])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(CSV_HEADER)
        for n in nights:
            mine = [p for p in pres if p["night_id"] == n.id]
            w.writerow([
                n.night_date.isoformat(), n.mode, n.source, n.world_name or "", n.instance_access or "",
                n.sleep_start.isoformat(timespec="minutes") if n.sleep_start else "",
                n.sleep_end.isoformat(timespec="minutes") if n.sleep_end else "",
                "" if n.sleep_minutes is None else n.sleep_minutes, n.awakenings,
                ";".join(p["display_name"] for p in mine if p["role"] == "co_sleeper"),
                ";".join(p["display_name"] for p in mine if p["role"] == "visitor"),
            ])
    return len(nights)


def chapters_text(v: TonightView, names: bool = False) -> str:
    out = []
    for x in v.visitors:
        label = f"来客: {x.name}" if names else "来客"
        out.append(f"{x.time.strftime('%H:%M:%S')} {label}")
    return "\n".join(out) + ("\n" if out else "")
