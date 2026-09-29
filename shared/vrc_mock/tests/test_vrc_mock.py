from datetime import datetime

from pythonosc.udp_client import SimpleUDPClient

from vrc_mock import FakeVRChat, LogWriter, OscRecorder, format_line
from vrc_mock.osc import AVATAR_PARAM_PREFIX, CHATBOX_INPUT


def test_fake_vrchat_records_parameters_and_chatbox():
    with FakeVRChat() as vrc:
        product = SimpleUDPClient("127.0.0.1", vrc.in_port)
        product.send_message(AVATAR_PARAM_PREFIX + "Sleeping", True)
        product.send_message(CHATBOX_INPUT, ["おやすみ", True, False])

        assert vrc.wait_for(CHATBOX_INPUT) is not None
        assert vrc.received_parameters() == {"Sleeping": True}
        assert vrc.chatbox_texts() == ["おやすみ"]


def test_fake_vrchat_emits_parameters_to_product():
    with FakeVRChat() as vrc, OscRecorder(listen_port=vrc.out_port) as product:
        vrc.set_parameter("HeartRate", 62)
        vrc.set_parameter("AFK", False)
        msg = product.wait_for(AVATAR_PARAM_PREFIX + "HeartRate")
        assert msg is not None and msg.args == (62,)
        assert product.wait_for(AVATAR_PARAM_PREFIX + "AFK").args == (False,)


def test_log_writer_produces_vrchat_shaped_lines(tmp_path):
    w = LogWriter(tmp_path, start=datetime(2026, 9, 29, 23, 0, 0))
    w.join("wrld_abc", "1234", "Sleep World", owner_user_id="usr_me")
    w.player_joined("Alice", "usr_a")
    w.advance(minutes=30)
    w.player_left("Alice", "usr_a")
    w.leave()

    text = w.path.read_text(encoding="utf-8").splitlines()
    assert w.path.name == "output_log_2026-09-29_23-00-00.txt"
    assert text[0] == "2026.09.29 23:00:00 Log        -  [Behaviour] Joining wrld_abc:1234~private(usr_me)~region(jp)"
    assert text[1].endswith("[Behaviour] Entering Room: Sleep World")
    assert text[2].endswith("[Behaviour] OnPlayerJoined Alice (usr_a)")
    assert text[3].startswith("2026.09.29 23:30:00")
    assert text[3].endswith("[Behaviour] OnPlayerLeft Alice (usr_a)")
    assert text[4].endswith("[Behaviour] OnLeftRoom")


def test_format_line_matches_fixture_layout():
    line = format_line(datetime(2026, 9, 29, 1, 2, 3), "[Behaviour] OnLeftRoom")
    assert line == "2026.09.29 01:02:03 Log        -  [Behaviour] OnLeftRoom"
