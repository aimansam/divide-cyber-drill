"""Smoke tests for the deploy/ observability configs.

We don't bring up Prometheus/Grafana in CI (that's heavy and the
deployment environment is host-specific). Instead we validate that:

  * prometheus.yml parses as YAML
  * Grafana dashboard JSON parses
  * Grafana provisioning files parse
  * docker-compose.yml references all the expected service names
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DEPLOY = REPO_ROOT / "deploy"


def test_prometheus_config_loads() -> None:
    cfg_path = DEPLOY / "prometheus" / "prometheus.yml"
    cfg = yaml.safe_load(cfg_path.read_text())
    # Top-level keys.
    assert "scrape_configs" in cfg
    assert "global" in cfg
    # We must scrape the API at the right target.
    jobs = {j["job_name"]: j for j in cfg["scrape_configs"]}
    assert "divide-api" in jobs
    api_job = jobs["divide-api"]
    assert api_job["metrics_path"] == "/metrics"
    targets = api_job["static_configs"][0]["targets"]
    assert "api:8000" in targets


def test_grafana_datasource_provisioning_loads() -> None:
    cfg_path = DEPLOY / "grafana" / "provisioning" / "datasources" / "prometheus.yml"
    cfg = yaml.safe_load(cfg_path.read_text())
    assert cfg["apiVersion"] == 1
    ds = cfg["datasources"][0]
    assert ds["type"] == "prometheus"
    assert ds["url"] == "http://prometheus:9090"
    assert ds["isDefault"] is True


def test_grafana_dashboard_provider_loads() -> None:
    cfg_path = DEPLOY / "grafana" / "provisioning" / "dashboards" / "divide.yml"
    cfg = yaml.safe_load(cfg_path.read_text())
    assert cfg["apiVersion"] == 1
    providers = cfg["providers"]
    assert len(providers) == 1
    p = providers[0]
    assert p["type"] == "file"
    # The path is where Grafana looks inside the container.
    assert p["options"]["path"] == "/var/lib/grafana/dashboards"


def test_starter_dashboard_loads_and_has_expected_panels() -> None:
    cfg_path = DEPLOY / "grafana" / "dashboards" / "divide-drill-platform.json"
    dash = json.loads(cfg_path.read_text())
    assert dash["title"].startswith("div:ide")
    assert dash["uid"] == "divide-drill-platform"
    panel_types = {p["type"] for p in dash["panels"]}
    # We expect at least one of each: timeseries, stat, piechart, heatmap.
    assert "timeseries" in panel_types
    assert "stat" in panel_types
    assert "piechart" in panel_types
    assert "heatmap" in panel_types
    # And the right panel count — six by design.
    assert len(dash["panels"]) == 6
    # Every panel must reference the Prometheus datasource.
    for p in dash["panels"]:
        assert p["datasource"] == "Prometheus"
        assert len(p["targets"]) >= 1


def test_compose_mentions_all_observability_services() -> None:
    compose_path = DEPLOY / "docker-compose.yml"
    compose = compose_path.read_text()
    for name in ("prometheus:", "grafana:", "api:"):
        assert name in compose, f"docker-compose.yml missing service {name!r}"
    # The two new volumes must be declared.
    assert "prometheus-data:" in compose
    assert "grafana-data:" in compose