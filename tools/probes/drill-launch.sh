#!/usr/bin/env bash
TOKEN=$(docker exec divide-api python3 -c "
import sys; sys.path.insert(0, '/app')
from app.core import auth
print(auth.sign_token('admin', 'admin', 3600))
")
API="http://localhost:8000"
H_AUTH="X-Divide-Token: $TOKEN"

echo "############## Section 6: Drill flow ##############"
echo ""
echo "=== 6.1 GET /v1/scenarios (list) ==="
out=$(curl -s -w "\n__HTTP__%{http_code}" "$API/api/v1/scenarios" \
    -H "$H_AUTH" --max-time 5 2>&1)
http=$(echo "$out" | grep '^__HTTP__' | sed 's/__HTTP__//')
echo "HTTP=$http"
echo "$out" | sed '/^__HTTP__/,$d' | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(f'  total={d.get(\"total\")} items in list')
for s in d.get('items', []):
    print(f'  - {s.get(\"name\")} (archived={bool(s.get(\"archived_at\"))})')
"
echo ""

echo "=== 6.2 GET /v1/drills (list) ==="
out=$(curl -s -w "\n__HTTP__%{http_code}" "$API/api/v1/drills" \
    -H "$H_AUTH" --max-time 5 2>&1)
http=$(echo "$out" | grep '^__HTTP__' | sed 's/__HTTP__//')
echo "HTTP=$http"
echo "$out" | sed '/^__HTTP__/,$d' | head -c 400
echo ""
echo ""

echo "=== 6.3 POST /admin/start-first-drill (full drill launch) ==="
echo "(This will actually clone a VM and start it -- takes ~30s)"
out=$(curl -s -w "\n__HTTP__%{http_code}" -X POST "$API/api/v1/admin/start-first-drill" \
    -H "$H_AUTH" -H 'Content-Type: application/json' -d '{}' \
    --max-time 60 2>&1)
http=$(echo "$out" | grep '^__HTTP__' | sed 's/__HTTP__//')
echo "HTTP=$http"
echo "$out" | sed '/^__HTTP__/,$d' | python3 -m json.tool 2>/dev/null | head -40 || echo "$out" | sed '/^__HTTP__/,$d'
echo ""

echo "=== 6.4 GET /v1/drills (after launch) ==="
out=$(curl -s -w "\n__HTTP__%{http_code}" "$API/api/v1/drills" \
    -H "$H_AUTH" --max-time 5 2>&1)
http=$(echo "$out" | grep '^__HTTP__' | sed 's/__HTTP__//')
echo "HTTP=$http"
echo "$out" | sed '/^__HTTP__/,$d' | python3 -c "
import json, sys
d = json.load(sys.stdin)
items = d.get('items', [])
print(f'  total drills: {len(items)}')
for d in items[:3]:
    print(f'  - id={d.get(\"id\")} state={d.get(\"state\")} scenario={d.get(\"scenario\")}')"
echo ""
