"""Tests for the demo runner script + docs.

The demo runner is the operator's "show off the cyber range" entry
point. We can't run it in CI (no API to hit, no browser), so these
tests pin:

  * tools/demo.sh exists and is executable
  * the script's API health-check + scenario-listing + URL-print
    surface are intact (no regressions from a future edit)
  * the Makefile exposes `make demo` + `make demo-open` targets
  * docs/DEMO.md exists and documents the steps
"""
from __future__ import annotations

import os
import re
import stat
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
DEMO_SH = REPO / "tools" / "demo.sh"
MAKEFILE = REPO / "Makefile"
DEMO_DOC = REPO / "docs" / "DEMO.md"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# ---------- tools/demo.sh ----------------------------------------------


def test_demo_script_exists():
    assert DEMO_SH.is_file(), "tools/demo.sh is missing"


def test_demo_script_is_executable():
    mode = DEMO_SH.stat().st_mode
    assert mode & 0o111, (
        f"tools/demo.sh must be executable (chmod +x); mode={oct(mode)}"
    )


def test_demo_script_shebang():
    """A bash shebang is required for `bash tools/demo.sh` to work
    even if the executable bit is set."""
    src = _read(DEMO_SH)
    assert src.startswith("#!/usr/bin/env bash"), (
        "tools/demo.sh must start with '#!/usr/bin/env bash'"
    )


def test_demo_script_checks_api_health():
    """The script must verify /healthz is reachable before printing
    the rest of the demo instructions. A 'not reachable' branch
    must tell the operator how to start the stack."""
    src = _read(DEMO_SH)
    assert "/healthz" in src
    assert "make up" in src, (
        "demo.sh must suggest 'make up' on the unreachable branch"
    )


def test_demo_script_lists_scenarios():
    """The script must hit /api/v1/scenarios and pretty-print the
    names so the operator can see what's in the catalog."""
    src = _read(DEMO_SH)
    assert "/api/v1/scenarios" in src


def test_demo_script_prints_portal_url():
    src = _read(DEMO_SH)
    assert "/portal/app/" in src
    assert "PORTAL_URL" in src or "portal/app" in src


def test_demo_script_documents_admin_hints():
    src = _read(DEMO_SH)
    assert "DIVIDE_BOOTSTRAP_ADMIN" in src, (
        "demo.sh must mention the bootstrap admin env vars so "
        "operators who set them see the sign-in hint"
    )


def test_demo_script_documents_f4_ui_tabs():
    """F4-UI is the visual layer the demo is showing off. Each of
    the 6 tabs must be named in the script's output."""
    src = _read(DEMO_SH)
    for tab in (
        "Dashboard",
        "Operate",
        "Observe",
        "Admin",
        "History",
        "Profile",
    ):
        assert tab in src, f"demo.sh must mention the {tab} tab"


def test_demo_script_documents_demo_scenarios():
    """The cyber-range demo scenarios must be listed so the operator
    knows which one to start with."""
    src = _read(DEMO_SH)
    for scenario in (
        "red-vs-blue-baseline",
        "first-live-drill",
        "phish-to-ransom",
        "lateral-movement-baseline",
    ):
        assert scenario in src, (
            f"demo.sh must mention the {scenario!r} scenario"
        )


def test_demo_script_supports_open_flag():
    """The --open flag tries to open the portal in a browser."""
    src = _read(DEMO_SH)
    assert "--open" in src
    assert "xdg-open" in src or "open" in src


def test_demo_script_supports_api_override():
    """The --api flag points at a remote stack."""
    src = _read(DEMO_SH)
    assert "--api" in src


def test_demo_script_exits_non_zero_on_unreachable_api():
    """A non-running API must fail loudly with a non-zero exit code."""
    src = _read(DEMO_SH)
    assert "exit 2" in src, (
        "demo.sh must exit 2 (or any non-zero) when /healthz is unreachable"
    )


def test_demo_script_bash_syntax_valid():
    """Use bash -n to syntax-check the script without running it."""
    import subprocess

    r = subprocess.run(
        ["bash", "-n", str(DEMO_SH)],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, (
        f"tools/demo.sh has a bash syntax error:\n{r.stderr}"
    )


# ---------- Makefile ----------------------------------------------------


def test_makefile_has_demo_target():
    src = _read(MAKEFILE)
    m = re.search(r"^demo:\s*##", src, re.MULTILINE)
    assert m, "Makefile must expose a `demo:` target with a ## docstring"


def test_makefile_has_demo_open_target():
    src = _read(MAKEFILE)
    m = re.search(r"^demo-open:\s*##", src, re.MULTILINE)
    assert m, "Makefile must expose a `demo-open:` target"


def test_makefile_demo_target_runs_demo_sh():
    src = _read(MAKEFILE)
    # Find the body of the demo: target.
    m = re.search(r"^demo:.*?\n\t(.+)", src, re.MULTILINE | re.DOTALL)
    assert m
    body = m.group(1)
    assert "tools/demo.sh" in body, (
        f"`make demo` must invoke tools/demo.sh; body={body!r}"
    )


def test_makefile_demo_in_phony():
    """`make demo` must be reachable, so it must be in .PHONY."""
    src = _read(MAKEFILE)
    phony_match = re.search(r"^\.PHONY:\s*(.+?)$", src, re.MULTILINE)
    assert phony_match, "Makefile must declare a .PHONY line"
    phony = phony_match.group(1)
    assert re.search(r"\bdemo\b", phony), (
        "`demo` must be in .PHONY"
    )
    assert re.search(r"\bdemo-open\b", phony), (
        "`demo-open` must be in .PHONY"
    )


# ---------- docs/DEMO.md ------------------------------------------------


def test_demo_doc_exists():
    assert DEMO_DOC.is_file(), "docs/DEMO.md is missing"


def test_demo_doc_has_tldr():
    """The TL;DR section is the operator's quick reference."""
    src = _read(DEMO_DOC)
    assert "TL;DR" in src
    assert "make demo" in src or "tools/demo.sh" in src


def test_demo_doc_documents_all_f4_ui_tabs():
    src = _read(DEMO_DOC)
    for tab in (
        "Dashboard",
        "Operate",
        "Observe",
        "Admin",
        "History",
        "Profile",
    ):
        assert tab in src, f"docs/DEMO.md must mention the {tab} tab"


def test_demo_doc_documents_all_demo_scenarios():
    src = _read(DEMO_DOC)
    for scenario in (
        "red-vs-blue-baseline",
        "first-live-drill",
        "phish-to-ransom",
        "lateral-movement-baseline",
    ):
        assert scenario in src, (
            f"docs/DEMO.md must mention the {scenario!r} scenario"
        )


def test_demo_doc_documents_admin_bootstrap():
    """The doc must tell operators how to bootstrap the first admin."""
    src = _read(DEMO_DOC)
    assert "DIVIDE_BOOTSTRAP_ADMIN_SUB" in src
    assert "DIVIDE_BOOTSTRAP_ADMIN_PASSWORD" in src


def test_demo_doc_documents_unsupported_features():
    """The doc must be honest about what the demo doesn't cover
    (multi-VM scenarios that run, scoring, multi-team, etc.)."""
    src = _read(DEMO_DOC)
    for feature in ("F3", "F5", "F6", "F7", "F8"):
        assert feature in src, (
            f"docs/DEMO.md must reference the {feature} roadmap item"
        )


def test_demo_doc_has_troubleshooting_section():
    """A troubleshooting table is required so the operator can
    self-diagnose when something goes wrong."""
    src = _read(DEMO_DOC)
    assert "Troubleshooting" in src
    assert "| Symptom" in src or "| " in src


# ---------- Bundle size invariant ---------------------------------------


def test_demo_runner_does_not_change_bundle():
    """The demo runner is shell + docs only; the portal bundle
    must remain at the F4-UI commit-3 size (~246 KB JS). If a
    future commit accidentally re-builds the portal with new
    assets for the demo, this test fires."""
    build_assets = REPO / "services" / "portal" / "app" / "build" / "assets"
    if not build_assets.is_dir():
        pytest.skip("build/ not present")
    js_files = [a for a in build_assets.glob("*.js") if ".map" not in a.name]
    total = sum(p.stat().st_size for p in js_files)
    # Generous 400 KB budget (F4-UI half-2 budget). Demo runner
    # doesn't add to it.
    assert total < 400 * 1024, (
        f"Bundle grew to {total/1024:.1f} KB — demo runner is shell/docs only"
    )
