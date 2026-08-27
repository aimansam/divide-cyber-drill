#!/usr/bin/env bash
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
    local method="$1"; local path="$2"; local data="$3"; local extra_h="$4"
    local args=(-s -X "$method" -w "\n__HTTP__%{http_code}" "$API$path" -H "$H_AUTH" --max-time 20)
    [[ -n "$extra_h" ]] && args+=(-H "$extra_h")
    if [[ -n "$data" ]]; then
        args+=(-H 'Content-Type: application/json' -d "$data")
    fi
    local body=$(curl "${args[@]}" 2>&1)
    local http=$(echo "$body" | grep '^__HTTP__' | sed 's/__HTTP__//')
    local json=$(echo "$body" | sed '/^__HTTP__/,$d')
    echo "HTTP=$http"
    echo "$json" | python3 -m json.tool 2>/dev/null || echo "$json"
}

echo "############## Section 2: PVE ground-truth cross-reference ##############"
echo ""
echo "=== 2.1 Direct PVE: /nodes/pve/network ==="
curl -ks "$HOST/api2/json/nodes/pve/network" -H "$H_PVE" | python3 -c "
import json, sys
d = json.load(sys.stdin)
for i in d.get('data', []):
    if i.get('type') == 'bridge':
        print(f'  PVE: {i.get(\"iface\")} addr={i.get(\"address\")} mask={i.get(\"netmask\")} comments=\"{i.get(\"comments\", \"\")}\"')
"
echo ""
echo "=== 2.2 Direct PVE: /cluster/sdn/vnets ==="
curl -ks "$HOST/api2/json/cluster/sdn/vnets" -H "$H_PVE" | python3 -c "
import json, sys
d = json.load(sys.stdin)
for v in d.get('data', []):
    print(f'  PVE: vnet={v.get(\"vnet\")} zone={v.get(\"zone\")}')
"
echo ""
echo "=== 2.3 Direct PVE: /cluster/sdn/zones ==="
curl -ks "$HOST/api2/json/cluster/sdn/zones" -H "$H_PVE" | python3 -c "
import json, sys
d = json.load(sys.stdin)
for z in d.get('data', []):
    print(f'  PVE: zone={z.get(\"zone\")} type={z.get(\"type\")}')
"
echo ""
echo "=== 2.4 Cross-check: API says present=[], PVE says actually present ==="
api_present=$(curl -s $API/api/v1/admin/pve-bridge-status -H "$H_AUTH" | python3 -c "import json, sys; d=json.load(sys.stdin); print(' '.join(sorted(d.get('present', []))))")
pve_bridges=$(curl -ks "$HOST/api2/json/nodes/pve/network" -H "$H_PVE" | python3 -c "
import json, sys
d = json.load(sys.stdin)
bs = sorted([i['iface'] for i in d.get('data', []) if i.get('type') == 'bridge'])
print(' '.join(bs))
")
echo "  API says: $api_present"
echo "  PVE says: $pve_bridges"
if [[ "$api_present" == "$pve_bridges" ]]; then
  echo "  MATCH"
else
  echo "  MISMATCH (BUG!)"
fi
echo ""
echo "############## Section 3: Wizard endpoints ##############"
for ep in probe storage; do
    echo "===== GET /api/v1/admin/$ep ====="
    run GET "/api/v1/admin/$ep"
    echo ""
done

echo "############## Section 4: Action endpoints ##############"
echo ""
echo "===== POST /api/v1/admin/pve-setup-bridges (idempotent re-run) ====="
run POST "/api/v1/admin/pve-setup-bridges" '{}'
echo ""
echo "===== DELETE /scenarios/<name> / restore ====="
# Find an active scenario
active=$(curl -s $API/api/v1/scenarios -H "$H_AUTH" | python3 -c "
import json, sys
d = json.load(sys.stdin)
for s in d.get('items', []):
    if not s.get('archived_at'):
        print(s.get('name'))
        break
")
echo "Archiving + restoring: $active"
echo "--- DELETE:"
run DELETE "/api/v1/scenarios/$active"
echo ""
echo "--- POST restore:"
run POST "/api/v1/scenarios/$active/restore"
echo ""

echo "############## Section 5: Error paths ##############"
echo ""
echo "===== 5.1 GET /pve-bridge-status with NO auth ====="
out=$(curl -s -w "\n__HTTP__%{http_code}" "$API/api/v1/admin/pve-bridge-status" --max-time 5 2>&1)
echo "HTTP=$(echo "$out" | grep '^__HTTP__' | sed 's/__HTTP__//')"
echo "$out" | sed '/^__HTTP__/,$d'
echo ""
echo "===== 5.2 GET /admin/<bogus> ====="
out=$(curl -s -w "\n__HTTP__%{http_code}" "$API/api/v1/admin/totally-nonexistent" \
    -H "$H_AUTH" --max-time 5 2>&1)
echo "HTTP=$(echo "$out" | grep '^__HTTP__' | sed 's/__HTTP__//')"
echo "$out" | sed '/^__HTTP__/,$d'
echo ""
echo "===== 5.3 GET /v1/admin/probe - non-admin role tries ====="
non_admin=$(docker exec divide-api python3 -c "
import sys; sys.path.insert(0, '/app')
from app.core import auth
print(auth.sign_token('analyst', 'lead', 3600))
")
out=$(curl -s -w "\n__HTTP__%{http_code}" "$API/api/v1/admin/probe" \
    -H "X-Divide-Token: $non_admin" --max-time 5 2>&1)
echo "HTTP=$(echo "$out" | grep '^__HTTP__' | sed 's/__HTTP__//')"
echo "$out" | sed '/^__HTTP__/,$d'
