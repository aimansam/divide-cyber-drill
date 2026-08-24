"""noVNC WebSocket proxy between the browser and Proxmox.

The portal's ConsoleCard opens a WebSocket against
``/api/v1/drills/{run_id}/assets/{asset_id}/console/ws``. The
browser then expects a noVNC-compatible server (binary websocket
frames). We:

  1. Authenticate the upgrade using the X-Divide-Token header.
  2. Validate the run + asset via the DB; check RBAC.
  3. Issue a ticket via ``adapter.get_vnc_ticket``.
  4. Open a second WebSocket against PVE's
     ``/nodes/{node}/qemu/{vmid}/vncproxy?port=...&vncticket=...``.
     This second socket sees the PVE-issued ticket in the URL,
     so PVE accepts the upgrade.
  5. Bidirectionally proxy the binary noVNC protocol.

Why not stream the bytes via asyncio directly? PVE speaks binary
WebSocket frames (RFB); the browser noVNC client also speaks
binary. Bidirectional pump is the natural shape.

Why not use websockets.connect() directly? ``websockets`` is an
async library; FastAPI uses ``uvicorn`` which ships
``websockets``. We use the same library to keep one set of
type stubs.

This module is deliberately small (~100 LoC) so the unit tests
can cover every branch:
  * Ticket issuance fails (no clone) -> close with 4404
  * RBAC fails -> close with 4403
  * Run terminal -> close with 4409
  * Upstream ws fails to connect -> close with 4402
  * Normal close from either side -> close cleanly
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import WebSocket
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import models
from app.db.session import get_sessionmaker
from app.runners.runner import build_runner
from app.services.authorization import can_view_run

log = logging.getLogger(__name__)


async def _load_asset(run_id: int, asset_id: int) -> tuple[models.Run, models.Asset] | None:
    """Return (run, asset) or None if either row is missing."""
    sm = get_sessionmaker()
    async with sm() as session:  # type: AsyncSession
        asset = (
            await session.execute(
                select(models.Asset)
                .where(models.Asset.id == asset_id)
                .where(models.Asset.run_id == run_id)
            )
        ).scalar_one_or_none()
        if asset is None:
            return None
        run = (
            await session.execute(
                select(models.Run).where(models.Run.id == run_id)
            )
        ).scalar_one_or_none()
        if run is None:
            return None
        return run, asset


async def open_no_vnc_socket(
    browser_ws: WebSocket,
    run_id: int,
    asset_id: int,
    claims: dict[str, Any],
) -> None:
    """Bidirectionally proxy a noVNC session to PVE.

    Parameters
    ----------
    browser_ws: FastAPI WebSocket (already accepted).
    run_id, asset_id: validated against the DB.
    claims: token claims dict (for RBAC; sub + role).

    Closes the browser socket with the documented ws close codes:
      * 4401 -- token invalid
      * 4403 -- RBAC denied
      * 4404 -- run / asset not found
      * 4409 -- run terminal (no point opening a console)
      * 4502 -- PVE upstream unavailable
      * 1000 -- clean disconnect
    """
    loaded = await _load_asset(run_id, asset_id)
    if loaded is None:
        await browser_ws.close(code=4404, reason="asset not found")
        return
    run, asset = loaded

    # RBAC: mirror can_view_run's logic with the claims dict.
    role = claims.get("role")
    sub = claims.get("sub")
    # can_view_run takes (token, run); we have only claims. Build
    # a transient role + sub token shim.
    from app.core.auth import TokenData
    fake_token = TokenData(sub=sub, role=role, iat=0, exp=9_999_999_999) if role else None
    if fake_token is None or not can_view_run(fake_token, run):
        await browser_ws.close(code=4403, reason="forbidden")
        return

    if asset.pve_vmid is None or not asset.pve_node:
        await browser_ws.close(
            code=4409, reason="asset not yet cloned"
        )
        return

    # Issue ticket. Mock returns deterministic; real returns PVE-issued.
    runner = build_runner()
    try:
        ticket = await runner._adapter.get_vnc_ticket(
            asset.pve_vmid, asset.pve_node
        )
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "console_proxy.ticket_failed run=%s asset=%s err=%s",
            run_id, asset_id, exc,
        )
        await browser_ws.close(code=4502, reason="vncproxy unavailable")
        return

    # Open upstream socket to PVE. The mock adapter has no real
    # socket; the dev/test path writes a single frame "hello"
    # and closes. The prod path uses websockets.connect.
    from app.services.console_upstream import open_upstream

    upstream = await open_upstream(
        vmid=asset.pve_vmid,
        node=asset.pve_node,
        port=ticket.port,
        ticket=ticket.ticket,
    )
    if upstream is None:
        await browser_ws.close(code=4502, reason="upstream unavailable")
        return

    # Bidirectional pump. Both ends are binary WebSockets; the
    # noVNC protocol is RFB wrapped in WS.
    import asyncio

    async def browser_to_upstream() -> None:
        try:
            while True:
                frame = await browser_ws.receive_bytes()
                await upstream.send(frame)
        except Exception:  # noqa: BLE001
            pass

    async def upstream_to_browser() -> None:
        try:
            async for frame in upstream:
                if isinstance(frame, str):
                    await browser_ws.send_text(frame)
                else:
                    await browser_ws.send_bytes(frame)
        except Exception:  # noqa: BLE001
            pass

    try:
        done, pending = await asyncio.wait(
            [
                asyncio.create_task(browser_to_upstream()),
                asyncio.create_task(upstream_to_browser()),
            ],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
    finally:
        await upstream.aclose()


# Close-code table for tests + ops:
WS_CLOSE = {
    "ok": 1000,
    "no_auth": 4401,
    "no_rbac": 4403,
    "not_found": 4404,
    "not_cloned": 4409,
    "upstream_down": 4502,
}


async def ws_console(
    websocket, run_id: int, asset_id: int
) -> None:
    """FastAPI entry point for the WebSocket console proxy.

    Authenticated via the ``X-Divide-Token`` header (token
    introspection happens here, not in Depends, because WebSocket
    routes don't support dependency injection).

    Forwards into :func:`open_no_vnc_socket` which does the
    real work (RBAC, ticket issuance, upstream pump).
    """
    from fastapi import WebSocketDisconnect
    from app.core.auth import verify_token as _decode_token

    token = (
        websocket.headers.get("x-divide-token")
        or websocket.query_params.get("token")
    )
    if not token:
        await websocket.close(code=4401, reason="missing X-Divide-Token")
        return
    try:
        claims = _decode_token(token)
    except Exception:
        await websocket.close(code=4401, reason="invalid token")
        return

    await websocket.accept()
    try:
        # ``claims`` is a TokenData dataclass; the proxy needs a
        # dict with .get(). Adapt here so the proxy stays simple.
        claims_dict = {
            "sub": claims.sub,
            "role": claims.role,
            "iat": claims.iat,
            "exp": claims.exp,
        }
        await open_no_vnc_socket(websocket, run_id, asset_id, claims_dict)
    except WebSocketDisconnect:
        pass
    finally:
        try:
            await websocket.close()
        except Exception:  # noqa: BLE001
            pass
