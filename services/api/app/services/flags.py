"""Flag submission + validation logic.

A scenario declares flags in ``spec.flags[]``. The user submits
flags via ``POST /api/v1/drills/{id}/submit-flag``. The
submissions live in ``flag_submissions``.

Pure-function validation so the unit tests pin it:

* ``resolve_flag(spec, flag_id) -> flag_spec``: looks up a flag
  in spec.flags[]. Raises ``FlagError.not_found`` if missing.
* ``verify_flag_value(flag_spec, submitted_value) -> bool``: a
  constant-time-ish string equality, not a cryptographic
  check; flags in this demo are plaintext CTF-style strings.
* ``capture_seconds(run, now)``: how long since the run
  started, capped at 0.

The actual HTTP route lives in ``routers/drills.py``. We keep
the parsing + scoring + persistence here so each piece is
testable in isolation.
"""
from __future__ import annotations

import hmac
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


class FlagError(Exception):
    """Base error for flag operations."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message

    @classmethod
    def not_found(cls, flag_id: str) -> "FlagError":
        return cls("flag_not_found", f"flag {flag_id!r} not in scenario")

    @classmethod
    def wrong_value(cls) -> "FlagError":
        return cls("flag_mismatch", "submitted value does not match")

    @classmethod
    def run_not_active(cls, status: str) -> "FlagError":
        return cls(
            "run_terminal",
            f"run is {status}; flags can only be captured while the run is active",
        )

    @classmethod
    def wrong_team(
        cls, team: str, flag_side: str, runner_role: str
    ) -> "FlagError":
        return cls(
            "wrong_team",
            (
                f"role {runner_role!r} cannot capture a {flag_side!r}-side "
                f"flag with team={team!r}"
            ),
        )

    @classmethod
    def duplicate(
        cls, team: str, flag_id: str
    ) -> "FlagError":
        return cls(
            "duplicate",
            f"team {team!r} already captured flag {flag_id!r}",
        )


@dataclass(frozen=True)
class FlagSpec:
    """One entry from ``spec.flags[]``.

    The runner plants ``value`` on ``planted_on_role`` (the asset
    role) via cloud-init user_data. The scorer uses
    ``base_points`` and ``window_seconds`` to compute the award.
    """

    flag_id: str
    side: str            # "red" hunts | "blue" hunts | "self"
    value: str
    planted_on_role: str
    window_seconds: int
    base_points: int

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> "FlagSpec":
        return cls(
            flag_id=str(raw["id"]),
            side=str(raw["side"]),
            value=str(raw["value"]),
            planted_on_role=str(raw["planted_on_role"]),
            window_seconds=int(raw["decay_window_seconds"]),
            base_points=int(raw["base_points"]),
        )


def resolve_flag(spec: dict[str, Any], flag_id: str) -> FlagSpec:
    """Return the FlagSpec matching ``flag_id``.

    ``spec`` is the parsed scenario (with ``spec.flags[]``). We
    raise :class:`FlagError.not_found` if the flag isn't in
    the list — useful for surfacing a 404 to the user.
    """
    inner_spec = spec.get("spec", spec) if isinstance(spec, dict) else {}
    flags = inner_spec.get("flags") or []
    for raw in flags:
        if str(raw.get("id")) == flag_id:
            return FlagSpec.from_raw(raw)
    raise FlagError.not_found(flag_id)


def verify_flag_value(flag_spec: FlagSpec, submitted: str) -> bool:
    """Return True iff ``submitted`` equals ``flag_spec.value``.

    We use :func:`hmac.compare_digest` so the comparison is
    constant-time relative to the input length. The flag value
    is not particularly secret (CTF-style), but the API still
    avoids leaking a length / timing oracle since a side
    channel could let the operator iterate to a match.
    """
    return hmac.compare_digest(
        flag_spec.value.encode("utf-8"),
        submitted.encode("utf-8"),
    )


def capture_seconds(
    started_at: datetime | None,
    now: datetime | None = None,
) -> int:
    """Compute the elapsed seconds since ``started_at``.

    Clamps to 0 if negative (a capture raced before the DB row
    was persisted). Accepts both tz-aware and tz-naive
    ``started_at`` (SQLite stores datetimes as naive) by
    normalising to UTC if no tz is attached.
    """
    if started_at is None:
        return 0
    if now is None:
        now = datetime.now(timezone.utc)
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    delta = (now - started_at).total_seconds()
    return max(0, int(delta))
