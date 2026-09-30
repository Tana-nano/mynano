"""Never take a UDP port another OSC app already holds."""

import socket

import pytest
from pythonosc.dispatcher import Dispatcher
from pythonosc.udp_client import SimpleUDPClient

from vsui_log import doctor, oscio


@pytest.mark.parametrize("other_host", ["0.0.0.0", "127.0.0.1"])
def test_port_free_sees_other_apps_socket(other_host):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as other:
        other.bind((other_host, 0))
        port = other.getsockname()[1]
        assert doctor.port_free(port) is False
    assert doctor.port_free(port) is True


@pytest.fixture
def exclusive_spy(monkeypatch):
    """Pretend to be Windows: record SO_EXCLUSIVEADDRUSE requests instead of applying them."""
    fake_opt = 0x7FFF_0001
    monkeypatch.setattr(socket, "SO_EXCLUSIVEADDRUSE", fake_opt, raising=False)
    calls = []
    real = socket.socket.setsockopt

    def spy(self, level, opt, value, *rest):
        if opt == fake_opt:
            calls.append(self.getsockname() if self.fileno() != -1 else None)
            return None
        return real(self, level, opt, value, *rest)

    monkeypatch.setattr(socket.socket, "setsockopt", spy)
    return calls


def test_port_free_requests_exclusive_bind(exclusive_spy):
    doctor.port_free(0)
    assert len(exclusive_spy) == 1


def test_fixed_and_direct_listeners_are_exclusive(exclusive_spy):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as a, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as b:
        a.bind(("127.0.0.1", 0))
        b.bind(("127.0.0.1", 0))
        fixed, direct = a.getsockname()[1], b.getsockname()[1]
    r = oscio.OscReceiver(Dispatcher(), mode="fixed", listen_port=fixed, direct_port=direct, advertise=None).start()
    try:
        assert r.direct_active
        assert len(exclusive_spy) == 2  # fixed + direct
    finally:
        r.stop()


def test_fixed_port_held_by_other_app_is_left_alone():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as other:
        other.bind(("0.0.0.0", 0))
        other.settimeout(2)
        port = other.getsockname()[1]
        with pytest.raises(oscio.PortInUse):
            oscio.OscReceiver(Dispatcher(), mode="fixed", listen_port=port, direct_port=0, advertise=None).start()
        SimpleUDPClient("127.0.0.1", port).send_message("/avatar/parameters/X", 1)
        data, _ = other.recvfrom(1024)
    assert b"/avatar/parameters/X" in data
