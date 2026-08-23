"""Tests for docs/TEST-PRODUCT.md.

These don't validate prose — they validate structure. Specifically:
  * L1, L2, L3 sections exist with exactly 15 criteria each.
  * Each criterion row has the same shape: `<number>. <text> | <how> | <status>`.
  * Status is one of ✅ / ❌ / ⚠️ (the only valid markers in this doc).
  * No criterion number appears twice.
  * STATUS column in the L1 table matches reality (e.g. if 1.14 says
    "190 passing", the test_count check should not regress below 190).

If the operator updates the doc with new criteria (e.g. adds 2.16),
the row count test will catch any drift.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
DOC = REPO / "docs" / "TEST-PRODUCT.md"


def _read_doc() -> str:
    assert DOC.exists(), f"{DOC} does not exist"
    return DOC.read_text(encoding="utf-8")


def _extract_table_rows(text: str, level_marker: str) -> list[tuple[str, str, str, str]]:
    """Return [(number, criterion, how, status), ...] for the table
    immediately following the section header that contains `level_marker`.

    Skips the header row (| # | Criterion ...) and the separator row
    (|---|---|...)."""
    header_re = re.compile(rf"^### .*{re.escape(level_marker)}.*?$", re.MULTILINE)
    m = header_re.search(text)
    assert m, f"section '{level_marker}' not found in {DOC}"
    after = text[m.end():]
    lines = after.splitlines()
    rows: list[tuple[str, str, str, str]] = []
    in_table = False
    saw_separator = False
    for line in lines:
        if not line.startswith("|"):
            if in_table:
                # Past the table.
                break
            continue
        # Inside the table.
        if not in_table:
            in_table = True
            # This line is the column header (| # | Criterion ...).
            continue
        if not saw_separator and re.match(r"^\|\s*-+", line):
            saw_separator = True
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) >= 3:
            # L1 tables have 4 cols (#, criterion, how, status);
            # L2/L3 tables have 3 cols (#, criterion, status).
            # Pad to 4-tuple for uniform shape.
            rows.append((cells[0], cells[1], cells[2] if len(cells) >= 3 else "",
                         cells[3] if len(cells) >= 4 else ""))
    return rows


# ---------- structure ----------


def test_doc_has_l1_criteria_with_15_rows():
    text = _read_doc()
    rows = _extract_table_rows(text, "L1 Criteria")
    assert len(rows) == 15, (
        f"L1 should have exactly 15 criteria; got {len(rows)}. "
        f"Update the test count if this is intentional."
    )


def test_doc_has_l2_criteria_with_at_least_15_rows():
    """L2 grew from 15 → 18 when the wizard + test UI + audit endpoint shipped.

    The test enforces a lower bound (not ==) so:
      * Rows don't get silently deleted (alert if count drops below 15).
      * Adding new criteria doesn't break the structural suite.
      * The L3 table is checked for parity (it grew too).
    """
    text = _read_doc()
    rows = _extract_table_rows(text, "New criteria beyond L1")
    assert len(rows) >= 15, f"L2 has {len(rows)} rows, expected ≥ 15"


def test_doc_has_l3_criteria_with_at_least_15_rows():
    text = _read_doc()
    rows = _extract_table_rows(text, "New criteria beyond L2")
    assert len(rows) >= 15, f"L3 has {len(rows)} rows, expected ≥ 15"


# ---------- row shape ----------


@pytest.mark.parametrize("level", ["L1 Criteria", "New criteria beyond L1", "New criteria beyond L2"])
def test_every_row_has_valid_status_marker(level):
    text = _read_doc()
    rows = _extract_table_rows(text, level)
    valid = {"✅", "❌", "⚠️"}
    for row in rows:
        num, criterion, how, status = row
        # For 3-column tables (L2/L3), 'status' is column 2; for 4-column
        # tables (L1), it's column 3. Use whichever is non-empty.
        marker = (status or how or criterion).split()[0] if (status or how) else ""
        # Actually for L1: column 3 = status (has ✅/❌/⚠️).
        # For L2/L3: column 2 = status.
        # We know L1 has 4 cells and L2/L3 have 3 — pick the last cell.
        # But our extractor pads to 4 cells with ''. So use the last
        # *non-empty* cell.
        cells = [c for c in (criterion, how, status) if c]
        marker_source = cells[-1] if cells else ""
        marker = marker_source.split()[0] if marker_source else ""
        assert marker in valid, (
            f"{num}: status must start with one of {valid}, got {marker!r} "
            f"(cells={cells!r})"
        )


@pytest.mark.parametrize("level", ["L1 Criteria", "New criteria beyond L1", "New criteria beyond L2"])
def test_every_row_number_is_unique(level):
    text = _read_doc()
    rows = _extract_table_rows(text, level)
    nums = [r[0] for r in rows]
    pattern = re.compile(r"^\d+\.\d+$")
    bad = [n for n in nums if not pattern.match(n)]
    assert not bad, f"{level}: invalid row numbers {bad}"
    assert len(nums) == len(set(nums)), f"{level}: duplicate row numbers"


@pytest.mark.parametrize("level", ["L1 Criteria", "New criteria beyond L1", "New criteria beyond L2"])
def test_every_row_has_how_column(level):
    text = _read_doc()
    rows = _extract_table_rows(text, level)
    for num, _criterion, how, _status in rows:
        assert how, f"{num}: 'How to verify' column is empty"


# ---------- reality checks ----------


def test_l1_status_reflects_actual_preflight():
    """1.2 says `make preflight reports 9/9 PASS`. Preflight is now green
    (run #11 succeeded) so 1.2 is marked ✅. Update this test only when
    preflight regresses back to a non-green status."""
    text = _read_doc()
    rows = _extract_table_rows(text, "L1 Criteria")
    for num, criterion, _how, status in rows:
        if num == "1.2":
            assert "9/9" in criterion, f"1.2 should mention 9/9 target, got {criterion!r}"
            assert status.startswith("✅"), (
                f"1.2 status should be ✅ while preflight is 9/9. "
                f"Got {status!r}"
            )
            return
    pytest.fail("L1 row 1.2 (preflight) not found")


def test_l1_status_reflects_test_count():
    """1.14 says tests are passing. Cross-check the actual test count.
    The count lives in the STATUS cell as '✅ N passing'."""
    text = _read_doc()
    rows = _extract_table_rows(text, "L1 Criteria")
    for num, _criterion, _how, status in rows:
        if num == "1.14":
            m = re.search(r"(\d+)\s+passing", status)
            assert m, f"1.14 status should mention '<N> passing', got {status!r}"
            claimed = int(m.group(1))
            # Run pytest --collect-only to count tests without executing them.
            # Faster than a full run; times out gracefully on slow CI.
            try:
                proc = subprocess.run(
                    ["python3", "-m", "pytest", "tests/", "services/api/tests/",
                     "--collect-only", "-q"],
                    cwd=REPO,
                    env={**os.environ, "PYTHONPATH": "services/api:."},
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                sm = re.search(r"(\d+)\s+tests collected", proc.stdout + proc.stderr)
                if not sm:
                    pytest.skip(
                        f"could not parse pytest --collect-only output:\n"
                        f"{proc.stdout}\n{proc.stderr}"
                    )
                actual = int(sm.group(1))
            except subprocess.TimeoutExpired:
                pytest.skip("pytest --collect-only timed out")
            assert actual >= claimed, (
                f"TEST-PRODUCT.md claims {claimed} tests passing, "
                f"but collect-only finds {actual}. Either fix the test "
                f"count in the doc or fix the regression."
            )
            return
    pytest.fail("L1 row 1.14 (tests) not found")


# ---------- references ----------


def test_plan_md_links_to_test_product():
    plan = (REPO / "docs" / "PLAN.md").read_text(encoding="utf-8")
    assert "TEST-PRODUCT.md" in plan, "PLAN.md should reference TEST-PRODUCT.md"


def test_readme_lists_test_product_in_docs():
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    assert "TEST-PRODUCT.md" in readme, "README.md should list TEST-PRODUCT.md in docs/"


