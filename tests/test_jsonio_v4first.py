import socket

import pytest

from lyric_agent.jsonio import create_connection_v4first


class FakeSock:
    def __init__(self, fam, fail):
        self.fam = fam
        self.fail = fail
        self.connected = None

    def settimeout(self, t):
        pass

    def connect(self, addr):
        if self.fail:
            raise OSError("unreachable")
        self.connected = addr

    def close(self):
        pass


def _patch(monkeypatch, infos, failing_fams):
    made = []

    def fake_getaddrinfo(host, port, *a, **k):
        return infos

    def fake_socket(fam, typ, proto):
        s = FakeSock(fam, fam in failing_fams)
        made.append(s)
        return s

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(socket, "socket", fake_socket)
    return made


V6 = (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2409::1", 443, 0, 0))
V4 = (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.2.3.4", 443))


def test_v4_tried_before_v6(monkeypatch):
    made = _patch(monkeypatch, [V6, V6, V4], failing_fams=set())
    sock = create_connection_v4first(("api.bilibili.com", 443), timeout=5)
    assert sock.fam == socket.AF_INET
    assert len(made) == 1


def test_falls_back_to_v6_when_v4_dead(monkeypatch):
    _patch(monkeypatch, [V6, V4], failing_fams={socket.AF_INET})
    sock = create_connection_v4first(("api.bilibili.com", 443), timeout=5)
    assert sock.fam == socket.AF_INET6


def test_all_dead_raises(monkeypatch):
    _patch(monkeypatch, [V6, V4],
           failing_fams={socket.AF_INET, socket.AF_INET6})
    with pytest.raises(OSError):
        create_connection_v4first(("api.bilibili.com", 443), timeout=5)
