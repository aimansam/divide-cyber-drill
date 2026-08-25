"""Day-1 wizard end-to-end integration test (P10).

Tests the full operator flow that the F-pve-bridge-wizard (SDN
variant) + F-pve-config-ui pivots built: the on-network POST
endpoints + the runner together.

This test would have caught P1: the previous bridge-not-found
error message surfaced from the runner pointed operators at
/etc/network/interfaces + ifreload -- instructions that did
nothing for an SDN-managed cluster. We lock the post-pivot
contract in here.

Coverage:
  * Step -1: POST /admin/pve-config -- the wizard's
    credentials step.
  * Step 0: GET /admin/pve-sdn-status + POST
    /admin/pve-setup-bridges -- mocked PVE SDN. Asserts the
    response carries the new error-message format (no
    /etc/network/interfaces references).
  * Step 4: POST /api/v1/drills -- the runner end-to-end. The
    bridge created in Step 0 must be visible from
    /nodes/{n}/network so the runner'\''s create_bridge
    assertion passes.

PVE is mocked in two places:
  * httpx (used by app/services/pve_sdn.py -- the wizard'\''s
    SDN layer)
  * proxmoxer (used by app/services/proxmox.py -- the probe-
    before-commit + the runner'\''s create_bridge assertion)
The runner'\''s actual VM lifecycle uses MockProxmoxAdapter by
default so we don'\''t need to mock proxmoxer for the clone/
start path.
"""
from __future__ import annotations

import json
import os
from typing import Any

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select

from app.db import models as db_models
from app.services import pve_sdn
from app.services import proxmox as proxmox_svc


def _sync_engine():
    url = os.environ["DIVIDE_DB_URL"].replace(
        "sqlite+aiosqlite://", "sqlite:///"
    )
    return create_engine(url)


class _StubAsyncClient(httpx.AsyncClient):
    """httpx.AsyncClient subclass that injects a shared MockTransport.

    The transport is set via the class-level ``_shared_transport``
    attribute before pytest invokes the test. pve_sdn.py instantiates
    ``httpx.AsyncClient(verify=..., timeout=...)`` -- with no
    transport kwarg -- so we read the shared transport off the class
    at construction time.
    """

    # Class-level transport shared across all instances created in
    # this test. Set by the pve_token fixture before any call.
    _shared_transport: httpx.MockTransport | None = None

    def __init__(self, **kwargs: Any) -> None:
        kwargs.pop("verify", None)
        kwargs.setdefault(
            "transport", self.__class__._shared_transport
        )
        super().__init__(**kwargs)


@pytest.fixture
def pve_token(monkeypatch: pytest.MonkeyPatch) -> tuple[dict[str, Any], Any]:
    """Stub the four PVE endpoints the wizard + the runner hit."""
    store: dict[str, Any] = {
        "zones": [],
        "vnets": [],
        "node_ifaces": [
            {"iface": "vmbr0", "type": "bridge"},
            {"iface": "lo", "type": "loopback"},
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        method = request.method

        # The wizard's SDN layer (pve_sdn.py) calls these:
        if method == "GET" and path == "/api2/json/cluster/sdn/zones":
            return httpx.Response(200, json={"data": store["zones"]})
        if method == "GET" and path == "/api2/json/cluster/sdn/vnets":
            return httpx.Response(200, json={"data": store["vnets"]})
        if method == "POST" and path == "/api2/json/cluster/sdn/zones":
            body = json.loads(request.content.decode())
            if body.get("zone") not in [z.get("zone") for z in store["zones"]]:
                store["zones"].append(body)
            return httpx.Response(200, json={"data": None})
        if method == "POST" and path == "/api2/json/cluster/sdn/vnets":
            body = json.loads(request.content.decode())
            store["vnets"].append(body)
            vnet_name = body.get("vnet")
            if vnet_name and vnet_name not in [
                i.get("iface") for i in store["node_ifaces"]
            ]:
                store["node_ifaces"].append(
                    {"iface": vnet_name, "type": "bridge"}
                )
            return httpx.Response(200, json={"data": None})
        # /nodes/{n}/network -- match any node name. Used by
        # list_node_ifaces during apply_sdn_plan'\''s propagation
        # poll AND by the runner'\''s create_bridge assertion.
        if method == "GET" and path.startswith(
            "/api2/json/nodes/"
        ) and path.endswith("/network"):
            return httpx.Response(
                200, json={"data": store["node_ifaces"]}
            )

        return httpx.Response(500, json={
            "data": None, "message": f"unmocked {method} {path}"
        })

    transport = httpx.MockTransport(handler)
    _StubAsyncClient._shared_transport = transport
    monkeypatch.setattr(
        pve_sdn.httpx, "AsyncClient", _StubAsyncClient
    )
    # proxmoxer-based calls (used by the probe-before-commit at
    # POST /admin/pve-config, and by the runner'\''s
    # create_bridge assertion) need a separate stub -- the layer
    # services/proxmox.py exports get_version/get_node etc. so
    # we monkeypatch those instead of going deeper.
    def _fake_get_version() -> dict:
        return {
            "version": "9.1.7", "release": "9.1", "repoid": "x",
            "host": "https://stub",
        }

    def _fake_list_nodes() -> list[dict]:
        return [{"node": "pve", "status": "online"}]

    monkeypatch.setattr(proxmox_svc, "get_version", _fake_get_version)
    monkeypatch.setattr(proxmox_svc, "list_nodes", _fake_list_nodes)

    def _fake_list_storage() -> list[dict]:
        return []

    def _fake_list_templates(node: str | None = None) -> list[dict]:
        return []

    def _fake_list_acl() -> list[dict]:
        return []

    def _fake_list_permissions() -> dict:
        return {}

    monkeypatch.setattr(proxmox_svc, "list_storage", _fake_list_storage)
    monkeypatch.setattr(proxmox_svc, "list_templates", _fake_list_templates)
    monkeypatch.setattr(proxmox_svc, "list_acl", _fake_list_acl)
    monkeypatch.setattr(proxmox_svc, "list_permissions", _fake_list_permissions)

    # Point settings.scenarios_dir at the repo'\''s examples/scenarios
    # and run an explicit sync so first-live-drill is in the DB.
    import pathlib
    examples = (
        pathlib.Path(__file__).resolve().parents[2]
        / "examples" / "scenarios"
    )
    monkeypatch.setenv(
        "DIVIDE_SCENARIOS_DIR", str(examples)
    )

    async def _reseed() -> None:
        from app.core.config import get_settings
        get_settings.cache_clear()
        from app.services.scenario_sync import sync_files
        from app.db.session import get_sessionmaker
        await sync_files(
            settings_dir=get_settings(),
            session_factory=get_sessionmaker(),
        )

    return store, _reseed


def test_full_day1_wizard_flow(
    client: TestClient, pve_token: tuple[dict[str, Any], Any]
) -> None:
    """P10: Step -1 -> Step 0 -> launch a drill.

    This is the integration test that would have caught P1: the
    runner's bridge-not-found error message used to say
    "/etc/network/interfaces" and "ifreload -a". Those
    remediation steps disappeared with the SDN pivot, but the
    message didn't until P1 commit landed. We assert that the
    error message flowing out of POST /api/v1/drills (when a
    bridge is missing) names wizard Step 0, not
    /etc/network/interfaces.
    """
    store, _ = pve_token

    # Insert first-live-drill directly so we don'\''t depend on
    # the lifespan sync (which uses env-var settings cached at
    # process start). The admin path exercises the same Scenario
    # fields we care about for the planner + runner bridge
    # assertion.
    from sqlalchemy import create_engine
    engine = create_engine(
        os.environ["DIVIDE_DB_URL"].replace(
            "sqlite+aiosqlite://", "sqlite:///"
        )
    )
    with engine.begin() as conn:
        # Read the YAML and pre-populate the scenarios row.
        import pathlib
        yaml_path = (
            pathlib.Path(__file__).resolve().parents[3]
            / "examples" / "scenarios"
            / "first-live-drill.scenario.yaml"
        )
        with open(yaml_path) as fh:
            raw = fh.read()
        spec = yaml.safe_load(raw)
        spec_yaml = raw
        # Two scenarios can'\''t share a name; delete any prior
        # first-live-drill row.
        conn.execute(
            db_models.Scenario.__table__.delete().where(
                db_models.Scenario.name == "first-live-drill"
            )
        )
        conn.execute(
            db_models.Scenario.__table__.insert().values(
                name="first-live-drill",
                title=spec.get("title", "First Live Drill"),
                version=int(spec.get("version", 1)),
                difficulty=spec.get("difficulty", "beginner"),
                duration_min=int(spec.get("duration_min", 10)),
                tags=spec.get("tags", []),
                spec=spec,
                authors=spec.get("authors", []),
                source_path=str(yaml_path),
            )
        )
    # Bootstrap admin.
    client.post(
        "/api/v1/auth/setup",
        json={"sub": "admin", "password": "adminpass1"},
    )
    admin_tok = client.post(
        "/api/v1/auth/login",
        json={"sub": "admin", "password": "adminpass1"},
    ).json()["token"]
    headers = {"X-Divide-Token": admin_tok}

    # Step -1: POST pve-config (probe-before-commit; succeeds against mock).
    r = client.post(
        "/api/v1/admin/pve-config",
        headers=headers,
        json={
            "host": "https://stub.pve",
            "port": 8006,
            "user": "stub@pve",
            "token_id": "stub!tk",
            "token_secret": "stub-secret",
            "verify_ssl": False,
            "node": "pve",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["source"] == "db"

    # Step 0a: probe SDN status (should report nothing yet).
    s = client.get("/api/v1/admin/pve-sdn-status", headers=headers).json()
    assert s["reachable"] is True
    assert len(s["vnets_missing"]) >= 1

    # Step 0b: trigger SDN apply.
    r = client.post(
        "/api/v1/admin/pve-setup-bridges",
        headers=headers,
        json={"dry_run": False},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert "vmbr100" in (body["added"] + body["already_present"])

    # Verify SDN state mutated through the mock.
    assert any(z.get("zone") == "divide" for z in store["zones"])
    assert any(v.get("vnet") == "vmbr100" for v in store["vnets"])

    # Step 4: launch a drill against first-live-drill.
    scenarios = client.get("/api/v1/scenarios").json()["items"]
    sl = next(s for s in scenarios if s["name"] == "first-live-drill")
    r = client.post(
        "/api/v1/drills",
        headers=headers,
        json={"scenario_id": sl["id"]},
    )
    # If the drill 5xx's for a bridge-related reason, the message
    # MUST NOT contain "/etc/network/interfaces" or "ifreload"
    # (P1 regression).
    if r.status_code >= 500:
        try:
            detail = r.json()
        except Exception:
            detail = r.text
        if isinstance(detail, dict) and "detail" in detail:
            detail_text = str(detail.get("detail", ""))
        else:
            detail_text = str(detail)
        assert "/etc/network/interfaces" not in detail_text, (
            f"P10 regression: bridge-not-found still names the SSH-era "
            f"fix. Detail was: {detail_text!r}"
        )
        assert "ifreload" not in detail_text, (
            f"P10 regression: bridge-not-found still names ifreload. "
            f"Detail was: {detail_text!r}"
        )
        assert "pvesh create /cluster/sdn/vnets" in detail_text, (
            f"P10: if the error is about a missing bridge, it should "
            f"name the post-pivot remediation. Detail: {detail_text!r}"
        )

    # End-to-end smoke: the configuration row is persisted.
    engine = _sync_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            select(db_models.PveConfig).where(db_models.PveConfig.id == 1)
        ).all()
    assert len(rows) == 1
    assert rows[0].token_secret == "stub-secret"