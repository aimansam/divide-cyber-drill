"""Schema validation tests for scenario YAML files.

Positive: every shipped example validates.
Negative: each negative case asserts a SPECIFIC error substring so the
test fails loudly if the schema is loosened accidentally.
"""
from __future__ import annotations

import ipaddress
import subprocess
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator, FormatChecker

# ---------------------------------------------------------------------------
# Custom format checkers
#
# jsonschema 4.x does not bundle a "cidr" format checker. We build one from
# the stdlib `ipaddress` module so we can keep "format: cidr" in the schema.
# ---------------------------------------------------------------------------

_format_checker = FormatChecker()


@_format_checker.checks("cidr", raises=ValueError)
def _check_cidr(value: object) -> bool:
    if not isinstance(value, str):
        return True  # let type checks handle non-strings
    ipaddress.ip_network(value, strict=False)
    return True


ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "schemas" / "scenario.schema.json"
EXAMPLES_DIR = ROOT / "examples" / "scenarios"
VALIDATOR_CLI = ROOT / "tools" / "validate_scenario.py"


@pytest.fixture(scope="module")
def schema() -> dict:
    with SCHEMA_PATH.open(encoding="utf-8") as f:
        s = yaml.safe_load(f)
    Draft202012Validator.check_schema(s)
    return s


@pytest.fixture(scope="module")
def validator(schema) -> Draft202012Validator:
    return Draft202012Validator(schema, format_checker=_format_checker)


@pytest.fixture(scope="module")
def example_files() -> list[Path]:
    return sorted(EXAMPLES_DIR.glob("*.scenario.yaml"))


# --- positive ----------------------------------------------------------------


def test_all_examples_exist() -> None:
    assert list(EXAMPLES_DIR.glob("*.scenario.yaml")), "no example scenarios shipped"


def test_examples_validate(validator, example_files) -> None:
    assert example_files, "no example scenarios shipped"
    for f in example_files:
        data = yaml.safe_load(f.read_text())
        errors = list(validator.iter_errors(data))
        assert errors == [], f"{f.name} should be valid, got: {[e.message for e in errors]}"


def test_cli_exits_zero(example_files) -> None:
    result = subprocess.run(
        ["python3", str(VALIDATOR_CLI), *map(str, example_files)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"CLI failed:\n{result.stderr}"


# --- helpers for negative cases ----------------------------------------------


def _minimal_valid() -> dict:
    """Smallest legal Scenario (used as a base; mutate then validate)."""
    return {
        "apiVersion": "divide/v1",
        "kind": "Scenario",
        "metadata": {
            "name": "minimal-valid",
            "title": "Minimal Valid Scenario",
            "version": 1,
            "difficulty": "beginner",
            "duration_min": 30,
        },
        "spec": {
            "objectives": {"red": ["Do the thing."], "blue": ["Spot it."]},
            "assets": [
                {
                    "role": "red_attacker",
                    "kind": "vm",
                    "template": "tpl-kali",
                    "networks": ["corp_vlan"],
                }
            ],
            "networks": [{"name": "corp_vlan", "cidr": "10.0.0.0/24"}],
            "telemetry": {"sinks": [{"type": "stdout"}]},
            "scoring": {
                "blue": {"rules": [{"id": "detection_speed", "weight": 100}], "pass_threshold": 70},
                "red": {"rules": [{"id": "objective_completion", "weight": 100}], "pass_threshold": 50},
            },
            "win_conditions": {"red": ["Compromise the box."], "blue": ["Detect the box."]},
            "artifacts": {"sink_to": "minio", "retention_days": 7},
        },
    }


def _assert_one_error(validator, data: dict, needle: str) -> None:
    errors = list(validator.iter_errors(data))
    assert errors, "expected validation error, got none"
    msgs = " | ".join(e.message for e in errors)
    assert needle in msgs, (
        f"expected error containing {needle!r}, got: {msgs}"
    )


# --- negative ----------------------------------------------------------------


def test_wrong_apiversion(validator) -> None:
    bad = _minimal_valid()
    bad["apiVersion"] = "divide/v2"
    _assert_one_error(validator, bad, "divide/v1")


def test_missing_required_field(validator) -> None:
    bad = _minimal_valid()
    del bad["spec"]["win_conditions"]
    _assert_one_error(validator, bad, "'win_conditions' is a required property")


def test_bad_difficulty_enum(validator) -> None:
    bad = _minimal_valid()
    bad["metadata"]["difficulty"] = "impossible"
    _assert_one_error(validator, bad, "is not one of")


def test_bad_cidr_format(validator) -> None:
    bad = _minimal_valid()
    bad["spec"]["networks"][0]["cidr"] = "not-a-cidr"
    _assert_one_error(validator, bad, "not-a-cidr")


def test_bad_asset_role_pattern(validator) -> None:
    bad = _minimal_valid()
    bad["spec"]["assets"][0]["role"] = "Red Attacker!"
    _assert_one_error(validator, bad, "Red Attacker!")


def test_negative_weight(validator) -> None:
    bad = _minimal_valid()
    bad["spec"]["scoring"]["blue"]["rules"][0]["weight"] = -5
    _assert_one_error(validator, bad, "less than the minimum")


def test_empty_objectives(validator) -> None:
    bad = _minimal_valid()
    bad["spec"]["objectives"]["red"] = []
    _assert_one_error(validator, bad, "should be non-empty")


def test_unknown_top_level_field(validator) -> None:
    bad = _minimal_valid()
    bad["secret_field"] = "shhh"
    _assert_one_error(validator, bad, "Additional properties are not allowed")


def test_unknown_nested_field(validator) -> None:
    bad = _minimal_valid()
    bad["spec"]["networks"][0]["unicorn"] = True
    _assert_one_error(validator, bad, "Additional properties are not allowed")


def test_duplicate_asset_roles(validator) -> None:
    bad = _minimal_valid()
    bad["spec"]["assets"].append({
        "role": "red_attacker",  # duplicate
        "kind": "vm",
        "template": "tpl-kali",
        "networks": ["corp_vlan"],
    })
    _assert_one_error(validator, bad, "has non-unique elements")


def test_retention_out_of_range(validator) -> None:
    bad = _minimal_valid()
    bad["spec"]["artifacts"]["retention_days"] = 99999
    _assert_one_error(validator, bad, "greater than the maximum")
