"""PVE Software-Defined Networking (SDN) bridge provisioning service.

The F3 runner auto-allocates ``vmbr100``, ``vmbr101``, ... per scenario
``spec.networks[]`` declaration and ``RealProxmoxAdapter.create_bridge``
asserts each one already exists on the PVE node.

PVE has had no public API for *creating* Linux bridges historically --
they live in ``/etc/network/interfaces`` (or ``/etc/network/interfaces.d/``)
and are activated by ``ifreload -a``. That requires SSH + sudo on the
PVE host, which we don't want for the day-1 web wizard.

The clean alternative is **PVE's Software-Defined Networking (SDN) stack**
(fully supported since PVE 8.1, default-installed on PVE 9+). It exposes
three pure-API endpoints that produce exactly the same outcome:

  * ``POST /cluster/sdn/zones``   -- create a Simple zone.
  * ``POST /cluster/sdn/vnets``   -- create a VNet (one per F3 bridge).
                                     Each VNet appears as a Linux bridge
                                     on every node in the cluster after
                                     the cluster-wide SDN reload.
  * ``DELETE /cluster/sdn/{vnets,zones}/...`` -- rollback path.

After the POSTs, PVE automatically propagates the new bridges to each
node within a few seconds (we re-poll ``/nodes/{n}/network`` to confirm).
No ifreload, no SSH, no host shell access.

Permissions required on the PVE token:
    * ``SDN.Audit`` -- already granted to ``PVEAuditor``.
    * ``SDN.Allocate`` -- NOT in ``PVEAuditor``; required for the POSTs.
      The wizard surfaces the literal PVE error plus a ``pveum aclmod``
      hint when this is missing.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import httpx
import structlog

from app.services.pve_bridges import (
    BRIDGE_START,
    ApplyResult,
    BridgePlan,
    BridgeSpec,
)

log = structlog.get_logger()

# --- constants ------------------------------------------------------------

#: Name of the SDN zone div:ide owns. Single zone for all VNet bridges;
#: one per div:ide deployment. Operators can rename later via the
#: admin UI if they need a multi-tenant layout.
DEFAULT_ZONE: str = "divide"

#: Seconds to wait for SDN propagation after the create POSTs. PVE's
#: controller pushes the new VNet bridges to each node within ~1-3s
#: in practice; we poll every ``PROBE_INTERVAL_S`` until every expected
#: bridge appears on ``/nodes/{node}/network`` or the timeout elapses.
PROPAGATE_TIMEOUT_S: float = 15.0
PROBE_INTERVAL_S: float = 1.0


# --- exceptions -----------------------------------------------------------


class SdnError(Exception):
    """Generic SDN operation failure. Surfaces PVE's error verbatim.

    The router maps this to HTTP 502 (PVE rejected the request).
    """


class SdnPermissionError(SdnError):
    """PVE returned 401/403 for an SDN endpoint.

    Carries the literal PVE message plus a copy-pasteable ``pveum`` hint
    so the wizard can render a clear remediation step. The router maps
    this to HTTP 403.
    """

    def __init__(
        self,
        message: str,
        *,
        pve_path: str,
        required_role: str,
        pveum_hint: str,
    ) -> None:
        super().__init__(message)
        self.pve_path = pve_path
        self.required_role = required_role
        self.pveum_hint = pveum_hint


# --- data shapes ----------------------------------------------------------


@dataclass(frozen=True)
class SdnAuth:
    """Credentials for talking to PVE.

    Matches ``PveConfig.to_public_dict()`` plus the PVE token secret.
    The wizard Step0 calls ``get_active_auth()`` to construct this from
    the DB overlay or env fallback.
    """

    base_url: str
    token_id: str
    token_secret: str
    verify_ssl: bool
    user: str
    node: str


@dataclass(frozen=True)
class SdnPlanResult:
    """Internal -- what ``apply_sdn_plan`` actually did."""

    zone_created: bool
    vnets_created: list[str]
    vnets_already_present: list[str]
    propagate_ok: bool
    propagation_wait_s: float
    raw_responses: list[dict[str, Any]] = field(default_factory=list)


# --- helpers --------------------------------------------------------------


def _pveum_aclmod_hint(*, user: str, role: str, path: str) -> str:
    """Render a copy-pasteable shell line for the operator."""
    return f"pveum aclmod {user} -role {role} -path {path}"


def _auth_headers(token_id: str, token_secret: str) -> dict[str, str]:
    return {"Authorization": f"PVEAPIToken={token_id}={token_secret}"}


def _normalize_base_url(host: str, port: int) -> str:
    """Strip trailing slash, ensure scheme + port. PVE wants both.

    Accepts:
      * "https://192.168.0.10"   + 8006 -> "https://192.168.0.10:8006"
      * "192.168.0.10:8006"      + 8006 -> "https://192.168.0.10:8006"
      * "https://pve.example"    + 443  -> "https://pve.example"
    """
    h = (host or "").strip().rstrip("/")
    if "://" not in h:
        h = f"https://{h}"
    # If user already included :port, leave it alone.
    if ":" not in h.split("//", 1)[1]:
        if port != 443:
            h = f"{h}:{port}"
    return h


def get_active_auth(*, node: str | None = None) -> SdnAuth:
    """Build an ``SdnAuth`` from the current PVE overlay or env fallback.

    The DB overlay takes precedence (so the wizard's POST to
    ``/admin/pve-config`` flows through immediately); if no row exists,
    we read from ``settings.proxmox``.

    Raises ``SdnError`` with a clear message if anything is missing --
    the wizard surfaces this directly so the operator knows to go back
    to Step -1.
    """
    from app.core.config import settings
    from app.services.proxmox import _DB_OVERLAY

    if _DB_OVERLAY is not None:
        host = (_DB_OVERLAY.get("host") or "").strip()
        port = _DB_OVERLAY.get("port") or 8006
        user = (_DB_OVERLAY.get("user") or "").strip()
        token_id = (_DB_OVERLAY.get("token_id") or "").strip()
        token_secret = _DB_OVERLAY.get("token_secret") or ""
        verify_ssl = bool(_DB_OVERLAY.get("verify_ssl", False))
        overlay_node = (_DB_OVERLAY.get("node") or "").strip()
    else:
        cfg = settings.proxmox
        host = (cfg.host or "").strip()
        port = cfg.port
        user = (cfg.user or "").strip()
        token_id = (cfg.token_id or "").strip()
        token_secret = (
            cfg.token_secret.get_secret_value() if cfg.token_secret else ""
        )
        verify_ssl = cfg.verify_ssl
        overlay_node = (cfg.node or "").strip()

    if not host:
        raise SdnError(
            "PVE host is not configured. Complete wizard Step -1 "
            "(PVE credentials) first, or set PROXMOX_HOST in deploy/.env."
        )
    if not user:
        raise SdnError(
            "PVE user is not configured. Set PROXMOX_USER in deploy/.env "
            "or re-enter in the wizard."
        )
    if not token_id or not token_secret:
        raise SdnError(
            "PVE token_id and token_secret are required. "
            "Set PROXMOX_TOKEN_ID + PROXMOX_TOKEN_SECRET in deploy/.env "
            "or re-enter in the wizard."
        )

    effective_node = (node or overlay_node or "pve").strip()
    base_url = _normalize_base_url(host, int(port))
    return SdnAuth(
        base_url=base_url,
        token_id=token_id,
        token_secret=token_secret,
        verify_ssl=verify_ssl,
        user=user,
        node=effective_node,
    )


# --- low-level API wrappers ------------------------------------------------


async def _request(
    method: str,
    url: str,
    *,
    auth: SdnAuth,
    json_body: dict[str, Any] | None = None,
    timeout_s: float = 10.0,
) -> Any:
    """Issue a single PVE API call and unwrap ``{"data": ...}``.

    Maps 401/403 to ``SdnPermissionError`` carrying the literal PVE
    message + a ``pveum`` hint. Other HTTP failures surface as
    ``SdnError``. Network errors are re-raised as ``SdnError``.
    """
    headers = _auth_headers(auth.token_id, auth.token_secret)
    try:
        async with httpx.AsyncClient(
            verify=auth.verify_ssl, timeout=timeout_s
        ) as client:
            r = await client.request(method, url, headers=headers, json=json_body)
    except httpx.HTTPError as exc:
        raise SdnError(f"PVE request failed: {exc}") from exc

    if r.status_code in (401, 403):
        try:
            payload = r.json()
            msg = payload.get("message") or payload.get("errors") or r.text
        except Exception:  # noqa: BLE001
            msg = r.text or f"HTTP {r.status_code}"
        role = "SDN.Allocate"
        path = "/sdn"
        if "SDN.Allocate" in msg:
            role = "SDN.Allocate"
        elif "Sys.Audit" in msg:
            role = "Sys.Audit"
            path = "/"
        elif "VM.Audit" in msg:
            role = "VM.Audit"
            path = "/vms"
        raise SdnPermissionError(
            msg.strip(),
            pve_path=path,
            required_role=role,
            pveum_hint=_pveum_aclmod_hint(
                user=auth.user, role=role, path=path
            ),
        )
    if r.status_code >= 400:
        try:
            payload = r.json()
        except Exception:  # noqa: BLE001
            payload = None
        msg = ""
        if isinstance(payload, dict):
            # PVE's API errors carry two fields:
            #   - "message": human summary ("Parameter verification failed.")
            #   - "errors":  dict of {field: reason} (e.g. {"tag": "...", "bridge": "..."})
            # The 1-line "message" is too vague to debug; concatenate the
            # field-level reasons so the operator sees exactly which
            # field is wrong (PVE 9.x changed Simple-zone + VNet
            # payloads; this matters more than ever).
            base_msg = (payload.get("message") or "").strip()
            errs = payload.get("errors")
            if isinstance(errs, dict) and errs:
                rendered = "; ".join(
                    f"{k}: {v}" for k, v in errs.items() if v
                )
                msg = f"{base_msg} ({rendered})" if base_msg else rendered
            else:
                msg = base_msg or r.text or f"HTTP {r.status_code}"
        else:
            msg = r.text or f"HTTP {r.status_code}"
        raise SdnError(f"PVE {method} {url} failed: {msg}".strip())

    try:
        payload = r.json()
    except Exception:  # noqa: BLE001
        return None
    return payload.get("data")


async def list_zones(auth: SdnAuth) -> list[dict[str, Any]]:
    """Return all SDN zones on the cluster."""
    url = f"{auth.base_url}/api2/json/cluster/sdn/zones"
    data = await _request("GET", url, auth=auth)
    return list(data or [])


async def list_vnets(auth: SdnAuth) -> list[dict[str, Any]]:
    """Return all SDN Vnets on the cluster."""
    url = f"{auth.base_url}/api2/json/cluster/sdn/vnets"
    data = await _request("GET", url, auth=auth)
    return list(data or [])


async def list_node_ifaces(auth: SdnAuth) -> list[dict[str, Any]]:
    """Return every iface on ``auth.node``. Used to verify SDN propagation."""
    url = f"{auth.base_url}/api2/json/nodes/{auth.node}/network"
    data = await _request("GET", url, auth=auth)
    return list(data or [])


async def create_zone(
    auth: SdnAuth,
    *,
    zone: str = DEFAULT_ZONE,
) -> None:
    """Create the div:ide SDN zone if it doesn't already exist.

    Idempotent: PVE returns 500 with a "Zone already exists" message
    on duplicate POSTs; we treat that as a no-op so apply_sdn_plan can
    safely re-run.

    Note (PVE 9.x compatibility): PVE 9 rejected several fields that
    PVE 8 accepted on Simple zones. We now send only the minimum:
        zone + type=simple + mtu=1500

    Specifically removed vs. PVE 8:
      * ``bridge`` -- PVE 9 returns "unexpected property 'bridge'"
      * ``dhcp: "none"`` -- PVE 9 only enumerates 'dnsmasq', so the
        "no DHCP" semantic must be expressed by omitting the field.
    """
    url = f"{auth.base_url}/api2/json/cluster/sdn/zones"
    body = {
        "zone": zone,
        "type": "simple",
        "mtu": 1500,
    }
    try:
        await _request("POST", url, auth=auth, json_body=body)
    except SdnError as exc:
        msg = str(exc).lower()
        if "already exists" in msg:
            log.info("pve_sdn.zone_already_present", zone=zone)
            return
        raise


async def delete_zone(auth: SdnAuth, *, zone: str = DEFAULT_ZONE) -> None:
    """Drop the SDN zone (and with it all its Vnets). Idempotent."""
    url = f"{auth.base_url}/api2/json/cluster/sdn/zones/{zone}"
    try:
        await _request("DELETE", url, auth=auth)
    except SdnError as exc:
        msg = str(exc).lower()
        if "not found" in msg or "does not exist" in msg:
            return
        raise


async def create_vnet(
    auth: SdnAuth,
    *,
    vnet: str,
    zone: str = DEFAULT_ZONE,
) -> None:
    """Create one SDN VNet (== one Linux bridge on the node).

    Note (PVE 9.x compatibility): PVE 9 changed the VNet API:
      * ``tag: -1`` (the PVE 8 "no VLAN tag" sentinel) is rejected
        with ``value must have a minimum value of 1``.
      * ``tag: N`` for any N >= 1 is rejected with
        ``vlan tag is not allowed on simple zone`` because Simple
        zones don't support VLAN tagging.
      The only payload PVE 9 accepts is {vnet, zone} with no tag.
    """
    url = f"{auth.base_url}/api2/json/cluster/sdn/vnets"
    body = {
        "vnet": vnet,
        "zone": zone,
    }
    try:
        await _request("POST", url, auth=auth, json_body=body)
    except SdnError as exc:
        msg = str(exc).lower()
        if "already exists" in msg:
            return
        raise


async def delete_vnet(auth: SdnAuth, *, vnet: str) -> None:
    """Drop one VNet. Idempotent."""
    url = f"{auth.base_url}/api2/json/cluster/sdn/vnets/{vnet}"
    try:
        await _request("DELETE", url, auth=auth)
    except SdnError as exc:
        msg = str(exc).lower()
        if "not found" in msg or "does not exist" in msg:
            return
        raise


# --- apply ----------------------------------------------------------------


async def apply_sdn_plan(
    plan: BridgePlan,
    *,
    auth: SdnAuth,
    dry_run: bool = False,
) -> SdnPlanResult:
    """Drive the PVE SDN controller to realize the plan on the cluster.

    Steps:
      1. Idempotently create the ``divide`` Simple zone.
      2. For each bridge in the plan, create a VNet named after it.
      3. Poll ``/nodes/{node}/network`` until every expected bridge
         appears (or ``PROPAGATE_TIMEOUT_S`` elapses).

    Returns an ``SdnPlanResult`` for the router to flatten. Raises
    ``SdnPermissionError`` if the token lacks ``SDN.Allocate``.
    """
    if plan.conflicts:
        from app.services.pve_bridges import BridgePlanError

        raise BridgePlanError(
            "refusing to apply: bridge plan has conflicts: "
            + "; ".join(plan.conflicts)
        )

    raw: list[dict[str, Any]] = []

    if dry_run:
        return SdnPlanResult(
            zone_created=False,
            vnets_created=[],
            vnets_already_present=[b.name for b in plan.bridges],
            propagate_ok=True,
            propagation_wait_s=0.0,
            raw_responses=[
                {
                    "would_create_zone": DEFAULT_ZONE,
                    "would_create_vnets": [b.name for b in plan.bridges],
                }
            ],
        )

    # Step 1: zone. Idempotent.
    existing_zones = {z.get("zone") for z in await list_zones(auth)}
    zone_created = DEFAULT_ZONE not in existing_zones
    if zone_created:
        await create_zone(auth, zone=DEFAULT_ZONE)
        raw.append({"step": "create_zone", "zone": DEFAULT_ZONE, "ok": True})
        log.info("pve_sdn.zone_created", zone=DEFAULT_ZONE)

    # Step 2: vnets.
    existing_vnets = {v.get("vnet") for v in await list_vnets(auth)}
    vnets_created: list[str] = []
    vnets_already_present: list[str] = []
    for spec in plan.bridges:
        if spec.name in existing_vnets:
            vnets_already_present.append(spec.name)
            continue
        await create_vnet(auth, vnet=spec.name, zone=DEFAULT_ZONE)
        vnets_created.append(spec.name)
        raw.append({"step": "create_vnet", "vnet": spec.name, "ok": True})
        log.info("pve_sdn.vnet_created", vnet=spec.name)

    # Step 3: poll for propagation.
    expected = {b.name for b in plan.bridges}
    elapsed = 0.0
    propagate_ok = False
    while elapsed < PROPAGATE_TIMEOUT_S:
        ifaces = await list_node_ifaces(auth)
        present = {
            i.get("iface")
            for i in ifaces
            if i.get("iface") and i.get("type", "").lower() in ("bridge", "vlan")
        }
        if expected.issubset(present):
            propagate_ok = True
            break
        await asyncio.sleep(PROBE_INTERVAL_S)
        elapsed += PROBE_INTERVAL_S
    log.info(
        "pve_sdn.propagate",
        expected=sorted(expected),
        elapsed_s=elapsed,
        ok=propagate_ok,
    )

    return SdnPlanResult(
        zone_created=zone_created,
        vnets_created=vnets_created,
        vnets_already_present=vnets_already_present,
        propagate_ok=propagate_ok,
        propagation_wait_s=elapsed,
        raw_responses=raw,
    )


def to_apply_result(
    plan: BridgePlan, sdn: SdnPlanResult
) -> ApplyResult:
    """Flatten ``SdnPlanResult`` into the public ``ApplyResult`` shape.

    The runner consumes ``ApplyResult``; keeping the shape stable means
    no caller changes downstream.
    """
    return ApplyResult(
        added=sdn.vnets_created,
        already_present=sdn.vnets_already_present,
        reload_ok=sdn.propagate_ok,
        reload_method=(
            "sdn" if (sdn.zone_created or sdn.vnets_created) else "sdn-noop"
        ),
        verify_ok=sdn.propagate_ok,
        config_path=f"/sdn/zones/{DEFAULT_ZONE}",
    )


# --- info ------------------------------------------------------------------


@dataclass(frozen=True)
class SdnReadiness:
    """What ``GET /admin/pve-sdn-status`` returns.

    The wizard uses this for the pre-flight banner ("your token has the
    right perms" vs "you'll need SDN.Allocate").
    """

    reachable: bool
    zone_present: bool
    zone_name: str
    vnets_present: list[str]
    vnets_missing: list[str]
    error: str | None = None
    pveum_hint: str | None = None
    required_role: str | None = None


async def read_sdn_state(
    *, auth: SdnAuth, expected_vnets: list[str]
) -> SdnReadiness:
    """Probe PVE and report what's there vs what's missing.

    Distinguishes 401/403 (permission) from other errors so the wizard
    can render the right remediation hint.
    """
    try:
        zones = await list_zones(auth)
        vnets = await list_vnets(auth)
    except SdnPermissionError as exc:
        return SdnReadiness(
            reachable=True,
            zone_present=False,
            zone_name=DEFAULT_ZONE,
            vnets_present=[],
            vnets_missing=list(expected_vnets),
            error=str(exc),
            pveum_hint=exc.pveum_hint,
            required_role=exc.required_role,
        )
    except SdnError as exc:
        return SdnReadiness(
            reachable=False,
            zone_present=False,
            zone_name=DEFAULT_ZONE,
            vnets_present=[],
            vnets_missing=list(expected_vnets),
            error=str(exc),
        )

    zone_present = any(z.get("zone") == DEFAULT_ZONE for z in zones)
    present = {v.get("vnet") for v in vnets}
    missing = [n for n in expected_vnets if n not in present]
    return SdnReadiness(
        reachable=True,
        zone_present=zone_present,
        zone_name=DEFAULT_ZONE,
        vnets_present=sorted(n for n in present if n),
        vnets_missing=missing,
        error=None,
    )


__all__ = [
    "DEFAULT_ZONE",
    "PROPAGATE_TIMEOUT_S",
    "PROBE_INTERVAL_S",
    "BRIDGE_START",
    "SdnAuth",
    "SdnError",
    "SdnPermissionError",
    "SdnPlanResult",
    "SdnReadiness",
    "apply_sdn_plan",
    "create_vnet",
    "create_zone",
    "delete_vnet",
    "delete_zone",
    "get_active_auth",
    "list_node_ifaces",
    "list_vnets",
    "list_zones",
    "read_sdn_state",
    "to_apply_result",
]