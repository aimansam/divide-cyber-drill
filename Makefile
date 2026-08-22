# div:ide Makefile
# Common operations for the control-plane stack.

SHELL := /usr/bin/env bash
COMPOSE := docker compose -f deploy/docker-compose.yml
PYTHON := python3
API_DIR := services/api

.DEFAULT_GOAL := help

.PHONY: help up down logs ps restart build pull lint format test smoke proxmox-ping diag clean validate-scenarios migrate db-upgrade db-downgrade db-revision smoke-run sync-scenarios

help: ## Show this help.
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

build: ## Build all container images.
	$(COMPOSE) build

pull: ## Pull external base images.
	$(COMPOSE) pull

up: ## Start the control-plane stack in the background.
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

lint: ## Run ruff + mypy.
	$(PYTHON) -m ruff check .
	cd $(API_DIR) && $(PYTHON) -m mypy app

format: ## Auto-format with ruff.
	$(PYTHON) -m ruff check --fix .
	$(PYTHON) -m ruff format .

test: ## Run pytest suite.
	$(PYTHON) -m pytest services/api/tests

smoke: ## Curl /healthz and /readyz on the local API.
	@echo "== /healthz =="
	@curl -fsS http://localhost:8000/healthz | $(PYTHON) -m json.tool
	@echo "== /readyz =="
	@curl -fsS http://localhost:8000/readyz | $(PYTHON) -m json.tool || true
	@echo "== /api/v1/scenarios =="
	@curl -fsS http://localhost:8000/api/v1/scenarios | $(PYTHON) -m json.tool

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
