# Portal end-to-end probe scripts

These bash scripts hit every endpoint the portal's Config tab + wizard
calls, against a running `divide-api` container. They also cross-reference
direct PVE API calls to confirm the API reports ground truth.

## Usage

```bash
# From the repo root, after `make up`:
./tools/probes/config-tab-load.sh      # just the Config tab 6 endpoints
./tools/probes/full-flow.sh             # + wizard + error paths
./tools/probes/drill-launch.sh          # + drill start (slow, ~30s)
```

Each script:
- mints an admin token via `docker exec divide-api sign_token(...)`
- hits every endpoint with the correct `X-Divide-Token` header
- cross-references PVE via direct `curl` to the PVE host
- prints status codes + JSON bodies for each call
- asserts shape consistency (e.g. `ready: true` on bridge status)

## What they found (Q14)

1. **Bug**: `POST /admin/start-first-drill` calls itself in a loopback
   HTTP request but doesn't forward the auth token → returns
   doubly-nested `{"detail":"{\"detail\":\"...\"}"}`.

2. **Bug**: `POST /api/v1/drills` against real PVE leaks an
   `sqlalchemy.exc.IntegrityError` (FK violation on assets.run_id)
   as a raw 500 instead of mapping it to a 502 via Q7-style error
   handling. The router's `except` chain doesn't catch
   `IntegrityError`.

3. **Bug**: many error paths return text/plain "Internal Server
   Error" instead of structured JSON, because global exception
   handlers aren't installed.
