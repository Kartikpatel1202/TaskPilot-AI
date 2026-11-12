"""DNS rebinding: the safe downloader resolves once and dials exactly the validated IP; a second,
different answer can never redirect the connection to a private address."""

from __future__ import annotations

import httpcore
import pytest

from app.integrations.files.pinned_transport import PinnedNetworkBackend, PinningError


class RecordingBackend(httpcore.AsyncNetworkBackend):
    def __init__(self) -> None:
        self.dialled: list[tuple[str, int]] = []

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):  # noqa: ANN001, ANN201
        self.dialled.append((host, port))
        raise httpcore.ConnectError("test backend: no network")

    async def connect_unix_socket(self, path, timeout=None, socket_options=None):  # noqa: ANN001, ANN201
        raise httpcore.ConnectError("no")

    async def sleep(self, seconds: float) -> None:
        return None


async def test_rebinding_resolver_cannot_redirect_the_connection() -> None:
    answers = iter([["93.184.216.34"], ["127.0.0.1"]])  # first lookup public, a later one private

    async def rebinding(host: str) -> list[str]:
        return next(answers)

    inner = RecordingBackend()
    backend = PinnedNetworkBackend(resolver=rebinding, inner=inner)
    with pytest.raises(httpcore.ConnectError):
        await backend.connect_tcp("files.example.com", 443)
    assert inner.dialled == [("93.184.216.34", 443)]  # the validated IP, not the hostname
    with pytest.raises(PinningError):  # the rebinding answer is refused before any socket is opened
        await backend.connect_tcp("files.example.com", 443)
    assert inner.dialled == [("93.184.216.34", 443)]


async def test_private_and_unresolvable_hosts_are_never_dialled() -> None:
    async def private(host: str) -> list[str]:
        return ["169.254.169.254"]

    async def broken(host: str) -> list[str]:
        raise OSError("nxdomain")

    inner = RecordingBackend()
    for resolver in (private, broken):
        with pytest.raises(PinningError):
            await PinnedNetworkBackend(resolver=resolver, inner=inner).connect_tcp("x.example.com", 443)
    with pytest.raises(PinningError):
        await PinnedNetworkBackend(inner=inner).connect_tcp("10.0.0.5", 80)  # IP literal
    assert inner.dialled == []


async def test_exact_trusted_fixture_origin_is_the_only_local_exception() -> None:
    inner = RecordingBackend()
    backend = PinnedNetworkBackend(trusted_hosts=["127.0.0.1:9000"], inner=inner)
    with pytest.raises(httpcore.ConnectError):
        await backend.connect_tcp("127.0.0.1", 9000)
    with pytest.raises(PinningError):
        await backend.connect_tcp("127.0.0.1", 9001)
    assert inner.dialled == [("127.0.0.1", 9000)]
