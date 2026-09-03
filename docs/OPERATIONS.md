# Operations & Runbook

This guide covers routine platform administration, user management, CLI execution, live drill lifecycles, and troubleshooting.

---

## 1. User & Identity Management

div:ide uses argon2id password hashing and Bearer/API token authorization.

### Default Built-in Roles
| Role | Permissions |
|---|---|
| **admin** | Full cluster control, user provisioning, PVE connection settings, template deletion |
| **lead** | Scenario upload, exercise creation, drill start/stop/reset, debrief export |
| **red** / **blue** | View assigned assets, connect to noVNC consoles, submit flags, view telemetry |
| **observer** | Read-only view of live leaderboard, SOC timeline, and debrief reports |

### Managing Users via CLI

```bash
# Create or reset an operator password
docker compose exec api python -m src.identity.cli create-user \
  --username operator \
  --password "SecurePass123!" \
  --role lead

# Mint a long-lived API token for CI/CD or automation
docker compose exec api python tools/issue_token.py \
  --user admin \
  --role admin \
  --ttl 8760h
```

---

## 2. Live Drill Operations

### Starting a Drill (Web UI)
1. Log in to `/`
2. Navigate to **Operate** tab
3. Select your scenario (e.g. `Red vs Blue Baseline`)
4. Click **Start Drill**
5. Switch to **Observe** tab to watch asset provisioning and live telemetry

### Starting a Drill (CLI / API)

```bash
# Start a single-team run
curl -s -X POST http://localhost:8000/api/v1/drills \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"scenario_id": "scenario-rvb-01", "name": "Sprint 4 Drill"}'

# Submit a flag
curl -s -X POST http://localhost:8000/api/v1/drills/42/submit-flag \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"flag_id": "flag-root-compromise", "value": "DIVIDE{root_fs_captured_992a}"}'

# Reset the drill environment
curl -s -X POST http://localhost:8000/api/v1/drills/42/reset \
  -H "Authorization: Bearer $TOKEN"
```

---

## 3. End-to-End Demo Script

To run an automated test drill demonstrating provisioning, scoring, and teardown:

```bash
# Run the end-to-end automated demo
./tools/demo.sh

# Or follow live streaming events in the terminal
python tools/watch_drill.py --drill-id latest
```

---

## 4. Maintenance & Troubleshooting

### VM Provisioning Fails or Timeouts
- **Check PVE Storage**: Ensure target storage pool (e.g. `local-lvm` or `ceph`) has sufficient free space.
- **Check PVE Permissions**: Run `python tools/preflight.py` to confirm API token has VM allocate and SDN permissions.
- **Watchdog Cleanup**: Stuck runs past TTL are automatically recovered and cleaned up by the background watchdog worker.

### Inspecting Logs
```bash
# API Server logs
docker compose logs -f api

# Runner Worker logs
docker compose logs -f runner

# Database & Event Bus
docker compose logs -f db redis
```
