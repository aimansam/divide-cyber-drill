# div:ide Observability

Prometheus + Grafana wiring for the divide-cyber-drill platform.

## What ships

| Service | Port | URL | Purpose |
|---|---|---|---|
| Prometheus | `9090` | http://localhost:9090 | Scrapes the API's `/metrics` every 15s |
| Grafana | `3000` | http://localhost:3000 | Dashboards (login: `admin` / `divide` by default) |

Both services start automatically with `docker compose up -d`. They depend
on `api` (Prometheus) and `prometheus` (Grafana), so the chain
`api → prometheus → grafana` is guaranteed healthy before Grafana is
considered ready.

## API `/metrics` endpoint

The API exposes Prometheus 0.0.4 exposition format on `GET /metrics`.

| Metric family | Labels | What it tracks |
|---|---|---|
| `divide_runs_total` | `outcome`, `adapter` | Run lifecycle (started, succeeded, failed, cancelled, timeout) |
| `divide_runs_active` | `adapter` | Current non-terminal runs |
| `divide_run_duration_seconds` | `outcome` | End-to-end run duration histogram |
| `divide_adapter_calls_total` | `method`, `adapter`, `outcome` | PVE adapter calls |
| `divide_adapter_call_latency_seconds` | `method`, `adapter` | Adapter call latency |
| `divide_http_requests_total` | `method`, `route`, `status` | Every HTTP request |
| `divide_http_request_latency_seconds` | `method`, `route` | HTTP handler latency |
| `divide_cancel_requests_total` | `result` | `/drills/{id}/cancel` outcomes |

**Labels are preserved end-to-end** — Prometheus, Grafana, and the
`make verify-drill` tool all use the `outcome` and `adapter` labels
distinctly. Don't ever collapse `divide_runs_total` to a single number:
a `succeeded` and a `failed` increment look identical without labels,
but the regression check (`make verify-drill`) needs to distinguish
them. Earlier in this project, `_fetch_metrics` in `verify_drill.py`
stripped labels — that bug shipped as commit `a600f3c6` and was fixed
in commit `2e4abf7`. The `tests/test_verify_drill.py` suite has a
`_fetch_metrics_preserves_labels` test that catches any regression.

Cardinality is bounded:
- `route` is the templated FastAPI path (`/{run_id}/cancel`), not the literal URL.
- `outcome` / `result` / `status` use closed enums.
- `adapter` is `real` or `mock`.

## Starter dashboard

`deploy/grafana/dashboards/divide-drill-platform.json` is auto-provisioned
on every Grafana start. Six panels:

1. **Run rate by outcome** (time series, stacked by outcome)
2. **Active runs** (single-value stat with thresholds)
3. **Cancel requests** (donut chart, last 1h)
4. **HTTP request latency** (p50 / p95 / p99 percentiles)
5. **HTTP request rate by status** (stacked bar)
6. **HTTP request latency heatmap**

The dashboard is editable from the UI; changes are persisted to the
`grafana-data` volume. The provisioning directory is mounted read-only,
so UI edits don't bleed back into the repo.

## Useful PromQL queries

```promql
# Run success rate over 5m
sum(rate(divide_runs_total{outcome="succeeded"}[5m]))
/
sum(rate(divide_runs_total{outcome=~"succeeded|failed|cancelled"}[5m]))

# Cancel ratio (cancelled vs total terminals)
sum(rate(divide_runs_total{outcome="cancelled"}[5m]))
/
sum(rate(divide_runs_total{outcome=~"succeeded|failed|cancelled"}[5m]))

# HTTP 5xx rate
sum(rate(divide_http_requests_total{status=~"5.."}[5m]))

# Adapter error rate by method
sum by (method) (rate(divide_adapter_calls_total{outcome="error"}[5m]))
```

## Adding a new panel

Two options:

1. **Edit the JSON** — add your panel to
   `deploy/grafana/dashboards/divide-drill-platform.json` and `git commit`.
   Grafana will pick it up within 30s (provisioning reload interval).
2. **Edit in the UI** — Grafana saves to the `grafana-data` volume; the
   change is local to this host. Useful for one-off exploration.

## Production hardening

For anything past local dev:

- Set `GRAFANA_ADMIN_PASSWORD` to a real secret (default is `divide`).
- Remove the `ports:` mapping from `prometheus` and `grafana` and route
  them through Traefik with HTTP basic auth or OAuth.
- Add an Alertmanager sidecar; minimum useful alerts:
  - `rate(divide_runs_total{outcome="failed"}[5m]) > 0.1` for 10m
  - `histogram_quantile(0.95, rate(divide_http_request_latency_seconds_bucket[5m])) > 1` for 10m
  - `up{job="divide-api"} == 0` for 2m (API stopped responding)
- Tune `--storage.tsdb.retention.time` (default 15d).

## Files

| Path | What it does |
|---|---|
| `deploy/prometheus/prometheus.yml` | Scrape config for the API |
| `deploy/grafana/provisioning/datasources/prometheus.yml` | Adds Prometheus as a Grafana datasource |
| `deploy/grafana/provisioning/dashboards/divide.yml` | Auto-loads the starter dashboard |
| `deploy/grafana/dashboards/divide-drill-platform.json` | The dashboard itself |
| `services/api/app/observability/__init__.py` | Metric registry + named counters/histograms |
| `services/api/app/observability/middleware.py` | HTTP request middleware |
| `services/api/app/routers/health.py` | `GET /metrics` endpoint |