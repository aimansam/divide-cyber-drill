"""Per-token rate limiting for drill creation.

Closes L2 2.7. Without this, a buggy / misclicking operator can call
``POST /api/v1/drills`` in a tight loop and accidentally spawn many
PVE clones (each ~30 s, each costing disk + RAM). The fix is a
window-counter keyed on ``token.sub`` (Redis-backed so the limit holds
across uvicorn workers).

Why this isn't just an in-process counter:

  * Multi-worker uvicorn means in-process state is per-worker. With
    N workers and limit L, the actual ceiling is N×L. Redis is the
    single shared truth.
  * A per-process counter is lost on restart, which defeats the
    purpose (an operator rebooting the API would get a fresh budget
    every time).
  * A simple Redis ``INCR`` on a key with a TTL is atomic, fast, and
    has well-known semantics; we depend on ``fakeredis`` in unit
    tests for the same shape.

Algorithm (fixed-window counter):

    For each ``sub`` we keep a counter at ``divide:rl:drills:<sub>``
    with TTL = ``window_s``. Each ``start_drill`` call does
    ``INCR``; if the post-increment value exceeds the limit, the
    request is rejected with 429. The TTL refreshes on every call
    (Redis ``EXPIRE`` is idempotent), so an operator who pauses for
    ``window_s`` gets a fresh budget.

The module is intentionally minimal — no leaky-bucket algorithm, no
quota, no per-route overrides. If we later need those, replace this
module; the router integration is the single call site (``start_drill``
in ``routers/drills.py``).
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, status

from app.services import cache as _cache_module


# --- module-level tunables (env-overridable) -------------------------------
#
# These defaults are intentionally not in pydantic-settings yet; if
# they get touched regularly, hoist them then. The constants keep
# the integration simple and the tests pure.


DEFAULT_LIMIT: int = 5  # max drill starts per window per sub
DEFAULT_WINDOW_SECONDS: int = 3600  # 1 hour


@dataclass(frozen=True)
class RateLimitConfig:
    """Resolved configuration for the drill-start rate limiter.

    Tests override via :func:`set_config` (which the production code
    path never calls). The single source of truth makes it easy to
    reason about behaviour.
    """

    limit: int = DEFAULT_LIMIT
    window_seconds: int = DEFAULT_WINDOW_SECONDS


_CONFIG = RateLimitConfig()


def get_config() -> RateLimitConfig:
    """Return the current rate-limit config.

    Splitting this out from the constants means a future move to
    pydantic-settings is a one-function edit, not a hunt-and-replace.
    """
    return _CONFIG


def set_config(limit: int | None = None, window_seconds: int | None = None) -> None:
    """Override the config from tests.

    Production code never calls this — the config is supposed to be
    immutable at runtime.
    """
    global _CONFIG
    _CONFIG = RateLimitConfig(
        limit=limit if limit is not None else _CONFIG.limit,
        window_seconds=window_seconds if window_seconds is not None else _CONFIG.window_seconds,
    )


def _bucket_key(sub: str) -> str:
    """Redis key for the drill-start bucket of one subject."""
    return f"divide:rl:drills:{sub}"


async def check_drill_start_limit(sub: str) -> None:
    """Gate ``POST /api/v1/drills``.

    Raises :class:`HTTPException` with status 429 if the caller is
    over the limit. A no-op when the bucket hasn't been created yet
    (Redis returns 1, well under the limit).

    Awaited as part of the request pipeline; the router calls it
    directly so the verified token subject is in scope.

    Fail-open on Redis errors: if Redis is unreachable (e.g. during
    local dev without a Redis container), the request is allowed and
    a structured-log warning is emitted. This is the right default for
    a safety net — we'd rather let a few extra drill starts through
    than refuse a legitimate request because Redis went down. If you
    want fail-closed, set ``DIVIDE_RATE_LIMIT_FAIL_CLOSED=true``.
    """
    import os

    import structlog

    cfg = get_config()
    key = _bucket_key(sub)

    try:
        client = _cache_module.get_redis()
        pipe = client.pipeline()
        pipe.incr(key)
        pipe.expire(key, cfg.window_seconds)
        count, _ = await pipe.execute()
    except Exception as exc:  # noqa: BLE001 — fail-open is intentional
        if os.environ.get("DIVIDE_RATE_LIMIT_FAIL_CLOSED", "").lower() in (
            "1", "true", "yes"
        ):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"rate limiter unavailable: {exc}",
            ) from exc
        structlog.get_logger().warning(
            "divide.rate_limit.redis_unreachable",
            subject=sub,
            error=str(exc),
        )
        return  # fail-open

    if int(count) > cfg.limit:
        # Don't decrement; the bucket naturally expires. Returning
        # the limit in the detail lets the UI render a useful toast.
        # Q15: carry a ``kind`` discriminator in the JSON detail
        # so the portal can dispatch on error type instead of
        # routing every failure to "Open Config". Today the run
        # lifecycle card always appends "Open Config" because the
        # rate-limit error has nothing to do with PVE credentials
        # or bridges -- the message says "rate limit exceeded"
        # but the UI sends the user to the wrong place. The
        # structured detail below lets the UI render a different
        # banner for ``kind="rate_limited"`` vs PVE/bridge errors.
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "kind": "rate_limited",
                "message": (
                    f"drill start rate limit exceeded for {sub!r}: "
                    f"{count}/{cfg.limit} starts in the last "
                    f"{cfg.window_seconds}s window. Wait for the "
                    f"window to reset before retrying."
                ),
                "subject": sub,
                "count": int(count),
                "limit": cfg.limit,
                "window_s": cfg.window_seconds,
            },
        )


__all__ = [
    "DEFAULT_LIMIT",
    "DEFAULT_WINDOW_SECONDS",
    "RateLimitConfig",
    "get_config",
    "set_config",
    "check_drill_start_limit",
]