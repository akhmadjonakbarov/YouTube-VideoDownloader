import socket

from services import network


class _Conn:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_online_when_connection_opens(monkeypatch):
    seen = {}
    monkeypatch.setattr(network.urllib.request, "getproxies", lambda: {})
    monkeypatch.setattr(network.socket, "create_connection", lambda addr, timeout: seen.setdefault("addr", addr) and _Conn())
    assert network.is_online()
    assert seen["addr"] == ("www.youtube.com", 443)


def test_offline_when_connection_fails(monkeypatch):
    def fail(addr, timeout):
        raise socket.gaierror("no network")
    monkeypatch.setattr(network.urllib.request, "getproxies", lambda: {})
    monkeypatch.setattr(network.socket, "create_connection", fail)
    assert not network.is_online()


def test_checks_proxy_when_configured(monkeypatch):
    seen = {}
    monkeypatch.setattr(network.urllib.request, "getproxies", lambda: {"https": "http://proxy.local:3128"})
    monkeypatch.setattr(network.socket, "create_connection", lambda addr, timeout: seen.setdefault("addr", addr) and _Conn())
    assert network.is_online()
    assert seen["addr"] == ("proxy.local", 3128)
