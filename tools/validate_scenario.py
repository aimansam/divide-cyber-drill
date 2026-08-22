#!/usr/bin/env python3
"""Validate one or more Scenario YAML files against the divide/v1 schema.

Usage:
    python tools/validate_scenario.py <scenario.yaml> [<more.yaml> ...]
    python tools/validate_scenario.py examples/scenarios/

Exit codes:
    0  all files valid
    1  one or more files failed
    2  usage / IO error
"""
from __future__ import annotations

import argparse
import ipaddress
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError, ValidationError

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "schemas" / "scenario.schema.json"

_format_checker = FormatChecker()


@_format_checker.checks("cidr", raises=ValueError)
def _check_cidr(value: object) -> bool:
    if not isinstance(value, str):
        return True
    ipaddress.ip_network(value, strict=False)
    return True


def load_schema() -> dict:
    with SCHEMA_PATH.open(encoding="utf-8") as f:
        schema = yaml.safe_load(f)  # JSON is valid YAML
    Draft202012Validator.check_schema(schema)  # raise if schema itself is bad
    return schema


def _yaml_to_python(path: Path) -> object:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def validate_file(path: Path, validator: Draft202012Validator) -> list[ValidationError]:
    data = _yaml_to_python(path)
    return sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))


def format_error(err: ValidationError, source: Path) -> str:
    path = "$" + "".join(f".{p}" if isinstance(p, str) else f"[{p}]" for p in err.absolute_path)
    msg = err.message.splitlines()[0] if err.message else "validation error"
    return f"  {source}: {path}: {msg}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "inputs",
        nargs="+",
        type=Path,
        help="Scenario YAML files or directories (recursive).",
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true", help="Only print on failure."
    )
    args = parser.parse_args(argv)

    files: list[Path] = []
    for inp in args.inputs:
        if inp.is_dir():
            files.extend(sorted(inp.rglob("*.yaml")))
            files.extend(sorted(inp.rglob("*.yml")))
        elif inp.is_file():
            files.append(inp)
        else:
            print(f"error: {inp} does not exist", file=sys.stderr)
            return 2
    if not files:
        print("error: no .yaml files found", file=sys.stderr)
        return 2

    try:
        schema = load_schema()
    except SchemaError as e:
        print(f"error: schema itself is invalid: {e.message}", file=sys.stderr)
        return 2

    validator = Draft202012Validator(schema, format_checker=_format_checker)
    total_errors = 0
    for f in files:
        errors = validate_file(f, validator)
        if errors:
            total_errors += len(errors)
            print(f"FAIL {f}", file=sys.stderr)
            for e in errors:
                print(format_error(e, f), file=sys.stderr)
        elif not args.quiet:
            print(f"OK   {f}")

    if total_errors:
        print(f"\n{total_errors} error(s) across {len(files)} file(s).", file=sys.stderr)
        return 1
    print(f"\n{len(files)} file(s) validated OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
