"""Tests for the Prometheus metrics module and /metrics endpoint."""
from __future__ import annotations

from app.main import app
from app.observability import (
    CANCEL_REQUESTS_TOTAL,
    HTTP_REQUESTS_TOTAL,
    REGISTRY,
    RUNS_TOTAL,
    inc_run_started,
    inc_run_terminal,
    record_adapter_call,
    record_cancel,
    render_latest,
)
from fastapi.testclient import TestClient

# --- exposition format ---------------------------------------------------


def test_render_latest_returns_prometheus_format():
    body, content_type = render_latest()
    # Content type must match what Prometheus expects.
    assert "text/plain" in content_type
    assert "version=" in content_type
    # Body must be bytes with at least the # HELP / # TYPE preamble.
    assert isinstance(body, bytes)
    assert b"# HELP" in body or b"# TYPE" in body


def test_render_latest_includes_known_metric_names():
    """Every metric declared in app.observability should appear in the
    exposition even with zero observations (we use labels so the
    underlying metric exists, just with no series)."""
    body, _ = render_latest()
    text = body.decode()
    # Counter + histogram names we expect to see.
    assert "divide_runs_total" in text
    assert "divide_cancel_requests_total" in text
    assert "divide_http_requests_total" in text
    assert "divide_adapter_calls_total" in text


# --- counter increments --------------------------------------------------


def test_inc_run_started_increments_counter():
    before = _counter_value(RUNS_TOTAL, outcome="started", adapter="mock")
    inc_run_started(adapter="mock")
    after = _counter_value(RUNS_TOTAL, outcome="started", adapter="mock")
    assert after - before == 1


def test_inc_run_terminal_increments_counter():
    before = _counter_value(RUNS_TOTAL, outcome="cancelled", adapter="real")
    inc_run_terminal(outcome="cancelled", adapter="real")
    after = _counter_value(RUNS_TOTAL, outcome="cancelled", adapter="real")
    assert after - before == 1


def test_record_cancel_increments_per_result_label():
    for r in ("ok", "not_found", "already_terminal", "error"):
        before = _counter_value(CANCEL_REQUESTS_TOTAL, result=r)
        record_cancel(result=r)
        after = _counter_value(CANCEL_REQUESTS_TOTAL, result=r)
        assert after - before == 1


def test_record_adapter_call_increments():
    before_ok = _counter_value(
        REGISTRY._names_to_collectors.get("divide_adapter_calls_total"),
        method="clone_vm",
        adapter="mock",
        outcome="ok",
    )
    record_adapter_call(method="clone_vm", adapter="mock", outcome="ok")
    after_ok = _counter_value(
        REGISTRY._names_to_collectors.get("divide_adapter_calls_total"),
        method="clone_vm",
        adapter="mock",
        outcome="ok",
    )
    assert after_ok - before_ok == 1


# --- /metrics endpoint ----------------------------------------------------


def test_metrics_endpoint_returns_200_and_prometheus_body():
    client = TestClient(app)
    r = client.get("/metrics")
    assert r.status_code == 200
    assert "text/plain" in r.headers["content-type"]
    # Should at minimum contain one of our metric names.
    assert "divide_runs_total" in r.text or "divide_http_requests_total" in r.text


def test_metrics_endpoint_increments_http_counter_on_request():
    client = TestClient(app)
    # Capture counter value before
    before = _counter_value(
        HTTP_REQUESTS_TOTAL, method="GET", route="/healthz", status="200"
    )
    r = client.get("/healthz")
    assert r.status_code == 200
    after = _counter_value(
        HTTP_REQUESTS_TOTAL, method="GET", route="/healthz", status="200"
    )
    assert after - before >= 1


def test_metrics_endpoint_does_not_count_itself():
    """The middleware short-circuits /metrics to avoid scrape inflation."""
    client = TestClient(app)
    # Even after hitting /metrics, the counter for the /metrics route
    # itself should NOT increment.
    before = _counter_value(
        HTTP_REQUESTS_TOTAL, method="GET", route="/metrics", status="200"
    )
    client.get("/metrics")
    client.get("/metrics")
    after = _counter_value(
        HTTP_REQUESTS_TOTAL, method="GET", route="/metrics", status="200"
    )
    assert after == before


# --- helpers --------------------------------------------------------------


def _counter_value(metric, **labels):
    """Read the current value of a labelled Counter (or 0 if no series)."""
    # prometheus_client >=0.20 uses .collect(); samples are .value for Counter.
    try:
        for fam in metric.collect():
            for sample in fam.samples:
                if sample.name.endswith("_total") and all(
                    sample.labels.get(k) == v for k, v in labels.items()
                ):
                    return sample.value
    except AttributeError:
        pass
    return 0.0