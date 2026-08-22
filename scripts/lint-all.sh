#!/usr/bin/env bash
# Run lint + type-check + tests across the repo.
set -euo pipefail

echo "==> ruff check"
ruff check .
echo "==> ruff format check"
ruff format --check .
echo "==> mypy (api)"
(cd services/api && mypy app)
echo "==> pytest (api)"
(cd services/api && pytest)
