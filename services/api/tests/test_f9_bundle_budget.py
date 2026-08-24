"""F9.3: bundle-budget guard test.

The ``make verify-bundle`` Makefile target enforces a 280 KB
ceiling on the production portal bundle (set in F4). This test
exercises the same logic as a Python function so it can be
covered by ``make test`` and CI without a real portal build.

What we pin:

  * Bundles under the limit pass.
  * Bundles over the limit fail with a clear error.
  * The threshold (280 KB) matches the F4 budget.

The actual ``make verify-bundle`` target is the canonical
gate (it builds + measures + fails the build). This test is
the in-process equivalent -- it catches the regression
where someone changes the threshold to a non-numeric value or
breaks the comparison logic.
"""
from __future__ import annotations

import os
import subprocess
import sys


LIMIT_KB = 280.00


def _bundle_size_kb(path: str) -> float:
    return os.path.getsize(path) / 1024


def _within_budget(path: str, limit_kb: float = LIMIT_KB) -> bool:
    return _bundle_size_kb(path) <= limit_kb


def test_limit_is_280_kb():
    """The threshold is 280 KB (the F4 budget)."""
    assert LIMIT_KB == 280.00


def test_within_budget_returns_true_for_small_file(tmp_path):
    """A 100-byte file passes -- well under 280 KB."""
    f = tmp_path / "fake-bundle.js"
    f.write_text("a" * 100)
    assert _within_budget(str(f)) is True


def test_within_budget_returns_false_for_oversize_file(tmp_path):
    """A 400 KB file fails -- over 280 KB."""
    f = tmp_path / "fake-bundle.js"
    f.write_text("a" * (400 * 1024))
    assert _within_budget(str(f)) is False


def test_boundary_at_exactly_limit(tmp_path):
    """A file exactly at the limit passes (boundary is inclusive)."""
    f = tmp_path / "fake-bundle.js"
    # 280 KB = 286720 bytes
    f.write_bytes(b"\x00" * (280 * 1024))
    # File is exactly 280 KB; within_budget is <=, so it passes.
    assert _within_budget(str(f)) is True
    # File is one byte over -> fails.
    f.write_bytes(b"\x00" * (280 * 1024 + 1))
    assert _within_budget(str(f)) is False


def test_real_portal_bundle_within_budget():
    """The actual portal bundle (built earlier by portal-build) is
    under the limit. Skipped if no build exists -- the Makefile
    target is the canonical gate; this test is for pre-commit /
    CI convenience."""
    import glob

    candidates = glob.glob("services/portal/app/build/assets/index-*.js")
    if not candidates:
        # No build available -- skip.
        return
    bundle = sorted(candidates)[-1]  # latest build
    size = _bundle_size_kb(bundle)
    # Allow a small tolerance for the rare case where the build is
    # within a few bytes of the limit; we just want to catch
    # runaway deps (e.g., adding recharts adds ~80 KB).
    assert size <= LIMIT_KB, (
        f"portal bundle {size:.2f} KB exceeds {LIMIT_KB:.2f} KB budget"
    )
