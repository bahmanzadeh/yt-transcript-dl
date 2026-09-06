import socket

import pytest


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    """Block application network calls; package provisioning runs in isolated uv."""

    def blocked(*args, **kwargs):
        raise AssertionError("Network access is disabled in automated tests")

    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)


@pytest.fixture
def caption_bytes():
    return b'{"events":[{"tStartMs":0,"segs":[{"utf8":"Hello world."}]}]}'
