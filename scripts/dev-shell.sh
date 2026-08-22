#!/usr/bin/env bash
# Open a shell in the running API container with the correct PYTHONPATH.
set -euo pipefail
docker compose -f deploy/docker-compose.yml exec api /bin/bash "$@"
