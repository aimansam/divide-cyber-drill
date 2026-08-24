"""Telemetry sinks for drill events (L2 2.11).

A drill run produces a stream of events (run.started, asset.spawned,
run.completed, ...). The scenario YAML declares which sinks should
receive them via ``spec.telemetry.sinks[]``. Each sink is a
``TelemetrySink`` protocol with a single ``async send(event) -> None``
method.

Design choices:

  * **Best-effort.** A failing sink (MinIO down, Wazuh 503) must
    NOT fail the drill run. Each sink is wrapped; the error is
    logged and we move on. Telemetry is a side-channel for offline
    analysis; it cannot be on the critical path of "did the drill
    succeed or not".
  * **Stdout by default.** Even without explicit configuration, the
    runner emits a structured-log line per event (handled by the
    runner directly — not by this module). The sinks list is *in
    addition to* that baseline logging.
  * **Lazy construction.** Sinks are built per dispatch based on the
    *current* event, not pre-built. Cheap, and means a config change
    doesn't require a server restart.
  * **No PII redaction.** Events carry ``started_by`` (token subject)
    and VM IPs. Same scope as the audit log; the same redaction rules
    apply. Adding redaction is a separate ticket.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Protocol


class TelemetrySink(Protocol):
    """Minimal sink contract. ``send`` is async, returns None."""

    name: str  # for logs + the SinkResult label

    async def send(self, event: dict[str, Any]) -> None: ...


# --- Built-in sinks ----------------------------------------------------------


class StdoutSink:
    """Print a single JSON line per event. Always available."""

    name = "stdout"

    async def send(self, event: dict[str, Any]) -> None:
        logging.getLogger("divide.telemetry.stdout").info(
            "divide.telemetry.event %s", json.dumps(event, default=str)
        )


class NullSink:
    """Sink that does nothing. Marker for "telemetry disabled here"."""

    name = "null"

    async def send(self, event: dict[str, Any]) -> None:
        return None


@dataclass(frozen=True)
class SinkResult:
    """One row per sink fired per dispatch, captured for tests + logs."""

    sink: str
    ok: bool
    error: str | None = None


async def dispatch(
    sinks: list[TelemetrySink], event: dict[str, Any]
) -> list[SinkResult]:
    """Fire each sink in order. Failures on one sink never block another.

    The dispatch is sequential (avoids stampeding the warehouse if a
    scenario specifies 5 sinks). With our current scope (1 sink per
    dispatch) the cost is negligible; parallel is a follow-up.
    """
    results: list[SinkResult] = []
    for sink in sinks:
        try:
            await sink.send(event)
            results.append(SinkResult(sink=sink.name, ok=True))
        except Exception as exc:  # noqa: BLE001 — best-effort by design
            logging.getLogger(__name__).warning(
                "divide.telemetry.sink_failed sink=%s err=%s",
                sink.name,
                exc,
            )
            results.append(SinkResult(sink=sink.name, ok=False, error=str(exc)))
    return results


def build_sinks_from_spec(spec: dict | None) -> list[TelemetrySink]:
    """Resolve the scenario ``spec.telemetry.sinks[]`` into live sinks.

    The runner always emits a structured-log line per event (handled
    in the runner itself, not here). This list is the *additional*
    sinks configured for the drill. If ``telemetry.sinks`` is unset,
    we return an empty list — i.e. stdout-only.

    Sinks we don't recognise (e.g. ``wazuh``, ``misp``) are logged
    and skipped — they are part of L3 scope, not L2.
    """
    if not spec:
        return []
    sinks_spec = (spec.get("telemetry") or {}).get("sinks") or []
    if not sinks_spec:
        return []

    sinks: list[TelemetrySink] = []
    for s in sinks_spec:
        kind = s.get("type")
        if kind == "stdout":
            sinks.append(StdoutSink())
        elif kind == "minio":
            sink = _build_minio_sink(
                bucket=s.get("bucket"),
                endpoint_override=s.get("endpoint"),
            )
            if sink is not None:
                sinks.append(sink)
        elif kind in ("wazuh", "misp"):
            logging.getLogger(__name__).info(
                "divide.telemetry.sink_deferred type=%s reason=L3_scope",
                kind,
            )
        else:
            logging.getLogger(__name__).warning(
                "divide.telemetry.unknown_sink type=%r", kind
            )
    return sinks


def _build_minio_sink(
    bucket: str | None = None, endpoint_override: str | None = None
) -> TelemetrySink | None:
    """Construct a MinIO sink. Returns None if minio-py is missing."""
    try:
        from minio import Minio  # type: ignore[import-not-found]
    except ImportError:
        logging.getLogger(__name__).info(
            "divide.telemetry.minio_skip reason=minio_not_installed"
        )
        return None

    from app.core.config import settings

    bucket = bucket or settings.minio_bucket
    secret = settings.minio_secret_key
    secret_value = secret.get_secret_value() if secret else ""
    client = Minio(
        endpoint_override or settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=secret_value,
        secure=settings.minio_secure,
    )
    return _MinioTelemetrySink(client=client, bucket=bucket, name="minio")


class _MinioTelemetrySink:
    """MinIO sink using the optional ``minio-py`` package.

    PUTs the event JSON under ``drills/<run_id>/<event_type>-<at>.json``.
    Failures bubble as exceptions — ``dispatch`` catches them.
    """

    def __init__(self, *, client: Any, bucket: str, name: str = "minio") -> None:
        self._client = client
        self._bucket = bucket
        self.name = name

    async def send(self, event: dict[str, Any]) -> None:
        import io

        body = json.dumps(event, default=str).encode("utf-8")
        run_id = event.get("run_id", "anon")
        event_type = event.get("type", "event")
        at = event.get("at", "unknown")
        object_name = f"drills/{run_id}/{event_type}-{at}.json"
        await _put_object_sync(self._client, self._bucket, object_name, body)


async def _put_object_sync(
    client: Any, bucket: str, object_name: str, body: bytes
) -> None:
    """Offload the sync minio PUT to a worker thread.

    Keeps the event loop responsive even if MinIO is on the slow side.
    """
    import asyncio
    import io

    def _do_put() -> None:
        try:
            if not client.bucket_exists(bucket):
                client.make_bucket(bucket)
        except Exception:  # noqa: BLE001 — pre-existing bucket is fine
            pass
        client.put_object(
            bucket,
            object_name,
            io.BytesIO(body),
            length=len(body),
            content_type="application/json",
        )

    await asyncio.to_thread(_do_put)


# Resolved once at import (no per-call cost).
_MINIO_AVAILABLE = True
try:
    import minio  # type: ignore[import-not-found]  # noqa: F401
except ImportError:
    _MINIO_AVAILABLE = False


def is_minio_enabled() -> bool:
    """Whether the MinIO sink can be constructed at runtime."""
    return _MINIO_AVAILABLE


__all__ = [
    "TelemetrySink",
    "StdoutSink",
    "NullSink",
    "SinkResult",
    "build_sinks_from_spec",
    "dispatch",
    "is_minio_enabled",
]