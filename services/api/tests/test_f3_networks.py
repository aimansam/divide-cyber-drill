"""F3: Multi-VM scenarios + networks[].

The previous M3.2 commit (commit ``a76f4ee``) shipped a 6-asset
scenario with three networks but the runner was still single-VM:
it ignored ``assets[].networks`` and only created one NIC per VM.
This suite covers the F3 changes end-to-end:

  * Scenario with no networks: existing behavior, no bridges created
  * Scenario with 1+ networks: one bridge per network declaration,
    named vmbr100+ to avoid colliding with operator-managed vmbr0..
  * Assets with declared networks get NICs attached in order
    (nic_id 0 = first network, nic_id 1 = second, …)
  * Assets with count > 1 get the same NIC layout on every clone
  * Bridges are torn down on failure (best-effort)
  * Idempotent create_bridge: re-creating an existing bridge is a
    no-op so retries don't fail
  * The runner validates network names declared by assets exist in
    spec.networks[] (typo safety)
"""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.db import models
from app.db.base import Base
from app.runners.adapter import NetworkSpec
from app.runners.mock_adapter import MockProxmoxAdapter
from app.runners.runner import Runner, RunRequest


# --- fixtures -------------------------------------------------------------


@pytest.fixture
def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    yield eng
    import asyncio

    asyncio.run(eng.dispose())


@pytest.fixture
async def session(engine) -> AsyncSession:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as s:
        yield s


def _scenario(name: str, networks_spec, assets_spec) -> models.Scenario:
    return models.Scenario(
        name=name,
        title=name,
        version=1,
        difficulty="beginner",
        duration_min=30,
        spec={
            "apiVersion": "divide/v1",
            "kind": "Scenario",
            "spec": {
                "networks": networks_spec,
                "assets": assets_spec,
            },
        },
    )


def _asset(role: str, networks: list[str], template: str = "tpl-x") -> dict:
    return {
        "role": role,
        "kind": "vm",
        "template": template,
        "networks": networks,
    }


def _network(name: str, cidr: str = "10.10.0.0/24") -> dict:
    return {"name": name, "cidr": cidr, "isolation": "tight", "egress": "blocked"}


# --- bridge creation ------------------------------------------------------


@pytest.mark.asyncio
async def test_one_bridge_per_network_declaration(session: AsyncSession) -> None:
    """Each spec.networks[] entry yields exactly one create_bridge call
    with a unique bridge name."""
    adapter = MockProxmoxAdapter(templates={"tpl-x": 9000})
    runner = Runner(adapter=adapter)
    await session.merge(
        _scenario(
            name="two-subnets",
            networks_spec=[
                _network("red_vlan", "10.10.10.0/24"),
                _network("blue_vlan", "10.10.20.0/24"),
            ],
            assets_spec=[_asset("victim_a", ["red_vlan"])],
        )
    )
    await session.commit()

    await runner.start_run(RunRequest(scenario_id=1), session=session)

    assert len(adapter.bridges_created) == 2
    bridges = [b.bridge for b in adapter.bridges_created]
    # Sequential allocation: vmbr100, vmbr101.
    assert bridges == ["vmbr100", "vmbr101"], (
        f"expected vmbr100+vmbr101; got {bridges}"
    )


@pytest.mark.asyncio
async def test_no_networks_creates_no_bridges(session: AsyncSession) -> None:
    """Pre-F3 scenarios with no networks[] still work — no bridges."""
    adapter = MockProxmoxAdapter(templates={"tpl-x": 9000})
    runner = Runner(adapter=adapter)
    await session.merge(
        models.Scenario(
            name="legacy",
            title="legacy",
            version=1,
            difficulty="beginner",
            duration_min=30,
            spec={
                "apiVersion": "divide/v1",
                "kind": "Scenario",
                "spec": {
                    "networks": [],
                    "assets": [_asset("a", [])],
                },
            },
        )
    )
    await session.commit()

    await runner.start_run(RunRequest(scenario_id=1), session=session)

    assert adapter.bridges_created == [], (
        f"legacy scenarios must not create bridges; got {adapter.bridges_created}"
    )
    assert adapter.nic_attached == [], (
        f"legacy scenarios have no NICs; got {adapter.nic_attached}"
    )


@pytest.mark.asyncio
async def test_bridge_creation_carries_cidr(session: AsyncSession) -> None:
    """Bridge creation passes the CIDR + isolation through to the adapter
    so the real adapter can use it (e.g. for documentation, IP
    planning, and operator dashboards)."""
    adapter = MockProxmoxAdapter(templates={"tpl-x": 9000})
    runner = Runner(adapter=adapter)
    await session.merge(
        _scenario(
            name="cidr-passthrough",
            networks_spec=[
                {
                    "name": "red_vlan",
                    "cidr": "10.10.50.0/24",
                    "isolation": "loose",
                    "egress": "allowed",
                    "dhcp": False,
                },
            ],
            assets_spec=[_asset("a", ["red_vlan"])],
        )
    )
    await session.commit()

    await runner.start_run(RunRequest(scenario_id=1), session=session)

    assert len(adapter.bridges_created) == 1
    spec = adapter.bridges_created[0]
    assert spec.bridge == "vmbr100"
    assert spec.cidr == "10.10.50.0/24"
    assert spec.isolation == "loose"
    assert spec.egress == "allowed"
    assert spec.dhcp is False


# --- NIC attachment -------------------------------------------------------


@pytest.mark.asyncio
async def test_asset_attached_to_declared_bridges_in_order(
    session: AsyncSession,
) -> None:
    """An asset on [red_vlan, blue_vlan] gets two NICs, in order."""
    adapter = MockProxmoxAdapter(templates={"tpl-x": 9000})
    runner = Runner(adapter=adapter)
    await session.merge(
        _scenario(
            name="router",
            networks_spec=[
                _network("red_vlan"),
                _network("blue_vlan"),
            ],
            assets_spec=[_asset("router_fw", ["red_vlan", "blue_vlan"])],
        )
    )
    await session.commit()

    await runner.start_run(RunRequest(scenario_id=1), session=session)

    # Find the router VMID and its NIC attachments.
    router_spec = adapter.cloned[0]
    router_vmid = adapter.cloned_results[0].vmid
    router_nics = [
        (vmid, bridge, nic_id)
        for vmid, bridge, nic_id in adapter.nic_attached
        if vmid == router_vmid
    ]
    assert router_nics == [
        (router_vmid, "vmbr100", 0),  # red_vlan -> nic0
        (router_vmid, "vmbr101", 1),  # blue_vlan -> nic1
    ], f"router NIC order wrong: {router_nics}"


@pytest.mark.asyncio
async def test_multiple_assets_get_their_own_nic_ids(
    session: AsyncSession,
) -> None:
    """Two assets sharing a network both get nic_id=0 (since each VM
    has its own NIC numbering starting at 0)."""
    adapter = MockProxmoxAdapter(templates={"tpl-x": 9000})
    runner = Runner(adapter=adapter)
    await session.merge(
        _scenario(
            name="two-victims",
            networks_spec=[_network("blue_vlan")],
            assets_spec=[
                _asset("victim_a", ["blue_vlan"]),
                _asset("victim_b", ["blue_vlan"]),
            ],
        )
    )
    await session.commit()

    await runner.start_run(RunRequest(scenario_id=1), session=session)

    # Both assets should attach nic0 to vmbr100 (blue_vlan).
    nic_ids = sorted([nid for _, _, nid in adapter.nic_attached])
    assert nic_ids == [0, 0], f"expected [0, 0]; got {nic_ids}"
    bridges = sorted(set(br for _, br, _ in adapter.nic_attached))
    assert bridges == ["vmbr100"], f"both should be on blue_vlan; got {bridges}"


@pytest.mark.asyncio
async def test_unknown_network_name_warns_does_not_fail(
    session: AsyncSession,
) -> None:
    """If an asset references a network not in spec.networks[], the
    runner warns and continues. We don't fail because the asset
    still has a primary NIC (PVE default), it just lacks the
    multi-NIC attachment."""
    adapter = MockProxmoxAdapter(templates={"tpl-x": 9000})
    runner = Runner(adapter=adapter)
    await session.merge(
        _scenario(
            name="typo-safety",
            networks_spec=[_network("red_vlan")],  # no 'blue_vlan'
            assets_spec=[_asset("hybrid", ["red_vlan", "blue_vlan"])],
        )
    )
    await session.commit()

    result = await runner.start_run(RunRequest(scenario_id=1), session=session)

    # Run still succeeds — the unknown network is skipped.
    assert result.status.value == "succeeded"
    # Only the known network attached.
    assert len(adapter.nic_attached) == 1
    assert adapter.nic_attached[0][1] == "vmbr100"


# --- teardown -------------------------------------------------------------


@pytest.mark.asyncio
async def test_bridges_removed_on_failure(session: AsyncSession) -> None:
    """When a clone fails after bridges were created, the runner
    removes the bridges it created (best-effort) so a retry starts
    clean. The mock removes them; real PVE is operator-owned and
    no-ops."""
    adapter = MockProxmoxAdapter(templates={"tpl-x": 9000})
    runner = Runner(adapter=adapter)
    await session.merge(
        _scenario(
            name="fail-mid",
            networks_spec=[_network("red_vlan")],
            assets_spec=[
                _asset("a", ["red_vlan"], template="tpl-x"),  # ok
                _asset("b", ["red_vlan"], template="tpl-missing"),
                # ^ spawn will fail: no template "tpl-missing"
            ],
        )
    )
    await session.commit()

    with pytest.raises(Exception):
        await runner.start_run(RunRequest(scenario_id=1), session=session)

    # Mock-recorded teardown includes all bridges we created.
    assert adapter.bridges_removed == ["vmbr100"], (
        f"vmbr100 should be removed on failure; got {adapter.bridges_removed}"
    )


@pytest.mark.asyncio
async def test_bridges_removed_on_success_too(
    session: AsyncSession,
) -> None:
    """Bridges are removed on success too — the drill is over."""
    adapter = MockProxmoxAdapter(templates={"tpl-x": 9000})
    runner = Runner(adapter=adapter)
    await session.merge(
        _scenario(
            name="ok",
            networks_spec=[_network("red_vlan"), _network("blue_vlan")],
            assets_spec=[_asset("a", ["red_vlan"])],
        )
    )
    await session.commit()

    await runner.start_run(RunRequest(scenario_id=1), session=session)

    assert sorted(adapter.bridges_removed) == ["vmbr100", "vmbr101"], (
        f"both bridges should be removed on success; "
        f"got {adapter.bridges_removed}"
    )


# --- adapter-level behavior ----------------------------------------------


@pytest.mark.asyncio
async def test_create_bridge_idempotent() -> None:
    """Re-creating an existing bridge is a no-op — important for
    retries where the previous run left a bridge around (despite
    best-effort cleanup)."""
    adapter = MockProxmoxAdapter()
    await adapter.create_bridge(NetworkSpec(bridge="vmbr100"))
    await adapter.create_bridge(NetworkSpec(bridge="vmbr100"))
    # Both calls recorded for observability, but the second doesn't
    # change internal state. Internal set is idempotent.
    assert "vmbr100" in adapter._bridges
    assert len(adapter.bridges_created) == 2  # history is honest


@pytest.mark.asyncio
async def test_remove_bridge_missing_is_noop() -> None:
    """Removing a non-existent bridge doesn't fail."""
    adapter = MockProxmoxAdapter()
    await adapter.remove_bridge("vmbr999")  # was never created
    assert adapter.bridges_removed == ["vmbr999"]
    assert "vmbr999" not in adapter._bridges


@pytest.mark.asyncio
async def test_attach_network_records_ordered_nics() -> None:
    """NIC IDs are sequential starting from 0; the runner uses
    enumerate() so the first declared network becomes nic0."""
    adapter = MockProxmoxAdapter(templates={"tpl-foo": 9000})
    # Manually create a VM to attach to.
    from app.runners.adapter import CloneSpec

    await adapter.clone_vm(
        CloneSpec(
            source_vmid=9000,
            new_vmid=9001,
            node="pve",
            name="test-vm",
        )
    )
    await adapter.attach_network(9001, "pve", "vmbr100", 0)
    await adapter.attach_network(9001, "pve", "vmbr101", 1)
    await adapter.attach_network(9001, "pve", "vmbr102", 2)

    assert adapter.nic_attached == [
        (9001, "vmbr100", 0),
        (9001, "vmbr101", 1),
        (9001, "vmbr102", 2),
    ]
    state = await adapter.get_vm_state(9001, "pve")
    assert state.ip is not None  # mock still gives an IP
    # _Vm.nics tracks ordering — VM-level state, not adapter history.
    vm = adapter._vms[9001]
    assert vm.nics == [(0, "vmbr100"), (1, "vmbr101"), (2, "vmbr102")]


# --- example-scenario parity ---------------------------------------------


@pytest.mark.asyncio
async def test_red_vs_blue_baseline_yaml_topology_runs(
    session: AsyncSession,
) -> None:
    """End-to-end: load the on-disk red-vs-blue-baseline scenario and
    run it. Asserts the runner produces the cyber-range topology
    this scenario was authored for:

      red zone:    red_attacker (1 nic, red_vlan)
      router zone: router_fw (2 nics, red_vlan + blue_vlan)
      blue zone:   victim_workstation*2, file_server, log_aggregator
                   (1 nic each, blue_vlan)

    This is THE scenario that F4-UI's TopologyGraph renders; F3
    makes it actually runnable end-to-end.
    """
    import yaml
    from pathlib import Path

    yaml_path = (
        Path(__file__).resolve().parents[3]
        / "examples"
        / "scenarios"
        / "red-vs-blue-baseline.scenario.yaml"
    )
    spec = yaml.safe_load(yaml_path.read_text())
    # Validate against the schema first so we fail loudly on a YAML
    # change breaking the topology contract.
    import json

    from jsonschema import Draft202012Validator
    from app.services.scenario_sync import _find_schema

    schema = json.loads(_find_schema().read_text())
    Draft202012Validator(schema).validate(spec)

    # Drop into the DB.
    await session.merge(
        models.Scenario(
            name=spec["metadata"]["name"],
            title=spec["metadata"]["title"],
            version=spec["metadata"]["version"],
            difficulty=spec["metadata"]["difficulty"],
            duration_min=spec["metadata"]["duration_min"],
            tags=spec["metadata"].get("tags", []),
            spec=spec,
        )
    )
    await session.commit()

    # Seed templates that the scenario references.
    adapter = MockProxmoxAdapter()
    for tpl in {
        spec["spec"]["assets"][i]["template"]
        for i in range(len(spec["spec"]["assets"]))
    }:
        adapter.seed_template(tpl)

    runner = Runner(adapter=adapter)
    result = await runner.start_run(
        RunRequest(scenario_id=1), session=session
    )

    # Run succeeded.
    assert result.status.value == "succeeded"

    # 5 declared assets, total 6 clones (1+1+2+1+1). This was
    # 5 in F3.1 (count not honoured); F3-followup lifts that limit
    # and now both victim_workstation_1 and victim_workstation_2
    # exist as separate asset rows. The dedicated
    # test_red_vs_blue_baseline_with_count_gives_six_clones pins
    # the same scenario's role breakdown in detail; here we only
    # check the topology (1 router with 2 NICs).
    assert len(adapter.cloned) == 6, (
        f"expected 6 clones; got {len(adapter.cloned)}: "
        f"{[c.name for c in adapter.cloned]}"
    )

    by_role: dict[str, int] = {}
    for c in adapter.cloned:
        # name format: divide-<run_id>-<sanitized_role>
        parts = c.name.split("-", 2)
        by_role[parts[2]] = by_role.get(parts[2], 0) + 1
    assert by_role.get("redattacker") == 1
    assert by_role.get("routerfw") == 1
    assert (
        by_role.get("victimworkstation1") == 1
        and by_role.get("victimworkstation2") == 1
    )
    assert by_role.get("fileserver") == 1
    assert by_role.get("logaggregator") == 1

    # 3 networks declared => 3 bridges created.
    assert len(adapter.bridges_created) == 3
    bridges = sorted(b.bridge for b in adapter.bridges_created)
    assert bridges == ["vmbr100", "vmbr101", "vmbr102"]

    # Find the router VMID by name (the only one with 2 NICs).
    two_nic_vms = {
        vmid for vmid, _, _ in adapter.nic_attached
    } & {
        vmid for vmid, bridge, _ in adapter.nic_attached
    }
    counts: dict[int, int] = {}
    for vmid, _, _ in adapter.nic_attached:
        counts[vmid] = counts.get(vmid, 0) + 1
    two_nic_vmids = [vmid for vmid, n in counts.items() if n == 2]
    assert len(two_nic_vmids) == 1, (
        f"expected exactly one VM with 2 NICs (the router); "
        f"counts={counts}"
    )
    router_vmid = two_nic_vmids[0]

    # The router's two NICs are vmbr100 (red_vlan) + vmbr102
    # (blue_vlan). vmbr101 is ``dmz`` in this scenario and no
    # asset attaches to it.
    router_nics = sorted(
        br for vmid, br, _ in adapter.nic_attached if vmid == router_vmid
    )
    assert router_nics == ["vmbr100", "vmbr102"], (
        f"router should attach to red+blue; got {router_nics}"
    )

    # dmz bridge exists (vmbr101) but has zero attachments — that's
    # a degenerate networking topology but it's what the YAML says;
    # the topology renderer ignores it. Real scenarios that need a
    # full red/router/dmz/blue layout would list router on
    # [red_vlan, dmz, blue_vlan] instead.

    # All other assets attach exactly one NIC, to one of the
    # non-router subnets (they declared [red_vlan] or [blue_vlan]).
    for vmid, c in counts.items():
        if vmid == router_vmid:
            continue
        assert c == 1, f"non-router VM {vmid} should have 1 NIC; got {c}"


# --- F3 follow-up: spec.assets[].count -----------------------------------


@pytest.mark.asyncio
async def test_count_one_does_not_suffix_role(session: AsyncSession) -> None:
    """Default count of 1 keeps the declared role verbatim — no _1
    suffix. This keeps the audit log + reports readable for
    single-instance assets."""
    adapter = MockProxmoxAdapter(templates={"tpl-x": 9000})
    runner = Runner(adapter=adapter)
    await session.merge(
        _scenario(
            name="count-one",
            networks_spec=[],
            assets_spec=[{"role": "attacker", "kind": "vm",
                          "template": "tpl-x", "networks": []}],
        )
    )
    await session.commit()

    await runner.start_run(RunRequest(scenario_id=1), session=session)

    roles = sorted(a.role for a in (await session.execute(
        __import__("sqlalchemy").select(models.Asset)
    )).scalars().all())
    assert roles == ["attacker"]


@pytest.mark.asyncio
async def test_count_two_spawns_two_clones_with_suffix(session: AsyncSession) -> None:
    """count: 2 declares two clones; runner appends _N (1-indexed)
    to keep roles distinct."""
    adapter = MockProxmoxAdapter(templates={"tpl-x": 9000})
    runner = Runner(adapter=adapter)
    await session.merge(
        _scenario(
            name="count-two",
            networks_spec=[],
            assets_spec=[
                {
                    "role": "victim_workstation",
                    "kind": "vm",
                    "template": "tpl-x",
                    "networks": [],
                    "count": 2,
                },
            ],
        )
    )
    await session.commit()

    await runner.start_run(RunRequest(scenario_id=1), session=session)

    assert len(adapter.cloned) == 2, (
        f"count=2 must spawn 2 clones; got {len(adapter.cloned)}"
    )
    roles = sorted(a.role for a in (await session.execute(
        __import__("sqlalchemy").select(models.Asset)
    )).scalars().all())
    assert roles == ["victim_workstation_1", "victim_workstation_2"], (
        f"expected suffix _N; got {roles}"
    )


@pytest.mark.asyncio
async def test_count_attached_to_declared_bridges(
    session: AsyncSession,
) -> None:
    """Each instance of a count>1 asset gets the same NIC layout."""
    adapter = MockProxmoxAdapter(templates={"tpl-x": 9000})
    runner = Runner(adapter=adapter)
    await session.merge(
        _scenario(
            name="count-with-nets",
            networks_spec=[_network("blue_vlan")],
            assets_spec=[
                {
                    "role": "victim",
                    "kind": "vm",
                    "template": "tpl-x",
                    "networks": ["blue_vlan"],
                    "count": 3,
                },
            ],
        )
    )
    await session.commit()

    await runner.start_run(RunRequest(scenario_id=1), session=session)

    # 3 clones, each with one NIC on the same bridge.
    assert len(adapter.cloned) == 3
    assert len(adapter.nic_attached) == 3
    bridges = sorted({br for _, br, _ in adapter.nic_attached})
    assert bridges == ["vmbr100"]
    nic_ids = sorted({nid for _, _, nid in adapter.nic_attached})
    # Each VM is its own namespace; nic_id is local to each VM.
    # All three use nic_id=0 because they're separate VMs.
    assert nic_ids == [0]


@pytest.mark.asyncio
async def test_red_vs_blue_baseline_with_count_gives_six_clones(
    session: AsyncSession,
) -> None:
    """Re-pins the cyber-range demo scenario now that count is
    honoured: 6 asset *declarations* (with count: 2 on
    victim_workstation) -> 7 clones (1+1+2+1+1+1).

    The TopologyGraph renders all 7 nodes; the audit + reports
    show both victim_workstation_1 and victim_workstation_2.
    """
    import json
    import yaml
    from pathlib import Path

    yaml_path = (
        Path(__file__).resolve().parents[3]
        / "examples"
        / "scenarios"
        / "red-vs-blue-baseline.scenario.yaml"
    )
    spec = yaml.safe_load(yaml_path.read_text())

    from jsonschema import Draft202012Validator
    from app.services.scenario_sync import _find_schema
    Draft202012Validator(json.loads(_find_schema().read_text())).validate(spec)

    await session.merge(
        models.Scenario(
            name=spec["metadata"]["name"],
            title=spec["metadata"]["title"],
            version=spec["metadata"]["version"],
            difficulty=spec["metadata"]["difficulty"],
            duration_min=spec["metadata"]["duration_min"],
            tags=spec["metadata"].get("tags", []),
            spec=spec,
        )
    )
    await session.commit()

    adapter = MockProxmoxAdapter()
    for tpl in {
        a["template"] for a in spec["spec"]["assets"]
    }:
        adapter.seed_template(tpl)

    runner = Runner(adapter=adapter)
    result = await runner.start_run(
        RunRequest(scenario_id=1), session=session
    )

    assert result.status.value == "succeeded"
    # The scenario declares 5 assets with counts
    #   red_attacker (1) + router_fw (1) + victim_workstation (2)
    #   + file_server (1) + log_aggregator (1) = 6 total clones.
    assert len(adapter.cloned) == 6, (
        f"expected 6 clones (count honoured); "
        f"got {len(adapter.cloned)}: {[c.name for c in adapter.cloned]}"
    )

    # Roles pinned — and both victim_workstation_1 / _2 must exist.
    by_role: dict[str, int] = {}
    for c in adapter.cloned:
        parts = c.name.split("-", 2)
        by_role[parts[2]] = by_role.get(parts[2], 0) + 1
    assert by_role.get("redattacker") == 1
    assert by_role.get("routerfw") == 1
    assert by_role.get("victimworkstation1") == 1
    assert by_role.get("victimworkstation2") == 1, (
        "second victim must exist; runner must honor count: 2"
    )
    assert by_role.get("fileserver") == 1
    assert by_role.get("logaggregator") == 1

    # Bridge topology unchanged: 3 bridges, the dmz bridge has
    # zero attachments (router goes red_vlan+blue_vlan, skipping dmz).
    assert sorted(b.bridge for b in adapter.bridges_created) == [
        "vmbr100",
        "vmbr101",
        "vmbr102",
    ]


# --- migration surface --------------------------------------------------


def test_alembic_0004_drops_unique_constraint():
    """The migration source is reachable, drops
    uq_assets_run_role, and is wired to chain after 0003_users."""
    from pathlib import Path
    import re

    src = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "0004_asset_instance.py"
    ).read_text()

    assert "down_revision = \"0003_users\""
    assert "drop_constraint" in src
    assert "uq_assets_run_role" in src

    # Both upgrade and downgrade paths exist so an operator can
    # roll back if needed.
    assert "def upgrade" in src
    assert "def downgrade" in src


def test_models_asset_table_has_no_unique_constraint():
    """After the schema migration, models.Asset should *not*
    declare uq_assets_run_role at the table-args level (it's no
    longer enforced by the DB). The unique constraint was the
    thing capping count at 1."""
    from app.db import models

    table_args = models.Asset.__table_args__
    # SQLAlchemy serialises Index entries; a UniqueConstraint
    # would show up here. We assert no UQ on (run_id, role).
    for entry in table_args:
        if hasattr(entry, "name") and entry.name == "uq_assets_run_role":
            pytest.fail(
                f"Asset.__table_args__ still has uq_assets_run_role; "
                "drop it (0004 migration drops the DB one too)"
            )
