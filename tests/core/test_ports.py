"""Port selection: the port that is tested must be the port that serves."""

import errno
import json
import socket

import pytest

from hanakura.core.net import ports
from hanakura.core.net.ports import PortUnavailableError, bind_first_free_port
from hanakura.core.net.runtime_file import read_runtime_file, remove_runtime_file, write_runtime_file


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _hold(port: int) -> socket.socket:
    s = socket.socket()
    s.bind(("127.0.0.1", port))
    s.listen()
    return s


def test_free_port_is_used():
    port = _free_port()
    sock = bind_first_free_port("127.0.0.1", port)
    try:
        assert sock.getsockname()[1] == port
    finally:
        sock.close()


def test_held_port_moves_to_next():
    port = _free_port()
    holder = _hold(port)
    try:
        sock = bind_first_free_port("127.0.0.1", port)
        assert sock.getsockname()[1] > port
        sock.close()
    finally:
        holder.close()


def test_strict_mode_does_not_move():
    port = _free_port()
    holder = _hold(port)
    try:
        with pytest.raises(PortUnavailableError, match="strict"):
            bind_first_free_port("127.0.0.1", port, strict=True)
    finally:
        holder.close()


def _taken(port: int) -> OSError:
    return OSError(errno.EADDRINUSE, f"port {port} is taken")


def test_search_has_no_attempt_limit(monkeypatch):
    # Far more taken ports than the old cap of 20.
    tried = []

    def fake_bind(host, port):
        tried.append(port)
        if port < 8000 + 500:
            raise _taken(port)
        return port

    monkeypatch.setattr(ports, "_bind", fake_bind)
    assert bind_first_free_port("127.0.0.1", 8000) == 8500
    assert tried == list(range(8000, 8501))


def test_search_wraps_around_below_the_start(monkeypatch):
    def fake_bind(host, port):
        if port >= 65000:
            raise _taken(port)
        return port

    monkeypatch.setattr(ports, "_bind", fake_bind)
    assert bind_first_free_port("127.0.0.1", 65000) == ports.LOWEST_FALLBACK_PORT


def test_every_port_taken_fails_after_trying_each_once(monkeypatch):
    tried = []

    def fake_bind(host, port):
        tried.append(port)
        raise _taken(port)

    monkeypatch.setattr(ports, "_bind", fake_bind)
    with pytest.raises(PortUnavailableError, match="No free port"):
        bind_first_free_port("127.0.0.1", 8000)
    assert sorted(tried) == list(range(ports.LOWEST_FALLBACK_PORT, ports.MAX_PORT + 1))


def test_an_error_another_port_would_not_fix_stops_the_search(monkeypatch):
    tried = []

    def fake_bind(host, port):
        tried.append(port)
        raise OSError(errno.EADDRNOTAVAIL, "address not available")

    monkeypatch.setattr(ports, "_bind", fake_bind)
    with pytest.raises(PortUnavailableError, match="Cannot bind"):
        bind_first_free_port("127.0.0.1", 8000)
    assert tried == [8000]


def test_runtime_file_matches_socket(tmp_path):
    sock = bind_first_free_port("127.0.0.1", _free_port())
    try:
        port = sock.getsockname()[1]
        write_runtime_file(tmp_path, "127.0.0.1", port, f"http://127.0.0.1:{port}")
        data = read_runtime_file(tmp_path)
        assert data["port"] == port
        assert json.loads((tmp_path / "server.json").read_text())["url"].endswith(str(port))
        remove_runtime_file(tmp_path)
        assert read_runtime_file(tmp_path) is None
    finally:
        sock.close()
