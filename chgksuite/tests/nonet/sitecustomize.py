"""Imported at startup by every Python the tests run, including the
``python -m chgksuite`` subprocesses, because conftest puts this directory on
PYTHONPATH. It makes any network call fail at once instead of waiting on a
host that may not answer."""

import socket


def _no_network(*args, **kwargs):
    raise OSError("network access is disabled in tests")


socket.socket.connect = _no_network
socket.socket.connect_ex = _no_network
socket.getaddrinfo = _no_network
socket.create_connection = _no_network
