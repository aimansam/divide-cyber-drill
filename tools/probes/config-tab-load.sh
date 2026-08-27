#!/usr/bin/env bash
# Probe all portal endpoints + cross-reference with PVE ground truth.
TOKEN=$(docker exec divide-api python3 -c "
import sys; sys.path.insert(0, '/app')
from app.core import auth
print(auth.sign_token('admin', 'admin', 3600))
")
HOST="https://192.168.0.10:8006"
PVE_TOK="divide@pve@pam!drill-token=4ea3414f-d3a4-47b5-a2ed-19018f416cc0"
API="http://localhost:8000"
H_AUTH="X-Divide-Token: $TOKEN"
H_PVE="Authorization: PVEAPIToken=$PVE_TOK"

run() {
    local method="$1"; local path="$2"; local data="$3"
    local body
    if [[ -n "$data" ]]; then
        body=$(curl -s -X "$method" -w "\n__HTTP__%{http_code}" "$API$path" \
            -H "$H_AUTH" -H 'Content-Type: application/json' -d "$data" --max-time 15 2>&1)
    else
        body=$(curl -s -X "$method" -w "\n__HTTP__%{http_code}" "$API$path" \
            -H "$H_AUTH" --max-time 15 2>&1)
    fi
    local http=$(echo "$body" | grep '^__HTTP__' | sed 's/__HTTP__//')
    local json=$(echo "$body" | sed '/^__HTTP__/,$d')
    echo "HTTP=$http"
    echo "$json" | python3 -m json.tool 2>/dev/null || echo "$json"
}

echo "############## 1: Config tab initial load ##############"
for ep in pve-config pve-sdn-status pve-bridge-status drill-template-status service-status expected-bridges; do
    echo "===== GET /api/v1/admin/$ep ====="
    run GET "/api/v1/admin/$ep"
    echo ""
done
