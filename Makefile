# div:ide Makefile
# Common operations for the control-plane stack.

SHELL := /usr/bin/env bash
COMPOSE := docker compose -f deploy/docker-compose.yml
PYTHON := python3
API_DIR := services/api

.DEFAULT_GOAL := help

.PHONY: help up down logs ps restart build pull lint format test test-live-pg smoke proxmox-ping diag clean validate-scenarios migrate db-upgrade db-downgrade db-revision smoke-run sync-scenarios upload-template live-drill demo demo-open portal-build portal-watch portal-install verify-bundle pve-bridge-status pve-setup-bridges

help: ## Show this help.
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

build: ## Build all container images.
	$(COMPOSE) build

pull: ## Pull external base images.
	$(COMPOSE) pull

up: portal-build ## Start the control-plane stack in the background.
	$(COMPOSE) up -d
	@echo "Waiting for /healthz ..."
	@for i in $$(seq 1 30); do \
		if curl -fsS http://localhost:8000/healthz >/dev/null 2>&1; then \
			echo "  ok (after $$i s)"; exit 0; \
		fi; \
		sleep 1; \
	done; \
	echo "  api did not become healthy in 30 s — run 'make logs'"; exit 1

down: ## Stop the control-plane stack (keeps volumes).
	$(COMPOSE) down

logs: ## Tail logs from all services.
	$(COMPOSE) logs -f --tail=100

ps: ## Show running services.
	$(COMPOSE) ps

restart: ## Restart the API container only.
	$(COMPOSE) restart api

# --- fresh-clone: wipe non-source state and re-run the day-1 path -----
# Drops docker volumes, removes node_modules + portal/build, removes the
# API image so it picks up code edits. Source tree is preserved.
#
# Designed to reproduce what a fresh ``git clone`` operator would
# experience, then walk them through the day-1 setup. Pair with the
# `verify-bundle` + `test` targets to confirm everything is green.
#
# SAFETY: this is destructive. Requires an explicit YES.
fresh-clone: ## Wipe non-source state to simulate a fresh git clone (destructive).
	@if [[ "$(FORCE)" != "1" ]]; then \
		echo "fresh-clone is destructive. Re-run with FORCE=1 to proceed."; \
		exit 1; \
	fi
	@echo "--- 1. Stop containers + drop state volumes ---"
	$(COMPOSE) down --remove-orphans || true
	docker volume rm divide-cyber-drill_postgres-data \
	                   divide-cyber-drill_grafana-data \
	                   divide-cyber-drill_minio-data \
	                   divide-cyber-drill_prometheus-data \
	                   divide-cyber-drill_redis-data \
	                   divide-cyber-drill_traefik-letsencrypt \
	                   divide-cyber-drill_wg-easy-data 2>/dev/null || true
	@echo "--- 2. Remove API image (forces rebuild from source) ---"
	docker rmi divide/api:dev 2>/dev/null || true
	@echo "--- 3. Delete node_modules + portal/build ---"
	rm -rf services/portal/app/node_modules
	rm -rf services/portal/app/build
	@echo "--- 4. Wipe __pycache__ + dev caches ---"
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache services/api/.pytest_cache .ruff_cache
	@echo "--- 5. Wipe operator-edited deploy/.env (NOT .env.example) ---"
	rm -f deploy/.env
	@echo ""
	@echo "=== fresh-clone complete ==="
	@echo "Now configure deploy/.env from deploy/.env.example and run:"
	@echo "  cp deploy/.env.example deploy/.env"
	@echo "  # edit deploy/.env: DIVIDE_BOOTSTRAP_ADMIN_*, PROXMOX_*, MINIO_ROOT_PASSWORD, etc."
	@echo "  make up"

lint: ## Run ruff + mypy.
	$(PYTHON) -m ruff check .
	cd $(API_DIR) && $(PYTHON) -m mypy app

format: ## Auto-format with ruff.
	$(PYTHON) -m ruff check --fix .
	$(PYTHON) -m ruff format .

test: ## Run pytest suite.
	$(PYTHON) -m pytest services/api/tests tests

# ----- React/Vite user portal (services/portal/app) ----------------------
# The portal/app/ tree is a separate Vite project; it has its own
# package.json and ships pre-built assets into services/portal/app/build/
# which FastAPI mounts at /portal/app/. Build before `make up` (or
# `make verify`) so the mount serves real bytes; use `portal-watch`
# in another terminal for the dev loop.
portal-build: ## Build the React/Vite user portal bundle into services/portal/app/build/.
	cd services/portal/app && npm ci --no-audit --no-fund && npm run build

portal-watch: ## Run Vite in watch mode for the user portal (HMR).
	cd services/portal/app && npm run dev

portal-install: ## Install npm deps for services/portal/app/.
	cd services/portal/app && npm ci --no-audit --no-fund

# F9.3: bundle-budget guard. Builds the portal and fails if the
# resulting JS bundle exceeds the budget ceiling set in F4 (and
# adjusted in F-pve-config-ui). The ceiling is enforced here + in
# CI so a runaway dep can't silently double the bundle.
#
# History:
#   F4:        280 KB  (5-step wizard)
#   F-pve-config-ui: 320 KB (6-step wizard with PveCredentialsStep +
#                  PVE config API client. The extra 40 KB is mostly
#                  the new React component + 3 small API helpers in
#                  api.ts; not a dependency regression.)
verify-bundle: portal-build ## Fail if the portal bundle exceeds the budget.
	@BUNDLE=$$(ls -1 services/portal/app/build/assets/index-*.js 2>/dev/null | head -1); \
	if [[ -z "$$BUNDLE" ]]; then echo "no bundle found; run \`make portal-build\` first"; exit 2; fi; \
	KB=$$(python3 -c "import os,sys; print(f'{os.path.getsize(sys.argv[1])/1024:.2f}')" "$$BUNDLE"); \
	LIMIT_KB=320.00; \
	echo "bundle: $$KB KB (limit $$LIMIT_KB KB)"; \
	if python3 -c "import sys; sys.exit(0 if float(sys.argv[1]) <= float(sys.argv[2]) else 1)" "$$KB" "$$LIMIT_KB"; then \
		echo "OK: bundle within budget"; \
	else \
		echo "FAIL: bundle $$KB KB exceeds $$LIMIT_KB KB budget"; exit 1; \
	fi

test-live-pg: ## Run live_pg tests against a real PostgreSQL (requires DIVIDE_TEST_LIVE_PG + reachable DB).
	@test -n "$$DIVIDE_TEST_LIVE_PG" || { echo "Set DIVIDE_TEST_LIVE_PG=1 (and optionally DIVIDE_TEST_LIVE_PG_URL)"; exit 2; }
	$(PYTHON) -m pytest -m live_pg services/api/tests

smoke: ## Curl /healthz and /readyz on the local API.
	@echo "== /healthz =="
	@curl -fsS http://localhost:8000/healthz | $(PYTHON) -m json.tool
	@echo "== /readyz =="
	@curl -fsS http://localhost:8000/readyz | $(PYTHON) -m json.tool || true
	@echo "== /api/v1/scenarios =="
	@curl -fsS http://localhost:8000/api/v1/scenarios | $(PYTHON) -m json.tool

verify: ## Aggregate gate: lint + test + preflight + smoke + bundle-budget. Use before push / in CI.
	@echo "=== make verify = 1/5 lint ==="
	$(MAKE) lint
	@echo "=== make verify = 2/5 test ==="
	$(MAKE) test
	@echo "=== make verify = 3/5 preflight (PVE health; non-fatal if PVE unreachable) ==="
	-$(MAKE) preflight || { echo "preflight reported NOT READY (see output above) -- continuing"; }
	@echo "=== make verify = 4/5 smoke ==="
	$(MAKE) smoke
	@echo "=== make verify = 5/5 bundle-budget ==="
	$(MAKE) verify-bundle

proxmox-ping: ## Run the Proxmox smoke test (requires env vars).
	cd $(API_DIR) && $(PYTHON) scripts/proxmox-smoke.py

diag: ## Print diagnostic info (versions, IPs, running containers).
	@echo "== docker =="
	@docker version --format '{{.Server.Version}}' 2>&1 | head -1
	@echo "== compose =="
	@$(COMPOSE) version 2>&1 | head -1
	@echo "== python =="
	@$(PYTHON) --version
	@echo "== host =="
	@hostname
	@ip -4 addr show | awk '/inet /{print $$2}' | head
	@echo "== stack =="
	@$(COMPOSE) ps --services

clean: ## Stop stack and remove build artifacts (volumes preserved).
	$(COMPOSE) down --remove-orphans
	rm -rf $(API_DIR)/.pytest_cache $(API_DIR)/.mypy_cache $(API_DIR)/.ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

validate-scenarios: ## Validate all scenario YAML files against divide/v1 schema.
	$(PYTHON) tools/validate_scenario.py examples/scenarios/ scenarios/

sync-scenarios: ## Sync scenario YAML files into the DB (DIVIDE_DB_URL required).
	DIVIDE_DB_URL=sqlite+aiosqlite:///./divide.db PYTHONPATH=$(API_DIR) $(PYTHON) tools/sync_scenarios.py

upload-template: ## Upload + register a cloud-init VM template on PVE. Args: NAME=... ISO=local:iso/...
	@test -n "$$NAME" || { echo "Usage: make upload-template NAME=tpl-debian-cloudinit ISO=local:iso/debian-XX-netinst.iso"; exit 2; }
	@test -n "$$ISO" || { echo "Set ISO=local:iso/<file>.iso (the Debian netinst ISO already on PVE is fine)"; exit 2; }
	$(COMPOSE) exec api python /workdir/tools/upload_cloudinit_template.py --name "$$NAME" --iso "$$ISO"

preflight: ## Verify all pre-conditions for `make live-drill` (PVE ACL, template, scenario, /metrics, Prometheus, Grafana).
	@SCENARIO=$${SCENARIO:-first-live-drill}; \
	TEMPLATE=$${TEMPLATE:-tpl-debian-cloudinit}; \
	$(PYTHON) tools/preflight.py --scenario "$$SCENARIO" --template "$$TEMPLATE"

live-drill: ## Run a drill end-to-end against live PVE. Args: SCENARIO=first-live-drill TIMEOUT=300.
	@SCENARIO=$${SCENARIO:-first-live-drill}; \
	$(COMPOSE) exec api python /workdir/tools/live_drill.py --scenario "$$SCENARIO" --timeout $${TIMEOUT:-300}

verify-drill: ## Verify the most recent (or RUN_ID=N) drill against expected status. Args: RUN_ID= RUN_EXPECT=succeeded RUN_JSON=1.
	$(PYTHON) tools/verify_drill.py --expect $${RUN_EXPECT:-succeeded} $${RUN_ID:+--run-id $$RUN_ID} $${RUN_JSON:+--json} $${RUN_NO_DESTROY:+--no-destroyed-check}

watch-drill: ## Watch the next drill via Prometheus; exits when outcome moves. Args: OUTCOME=succeeded CANCEL_AFTER=...
	@OUTCOME=$${OUTCOME:-succeeded}; \
	$(PYTHON) tools/watch_drill.py --outcome "$$OUTCOME" $${CANCEL_AFTER:+--cancel-after $$CANCEL_AFTER} --timeout $${TIMEOUT:-600}

live-cancel: ## Start a drill, then cancel it after N seconds. Args: SCENARIO=first-live-drill CANCEL_AFTER=30.
	@SCENARIO=$${SCENARIO:-first-live-drill}; \
	echo "1) starting drill..."; \
	$(COMPOSE) exec -T api python /workdir/tools/live_drill.py --scenario "$$SCENARIO" --timeout 5 --no-stop || true; \
	echo "2) watching + cancelling after $${CANCEL_AFTER:-30}s..."; \
	$(PYTHON) tools/watch_drill.py --scenario "$$SCENARIO" --cancel-after $${CANCEL_AFTER:-30} --outcome cancelled --timeout $${TIMEOUT:-120}

smoke-run: ## End-to-end smoke (in-memory DB + MockProxmoxAdapter).
	PYTHONPATH=$(API_DIR) $(PYTHON) tools/run_smoke.py

# --- database migrations ----------------------------------------------------

ALEMBIC := cd $(API_DIR) && alembic --config alembic.ini

migrate: db-upgrade ## Alias for `make db-upgrade`.

db-upgrade: ## Apply all pending migrations to head.
	$(ALEMBIC) upgrade head

db-downgrade: ## Roll back the most recent migration.
	$(ALEMBIC) downgrade -1

db-revision: ## Create a new migration (use msg=...). Requires autogenerate setup.
	$(ALEMBIC) revision --autogenerate -m "$(msg)"

demo: ## Run the F4-UI demo runner (one-command bootstrap).
	@bash tools/demo.sh

demo-open: ## Demo runner that also tries to open the portal in a browser.
	@bash tools/demo.sh --open

# --- F-pve-bridge-wizard (SDN variant): PVE bridge provisioning -------
# The wizard's Step 0 is the day-1 default; these targets let ops
# who can't use the UI check status + apply. Both targets shell
# out to the API directly via curl -- there's no longer a Python
# CLI helper because the wizard handles all SSH/SDN paths itself.

DIVIDE_API_BASE ?= http://localhost:8000
DIVIDE_ADMIN_TOKEN ?= $(shell $(PYTHON) tools/issue_token.py --user admin --role admin --ttl 1h 2>/dev/null || echo '')

pve-bridge-status: ## Show which F3 bridges the runner needs vs. what's on PVE (dry-run safe).
	@if [[ -z "$(DIVIDE_ADMIN_TOKEN)" ]]; then echo "Set DIVIDE_ADMIN_TOKEN or run via the wizard"; exit 2; fi
	@curl -s $(DIVIDE_API_BASE)/api/v1/admin/pve-bridge-status \
		-H "X-Divide-Token: $(DIVIDE_ADMIN_TOKEN)" | $(PYTHON) -m json.tool

pve-setup-bridges: ## Create the F3 bridges via PVE SDN (no SSH). Uses creds from pve_config or env.
	@if [[ -z "$(DIVIDE_ADMIN_TOKEN)" ]]; then echo "Set DIVIDE_ADMIN_TOKEN or run via the wizard"; exit 2; fi
	@curl -s -X POST $(DIVIDE_API_BASE)/api/v1/admin/pve-setup-bridges \
		-H "X-Divide-Token: $(DIVIDE_ADMIN_TOKEN)" \
		-H "Content-Type: application/json" \
		-d '{"dry_run": false}' | $(PYTHON) -m json.tool
