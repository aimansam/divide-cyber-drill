"""Scoring primitives for F5 (flags + scoring).

The scoring function is intentionally small + pure so the unit
tests can pin it independently of the runner / API / DB.

Scoring formula (locked in by tests):

    points = floor( base_points * max(0.0, min(1.0, 1 - elapsed_seconds/window_seconds)) )

A few choices made here:

  * **Floor.** Score is an integer; we floor the multiplication so
    a 99.9 score doesn't leak as 99 to the leaderboard but 100 to
    the audit log. Floor over round so the score never exceeds
    the base.
  * **Linear decay.** Time-decay scoring with a linear
    ``(1 - elapsed / window)`` curve. Anything past window
    awards 0 points. Anything captured at t=0 awards the full
    base.
  * **Cap at base.** Cap at base (no negative decay bonus for
    early captures — only red captures bonus at t=0).
  * **Snapshot at capture.** The DB stores ``points`` and
    ``elapsed_seconds`` on the FlagSubmission row at capture
    time; re-scoring with a different window later does not
    change history.
"""
from __future__ import annotations

import math


def score(
    base_points: int,
    window_seconds: int,
    elapsed_seconds: int,
) -> int:
    """Return the points awarded for a flag captured at
    ``elapsed_seconds`` after the run started.

    Parameters
    ----------
    base_points:
        The maximum points this flag is worth at t=0.
    window_seconds:
        The linear-decay window. At t=window the flag is worth 0.
        After that, it's also 0.
    elapsed_seconds:
        Wall-clock seconds since ``run.started_at``.

    Negative ``elapsed_seconds`` is clamped to 0 (a captured-
    before-the-clock-started race; rare but happens with
    immediate captures during provisioning).
    """
    if base_points <= 0:
        return 0
    if window_seconds <= 0:
        # A scenario with a zero/negative decay window gets the
        # full base points awarded exactly once and never
        # again. We intentionally don't error here; the runner
        # rejects zero windows at validation time. The DB pin
        # (raises 422) happens in the API layer.
        return base_points
    elapsed = max(0, elapsed_seconds)
    decay = max(0.0, min(1.0, 1.0 - elapsed / window_seconds))
    return int(math.floor(base_points * decay))


def score_breakdown(
    base_points: int,
    window_seconds: int,
    captured_at_seconds: int,
) -> dict:
    """Return a serializable breakdown for the after-action report.

    Format::

        {
          "base_points": <int>,
          "window_seconds": <int>,
          "elapsed_seconds": <int>,
          "decay_fraction": <float in [0.0, 1.0]>,
          "awarded_points": <int>,
        }
    """
    if window_seconds <= 0:
        decay = 1.0
    else:
        decay = max(0.0, min(1.0, 1.0 - max(0, captured_at_seconds) / window_seconds))
    return {
        "base_points": base_points,
        "window_seconds": window_seconds,
        "elapsed_seconds": max(0, captured_at_seconds),
        "decay_fraction": decay,
        "awarded_points": score(base_points, window_seconds, captured_at_seconds),
    }
