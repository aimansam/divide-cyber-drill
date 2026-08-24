"""PVE noVNC upstream socket.

The :func:`open_upstream` function delegates to either a real
PVE WebSocket or a local mock, depending on whether the
configured adapter is ``RealProxmoxAdapter`` or
``MockProxmoxAdapter``.

Real path: ``websockets.connect(...)`` against
``wss://<pve-host>:8006/api2/json/nodes/{n}/qemu/{v}/vncproxy?port=...&vncticket=...``

Mock path: opens a tiny in-process WebSocket server (single
client, single frame "MOCK-TICKET-OK", then close) so the
end-to-end tests can prove the proxy plumbing without a
real PVE.

Why we always go through this module (rather than letting
``console_proxy`` call ``websockets.connect`` directly):
  * Centralises the URL format so dev/prod use the same path.
  * Makes it trivial to record-only or null-routing in tests.
  * Centralises the close-code mapping for the tests.
"""
from __future__ import annotations

import logging
from typing import Any, Protocol

log = logging.getLogger(__name__)


class UpstreamSocket(Protocol):
    """Narrow protocol for the upstream WebSocket.

    We only need ``send(bytes)`` + iteration over binary/text
    frames + ``aclose``. The ``websockets`` library
    implements all of this; the test mock implements just
    enough to satisfy the proxy.
    """

    async def send(self, payload: bytes) -> None: ...
    def __aiter__(self) -> Any: ...
    async def aclose(self) -> None: ...


async def open_upstream(
    *, vmid: int, node: str, port: int, ticket: str
) -> UpstreamSocket | None:
    """Open a WebSocket to PVE's VNC proxy.

    Returns ``None`` on connection failure (so the caller can
    surface 4502 to the browser). The mock path returns an
    ``InMemorySocket`` that hand-feeds a single frame and
    closes, which is what the proxy tests assert against.
    """
    from app.runners.runner import _default_adapter

    adapter = _default_adapter()
    cls = type(adapter).__name__

    if cls == "MockProxmoxAdapter":
        return _open_mock_upstream(vmid, node, port, ticket)

    return await _open_real_upstream(adapter, vmid, node, port, ticket)


async def _open_real_upstream(adapter, vmid, node, port, ticket):
    """Open a WebSocket against the real PVE noVNC endpoint.

    Constructs the URL from the adapter's settings (host,
    port, ssl). The ticket + port go in the query string;
    PVE accepts this exact shape per the API docs.
    """
    try:
        import websockets  # type: ignore
    except ImportError:
        log.error(
            "console_upstream: 'websockets' library not installed; "
            "add it to requirements.txt (F4 plan)."
        )
        return None

    p = adapter._host  # private; OK for our internal use
    # PVE noVNC websocket URL format:
    ws_scheme = "wss" if getattr(adapter, "_verify_ssl", True) else "ws"
    ws_port = getattr(adapter, "_port", 8006)
    url = (
        f"{ws_scheme}://{p}:{ws_port}/api2/json/nodes/{node}/qemu/"
        f"{vmid}/vncproxy?port={port}&vncticket={ticket}"
    )
    try:
        return await websockets.connect(
            url,
            ssl=getattr(adapter, "_verify_ssl", True),
            ping_interval=None,
            ping_timeout=None,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "console_upstream.connect_failed url=%s err=%s", url, exc
        )
        return None


class InMemorySocket:
    """Tiny in-memory socket for the mock path.

    Used by the test suite; the production path uses
    ``websockets.connect``. Both implement the upstream
    protocol so the proxy doesn't care which one is in use.

    Behaviour:
      * Iterating yields one binary frame ``b"MOCK-FRAME"``
        then raises ``StopAsyncIteration``.
      * ``send`` records bytes in ``sent`` for assertions.
      * ``aclose`` sets ``closed = True``.
    """

    def __init__(self, vmid: int, node: str, port: int, ticket: str) -> None:
        self.vmid = vmid
        self.node = node
        self.port = port
        self.ticket = ticket
        self.sent: list[bytes] = []
        self.closed = False
        self._yielded = False

    async def send(self, payload: bytes) -> None:
        self.sent.append(payload)

    def __aiter__(self):
        async def gen():
            if not self._yielded:
                self._yielded = True
                yield b"MOCK-FRAME-OK"
        return gen()

    async def aclose(self) -> None:
        self.closed = True


async def _open_mock_upstream(vmid, node, port, ticket):
    return InMemorySocket(vmid, node, port, ticket)
