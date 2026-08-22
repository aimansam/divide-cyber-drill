"""FastAPI middleware that records HTTP request metrics.

We record:
  * divide_http_requests_total{method, route, status}
  * divide_http_request_latency_seconds{method, route}

``route`` is a bounded-cardinality identifier for the matched route.
We use the FastAPI route *template* (``scope['route'].path``) which
keeps path parameters as ``{run_id}`` rather than the literal value,
so cardinality stays bounded by routes not by requests.

Note: when routers are mounted via ``include_router(prefix=...)``,
FastAPI's ``route.path`` is RELATIVE to that prefix, so the cancel
route shows as ``/{run_id}/cancel`` rather than
``/api/v1/drills/{run_id}/cancel``. We accept this — dashboards group
by method anyway, and full paths would require walking Starlette's
internal include graph (brittle). The route *pattern* (with ``{}``
placeholders) is preserved, which is what matters for cardinality.

Skips recording for the /metrics endpoint itself (otherwise scrapes
inflate the counter).
"""
from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.types import ASGIApp

from app.observability import HTTP_REQUEST_LATENCY_SECONDS, HTTP_REQUESTS_TOTAL


class PrometheusMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        # Skip the scrape endpoint itself.
        if request.url.path == "/metrics":
            return await call_next(request)

        started = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - started

        # request.scope["route"] is set by FastAPI when the router
        # matched; its ``path`` attribute is the templated route
        # (path params stay as ``{name}``). If the request didn't
        # match any route, fall back to a coarse bucket so we don't
        # blow up cardinality on attacker-supplied URLs.
        #
        # Note: a route declared as ``@router.get("", ...)`` (mounted at
        # ``/api/v1/drills``) has ``route.path == ''`` because the path
        # is relative to the include_router prefix. We normalise that
        # to ``/`` so it doesn't fall into the ``<unmatched>`` bucket.
        route = request.scope.get("route")
        raw_path = getattr(route, "path", None)
        if raw_path is None:
            route_template = "<unmatched>"
        elif raw_path == "":
            route_template = "/"
        else:
            route_template = raw_path

        method = request.method
        status = str(response.status_code)

        HTTP_REQUESTS_TOTAL.labels(
            method=method, route=route_template, status=status
        ).inc()
        HTTP_REQUEST_LATENCY_SECONDS.labels(
            method=method, route=route_template
        ).observe(elapsed)

        return response