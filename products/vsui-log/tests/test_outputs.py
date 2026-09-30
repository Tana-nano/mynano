import csv
import io
import re
from datetime import date, datetime, time, timedelta

from PIL import ImageFont

from vsui_log.card import FontNotFound, find_font, render_card
from vsui_log.console import setup_console
from vsui_log.doctor import PoseRecorder, mask_log_lines
from vsui_log.logparse import LogParser
from vsui_log.report import (
    NOTE_DESKTOP,
    NOTE_UNDETECTED,
    chapters_text,
    export_csv,
    fmt_duration,
    mean_clock_time,
    tonight_html,
    tonight_text,
    tonight_view,
    week_html,
    week_text,
    week_view,
)
from vsui_log.store import NightRecord, PersonRecord, Store

D = date(2026, 9, 29)
T = datetime(2026, 9, 29, 23, 20)


def seeded_store() -> Store:
    st = Store(":memory:")
    n = NightRecord(
        night_date=D, mode="vr", source="motion", world_name="Sleep <World>", instance_access="private",
        sleep_start=T, sleep_end=T + timedelta(hours=7, minutes=50), sleep_minutes=470, awakenings=1,
        people=[
            PersonRecord("FixtureAlice", "usr_a", T - timedelta(hours=1), T + timedelta(hours=8), "co_sleeper"),
            PersonRecord("Fixture Bob", "usr_b", T + timedelta(hours=1), T + timedelta(hours=1, minutes=10), "visitor"),
        ],
    )
    st.save_night(n)
    st.unlock("first_night", T + timedelta(hours=8), D)
    for i, mins in ((2, 400), (3, 380)):
        st.save_night(NightRecord(
            night_date=D + timedelta(days=i), mode="vr", source="motion",
            sleep_start=datetime.combine(D + timedelta(days=i + 1), time(0, 30)),
            sleep_end=datetime.combine(D + timedelta(days=i + 1), time(7, 0)), sleep_minutes=mins,
            people=[PersonRecord("FixtureAlice", "usr_a", T, None, "co_sleeper")],
        ))
    return st


def test_format_helpers():
    assert fmt_duration(470) == "7時間50分"
    assert fmt_duration(5) == "5分"
    assert fmt_duration(None) == "―"
    assert mean_clock_time([datetime(2026, 1, 1, 23, 30), datetime(2026, 1, 2, 0, 30)]) == time(0, 0)
    assert mean_clock_time([datetime(2026, 1, 1, 22, 0), datetime(2026, 1, 1, 23, 0)]) == time(22, 30)


def test_tonight_view_text_and_html():
    st = seeded_store()
    v = tonight_view(st, D)
    assert v.sleep_minutes == 470 and v.co_sleepers == ["FixtureAlice"]
    assert [x.name for x in v.visitors] == ["Fixture Bob"]
    assert v.achievements == ["はじめてのV睡"]
    text = tonight_text(v)
    assert "7時間50分" in text and "23:20" in text and "Fixture Bob" in text
    page = tonight_html(v)
    assert "Sleep &lt;World&gt;" in page                          # escaped
    assert not re.search(r"(src|href)=[\"']?https?:", page)       # self-contained
    assert "http://" not in page and "https://" not in page


def test_tonight_view_defaults_to_latest_and_none_when_empty():
    assert tonight_view(Store(":memory:")) is None
    assert tonight_view(seeded_store()).date == D + timedelta(days=3)


def test_log_night_notes():
    st = Store(":memory:")
    st.save_night(NightRecord(night_date=D, mode="log_only", source="log", instance_key="k", stay_start=T))
    assert tonight_view(st, D).note == NOTE_DESKTOP
    st2 = Store(":memory:")
    st2.save_night(NightRecord(night_date=D, mode="vr", source="log", instance_key="k", stay_start=T))
    v = tonight_view(st2, D)
    assert v.note == NOTE_UNDETECTED and "sensitivity" in tonight_text(v)


def test_week_view():
    st = seeded_store()
    y, w, _ = D.isocalendar()
    v = week_view(st, y, w)
    assert v.nights == 3 and v.total_minutes == 470 + 400 + 380
    assert v.avg_onset == time(0, 7)  # 23:20, 0:30, 0:30 -> 0:06.67 -> rounded
    assert v.top[0] == ("FixtureAlice", 3)
    assert v.streak == 2  # 10/1 and 10/2 consecutive
    assert "週次レポート" in week_html(v) and "<svg" in week_html(v)
    assert "FixtureAlice（3回）" in week_text(v)


def test_week_avg_onset_rounding():
    assert mean_clock_time([datetime(2026, 1, 1, 23, 20), datetime(2026, 1, 2, 0, 30), datetime(2026, 1, 3, 0, 30)]) == time(0, 7)


def test_export_csv_bom_header_and_rows(tmp_path):
    st = seeded_store()
    path = tmp_path / "out.csv"
    assert export_csv(st, D, D + timedelta(days=7), path) == 3
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
    assert rows[0][0] == "night_date" and rows[1][9] == "FixtureAlice" and rows[1][10] == "Fixture Bob"


def test_chapters():
    v = tonight_view(seeded_store(), D)
    assert chapters_text(v) == "00:20:00 来客\n"
    assert chapters_text(v, names=True) == "00:20:00 来客: Fixture Bob\n"


def test_card_size_and_names_hidden_by_default():
    v = tonight_view(seeded_store(), D)
    loader = lambda size: ImageFont.load_default(size)  # noqa: E731
    img, texts = render_card(v, streak=3, font_loader=loader)
    assert img.size == (1200, 675)
    joined = " ".join(texts)
    assert "1人" in joined and "3日連続" in joined
    assert "FixtureAlice" not in joined and "Fixture Bob" not in joined
    _, texts2 = render_card(v, streak=3, show_names=True, font_loader=loader)
    assert "FixtureAlice" in " ".join(texts2)


def test_card_font_missing(monkeypatch):
    import pytest
    import vsui_log.card as card
    v = tonight_view(seeded_store(), D)
    assert find_font(["/no/such/font.ttc"]) is None
    monkeypatch.setattr(card, "FONT_CANDIDATES", ["/no/such/font.ttc"])
    with pytest.raises(FontNotFound):
        render_card(v)


def test_console_survives_cp932():
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="cp932", errors="strict")
    setup_console(stream)
    print("💤 おやすみなさい", file=stream)
    stream.flush()
    assert "おやすみなさい".encode("cp932") in raw.getvalue()


FIXTURE_LOG = """\
2026.09.29 22:00:00 Log        -  [Behaviour] User Authenticated: RealMe (usr_11111111-1111-1111-1111-111111111111)
2026.09.29 23:40:59 Log        -  [Behaviour] Joining wrld_4432ea9b-729c-46e3-8eaf-846aa0a37fdd:67646~private(usr_11111111-1111-1111-1111-111111111111)~region(jp)
2026.09.29 23:40:59 Log        -  [Behaviour] Entering Room: My Secret Bedroom
2026.09.29 23:41:02 Log        -  [Behaviour] OnPlayerJoined RealMe (usr_11111111-1111-1111-1111-111111111111)
2026.09.29 23:41:07 Log        -  [Behaviour] OnPlayerJoined Real Friend (usr_22222222-2222-2222-2222-222222222222)
2026.09.29 23:41:08 Log        -  [Network] some unrelated line with Real Friend in it
2026.09.30 06:58:00 Log        -  [Behaviour] OnPlayerLeft Real Friend (usr_22222222-2222-2222-2222-222222222222)
2026.09.30 07:01:22 Log        -  [Behaviour] OnLeftRoom
"""


def test_log_sample_masks_everything_personal():
    out = mask_log_lines(FIXTURE_LOG.splitlines(), LogParser())
    text = "\n".join(out)
    for secret in ("RealMe", "Real Friend", "My Secret Bedroom", "usr_1111", "usr_2222", "4432ea9b"):
        assert secret not in text
    assert "unrelated line" not in text                      # only event lines are emitted
    assert "OnPlayerJoined Player1 (usr_xxxx)" in text
    assert "Entering Room: World1" in text
    assert len(out) == 7


def test_pose_recorder_csv_is_numbers_only(tmp_path):
    rec = PoseRecorder()
    rec(datetime.now(), (0.1, 1.2, 0.3, 1.0, 90.0, 2.0))
    rec(datetime.now(), ("bad",))
    path = tmp_path / "pose.csv"
    rec.write_csv(path)
    rows = list(csv.reader(path.open(encoding="utf-8")))
    assert rows[0] == ["t", "x", "y", "z", "rx", "ry", "rz"]
    assert len(rows) == 2 and all(float(c) or float(c) == 0 for c in rows[1])


def test_card_names_line_truncates():
    from vsui_log.card import NAMES_MAX_CHARS, names_line
    assert names_line("来客: ", ["A", "B"]) == "来客: A、B"
    long = names_line("来客: ", [f"LongDisplayName{i}" for i in range(8)])
    assert len(long) <= NAMES_MAX_CHARS + 8 and long.endswith("人") and "ほか" in long
    assert len(names_line("来客: ", ["x" * 100])) <= NAMES_MAX_CHARS
