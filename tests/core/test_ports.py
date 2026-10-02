"""Port selection: the port that is tested must be the port that serves."""

import json
import socket

import pytest

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


def test_all_ports_held_fails():
    port = _free_port()
    holders = []
    try:
        for p in range(port, port + 3):
            try:
                holders.append(_hold(p))
            except OSError:
                pytest.skip("neighbouring port busy")
        with pytest.raises(PortUnavailableError, match="No free port"):
            bind_first_free_port("127.0.0.1", port, attempts=3)
    finally:
        for h in holders:
            h.close()


def test_strict_mode_does_not_move():
    port = _free_port()
    holder = _hold(port)
    try:
        with pytest.raises(PortUnavailableError, match="strict"):
            bind_first_free_port("127.0.0.1", port, strict=True)
    finally:
        holder.close()


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
