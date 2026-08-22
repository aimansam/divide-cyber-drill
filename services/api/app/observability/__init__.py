"""Prometheus metrics for div:ide API.

Single module that owns the metric registry and exposes named counters /
gauges / histograms. Other modules import the named objects directly so
they don't need to know the registry — and tests can re-import the
module to grab the same objects.

Labels are kept low-cardinality on purpose:
  * outcome   ∈ {started, succeeded, failed, cancelled, timeout, error}
  * adapter   ∈ {real, mock}
  * method    — HTTP method (GET/POST/...)
  * route     — FastAPI route template (e.g. "/api/v1/drills/{run_id}/cancel")
  * status    — HTTP status code as string ("200", "404", ...)

We deliberately do NOT label by scenario_id, run_id, or VMID — those
have unbounded cardinality and would blow out Prometheus.
"""
from __future__ import annotations

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

# Module-level registry. Importing ``prometheus_client`` defaults to a
# global registry, but using our own makes tests cleaner (we can create
# a fresh one per test) and avoids accidental collisions with anything
# uvicorn's internals might register.
REGISTRY = CollectorRegistry()

# --- run lifecycle ---------------------------------------------------------

RUNS_TOTAL = Counter(
    "divide_runs_total",
    "Number of drill runs by terminal outcome.",
    labelnames=("outcome", "adapter"),
    registry=REGISTRY,
)
# outcome values: started, succeeded, failed, cancelled, timeout

RUN_ACTIVE = Gauge(
    "divide_runs_active",
    "Drill runs currently in a non-terminal state.",
    labelnames=("adapter",),
    registry=REGISTRY,
)

RUN_DURATION_SECONDS = Histogram(
    "divide_run_duration_seconds",
    "End-to-end duration of a drill run (start -> terminal).",
    labelnames=("outcome",),
    buckets=(1, 5, 15, 30, 60, 120, 300, 600, 1800, 3600),
    registry=REGISTRY,
)

# --- adapter / PVE --------------------------------------------------------

ADAPTER_CALLS_TOTAL = Counter(
    "divide_adapter_calls_total",
    "Proxmox adapter method calls.",
    labelnames=("method", "adapter", "outcome"),
    registry=REGISTRY,
)
# method values: clone_vm, start_vm, stop_vm, destroy_vm, find_template,
#                allocate_vmid, get_vm_state, list_nodes, ...
# outcome values: ok, error

ADAPTER_CALL_LATENCY_SECONDS = Histogram(
    "divide_adapter_call_latency_seconds",
    "Latency of Proxmox adapter calls.",
    labelnames=("method", "adapter"),
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
    registry=REGISTRY,
)

# --- HTTP (set by the middleware) -----------------------------------------

HTTP_REQUESTS_TOTAL = Counter(
    "divide_http_requests_total",
    "HTTP requests handled by the API, by route template.",
    labelnames=("method", "route", "status"),
    registry=REGISTRY,
)

HTTP_REQUEST_LATENCY_SECONDS = Histogram(
    "divide_http_request_latency_seconds",
    "HTTP request handler latency.",
    labelnames=("method", "route"),
    buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
    registry=REGISTRY,
)

# --- cancellation-specific (so the new endpoint is visible) ---------------

CANCEL_REQUESTS_TOTAL = Counter(
    "divide_cancel_requests_total",
    "Drill cancel requests, by result.",
    labelnames=("result",),
    registry=REGISTRY,
)
# result values: ok, not_found, already_terminal, error


def render_latest() -> tuple[bytes, str]:
    """Return ``(body, content_type)`` for a /metrics response."""
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST


# --- convenience helpers --------------------------------------------------


def inc_run_started(adapter: str = "mock") -> None:
    RUNS_TOTAL.labels(outcome="started", adapter=adapter).inc()
    RUN_ACTIVE.labels(adapter=adapter).inc()


def inc_run_terminal(outcome: str, adapter: str = "mock") -> None:
    """outcome ∈ {succeeded, failed, cancelled, timeout}"""
    RUNS_TOTAL.labels(outcome=outcome, adapter=adapter).inc()
    RUN_ACTIVE.labels(adapter=adapter).dec()


def record_cancel(result: str) -> None:
    """result ∈ {ok, not_found, already_terminal, error}"""
    CANCEL_REQUESTS_TOTAL.labels(result=result).inc()


def record_adapter_call(method: str, adapter: str, outcome: str) -> None:
    """outcome ∈ {ok, error}"""
    ADAPTER_CALLS_TOTAL.labels(method=method, adapter=adapter, outcome=outcome).inc()


def _zero_init() -> None:
    """Pre-create label combinations with value 0 so the metrics show
    up in scrapes before the first run. Without this, Prometheus would
    only see a metric after the first increment — bad for alerting
    (``rate(...)`` returns NaN until at least one sample).

    Label sets mirror the cardinality declared in the module docstring.
    """
    for adapter in ("real", "mock"):
        RUNS_TOTAL.labels(outcome="started", adapter=adapter)
        RUN_ACTIVE.labels(adapter=adapter)
        for outcome in ("succeeded", "failed", "cancelled", "timeout"):
            RUNS_TOTAL.labels(outcome=outcome, adapter=adapter)
    for result in ("ok", "not_found", "already_terminal", "error"):
        CANCEL_REQUESTS_TOTAL.labels(result=result)
    for status_code in ("200", "201", "204", "400", "404", "409", "422", "500"):
        HTTP_REQUESTS_TOTAL.labels(method="GET", route="/healthz", status=status_code)


# Module import side effect: zero-init so /metrics is non-empty from
# the very first scrape. Safe to run multiple times — labels() returns
# the existing sample if already created.
_zero_init()


__all__ = [
    "REGISTRY",
    "RUNS_TOTAL",
    "RUN_ACTIVE",
    "RUN_DURATION_SECONDS",
    "ADAPTER_CALLS_TOTAL",
    "ADAPTER_CALL_LATENCY_SECONDS",
    "HTTP_REQUESTS_TOTAL",
    "HTTP_REQUEST_LATENCY_SECONDS",
    "CANCEL_REQUESTS_TOTAL",
    "render_latest",
    "inc_run_started",
    "inc_run_terminal",
    "record_cancel",
    "record_adapter_call",
]