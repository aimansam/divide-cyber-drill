"""Tests for the red-vs-blue-baseline demo scenario (F4-UI demo).

The demo scenario exists to populate the TopologyGraph view with
real assets across all three zones (red / router / blue). These
tests pin that the scenario file:
  * parses as YAML
  * validates against the divide/v1 schema
  * declares at least 4 assets
  * covers all three zone roles (red, router, blue)
  * declares at least 3 networks so the topology diagram has
    something to lay out
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
SCENARIO_PATH = (
    REPO / "examples" / "scenarios" / "red-vs-blue-baseline.scenario.yaml"
)


def _load() -> dict:
    return yaml.safe_load(SCENARIO_PATH.read_text(encoding="utf-8"))


# ---------- File shape --------------------------------------------------


def test_demo_scenario_file_exists():
    assert SCENARIO_PATH.is_file(), (
        f"Demo scenario missing: {SCENARIO_PATH}. Run git status "
        "to confirm it was committed."
    )


def test_demo_scenario_parses_as_yaml():
    data = _load()
    assert isinstance(data, dict)
    assert data.get("apiVersion") == "divide/v1"
    assert data.get("kind") == "Scenario"


def test_demo_scenario_metadata_block():
    data = _load()
    md = data["metadata"]
    assert md["name"] == "red-vs-blue-baseline"
    assert "title" in md
    assert "version" in md and md["version"] >= 1
    assert "difficulty" in md
    assert "tags" in md and isinstance(md["tags"], list)
    assert len(md["tags"]) > 0
    # The 'topology-demo' tag is what marks this as the F4-UI demo.
    assert "topology-demo" in md["tags"], (
        "Demo scenario must self-identify with a 'topology-demo' tag"
    )


def test_demo_scenario_validates_against_schema():
    """Round-trip through the divide/v1 schema validator."""
    import os
    import subprocess
    import sys

    env = {"PYTHONPATH": str(REPO / "services" / "api")}
    r = subprocess.run(
        [sys.executable, "-m", "tools.validate_scenario", str(SCENARIO_PATH)],
        capture_output=True,
        text=True,
        env={**env, **os.environ},
        cwd=str(REPO),
    )
    assert r.returncode == 0, (
        f"schema validation failed:\n{r.stdout}\n{r.stderr}"
    )


# ---------- Topology shape ----------------------------------------------


def test_demo_scenario_has_at_least_four_assets():
    """The TopologyGraph only looks meaningful with 4+ assets."""
    data = _load()
    assets = data["spec"]["assets"]
    assert len(assets) >= 4, (
        f"Demo scenario needs >= 4 assets to fill the topology "
        f"graph; got {len(assets)}"
    )


def test_demo_scenario_covers_all_three_zones():
    """Asset roles must cover red (attacker), router (gateway), and
    blue (victim / defender / log-aggregator)."""
    data = _load()
    roles = [a["role"].lower() for a in data["spec"]["assets"]]
    assert any("red" in r or "attacker" in r for r in roles), (
        f"Demo scenario must include a red-zone asset; got {roles}"
    )
    assert any(
        "router" in r or "firewall" in r or "gw" in r for r in roles
    ), f"Demo scenario must include a router asset; got {roles}"
    assert any(
        "victim" in r
        or "blue" in r
        or "defender" in r
        or "log" in r
        or "server" in r
        for r in roles
    ), f"Demo scenario must include a blue-zone asset; got {roles}"


def test_demo_scenario_has_three_networks():
    """One network per zone gives the topology diagram something
    to lay out."""
    data = _load()
    networks = data["spec"].get("networks", [])
    assert len(networks) >= 3, (
        f"Demo scenario must declare >= 3 networks (one per zone); "
        f"got {len(networks)}"
    )


def test_demo_scenario_telemetry_includes_minio():
    """The telemetry sinks must include minio so the demo
    generates an actual report on completion."""
    data = _load()
    sinks = data["spec"].get("telemetry", {}).get("sinks", [])
    types = [s.get("type") for s in sinks]
    assert "minio" in types, (
        f"Demo scenario telemetry must include a minio sink; got {types}"
    )


def test_demo_scenario_objectives_have_red_and_blue():
    """A 'red vs blue' scenario must have objectives for both sides."""
    data = _load()
    objectives = data["spec"].get("objectives", {})
    assert "red" in objectives and len(objectives["red"]) > 0
    assert "blue" in objectives and len(objectives["blue"]) > 0


def test_demo_scenario_scoring_has_red_and_blue():
    data = _load()
    scoring = data["spec"].get("scoring", {})
    assert "red" in scoring
    assert "blue" in scoring


def test_demo_scenario_win_conditions_for_both_sides():
    data = _load()
    win = data["spec"].get("win_conditions", {})
    assert "red" in win and len(win["red"]) > 0
    assert "blue" in win and len(win["blue"]) > 0


# ---------- TopologyGraph classifier compatibility ---------------------


# Direct Python port of classifyRole() in topology-graph.tsx. If a
# future plan adds a new keyword to the TS classifier, this port
# must be updated in lockstep — see
# test_classifier_keywords_match_typescript_source below.
def _classify_role(role: str) -> str:
    v = role.lower()
    if "attacker" in v or "red" in v or "offensive" in v or "pentester" in v:
        return "red"
    if "router" in v or "firewall" in v or "gw" in v:
        return "router"
    if (
        "victim" in v
        or "defender" in v
        or "blue" in v
        or "target" in v
        or "log-aggregator" in v
        or "syslog" in v
        or "drill_vm" in v
        or "server" in v
        or "workstation" in v
        or "client" in v
    ):
        return "blue"
    return "unassigned"


def test_demo_scenario_classifies_correctly_into_topology_zones():
    """Feed every asset role through the same classifier the
    TopologyGraph component uses, and assert the resulting zone
    distribution is what the demo scenario was designed to show:
    at least 1 red, at least 1 router, at least 2 blue."""
    data = _load()
    zones = [_classify_role(a["role"]) for a in data["spec"]["assets"]]
    red = zones.count("red")
    router = zones.count("router")
    blue = zones.count("blue")
    assert red >= 1, f"Demo scenario needs >= 1 red asset; zones={zones}"
    assert router >= 1, f"Demo scenario needs >= 1 router asset; zones={zones}"
    assert blue >= 2, (
        f"Demo scenario needs >= 2 blue assets; zones={zones}"
    )


# The keyword lists below are a hand-maintained copy of the
# strings inside topology-graph.tsx::classifyRole. Update both
# places if you add a new classifier keyword. The companion test
# `test_classifier_keywords_match_typescript_source` extracts the
# TS keywords from the source file and asserts the Python port
# still contains every one.
EXPECTED_RED_KEYWORDS = {"attacker", "red", "offensive", "pentester"}
EXPECTED_ROUTER_KEYWORDS = {"router", "firewall", "gw"}
EXPECTED_BLUE_KEYWORDS = {
    "victim",
    "defender",
    "blue",
    "target",
    "log-aggregator",
    "syslog",
    "drill_vm",
    "server",
    "workstation",
    "client",
}
# Return string literal; not a substring keyword but the test
# pins every quoted string the classifier uses.
EXPECTED_OTHER_KEYWORDS = {"unassigned"}


def test_classifier_keywords_match_typescript_source():
    """Pin that the Python port stays in sync with the TypeScript
    classifier. If a future plan adds a new keyword to
    topology-graph.tsx, this test fails until both the TS source
    and the EXPECTED_*_KEYWORDS constants above are updated."""
    import re

    topo_src = (REPO / "services" / "portal" / "app" / "src" / "components" / "portal" / "topology-graph.tsx").read_text(
        encoding="utf-8"
    )
    m = re.search(
        r"function classifyRole\(role: string\): Zone \{[\s\S]*?\n\}",
        topo_src,
    )
    assert m, "Could not extract classifyRole from topology-graph.tsx"
    classifier_body = m.group(0)
    # Pull every quoted string in the classifier body. The TS
    # source uses these as .includes() arguments AND as the
    # return string literals ("red" / "blue" / "router" /
    # "unassigned"). Both are valid classifier keywords from the
    # Python port's perspective.
    ts_keywords = set(re.findall(r'"([a-z_-]+)"', classifier_body))
    expected = (
        EXPECTED_RED_KEYWORDS
        | EXPECTED_ROUTER_KEYWORDS
        | EXPECTED_BLUE_KEYWORDS
        | EXPECTED_OTHER_KEYWORDS
    )
    missing = ts_keywords - expected
    extra = expected - ts_keywords
    assert not missing, (
        f"EXPECTED_*_KEYWORDS missing TS keywords: {missing}. "
        f"Update the constants in tests/test_demo_scenario.py."
    )
    assert not extra, (
        f"EXPECTED_*_KEYWORDS has stale entries not in TS: {extra}. "
        f"Update the constants in tests/test_demo_scenario.py."
    )
