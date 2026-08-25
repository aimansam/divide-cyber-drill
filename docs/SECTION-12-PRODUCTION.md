# Section 18.5 — F12.3: Production deployment

> **Status:** F12.3 shipped. `deploy/docker-compose.production.yaml`
> is a production-grade Compose file with TLS termination,
> multi-worker uvicorn, Redis required, Authentik in production
> mode, JSON logging, resource limits, and tight healthchecks.

## What F12.3 ships

A new file `deploy/docker-compose.production.yaml` that brings up
a single-tenant production deployment on a Docker host with:

  * **Traefik** in front of the API with Let's Encrypt TLS.
    Public ingress on :443 with HTTP→HTTPS redirect.
  * **Multi-worker uvicorn** (4 workers). R1's Redis pub/sub
    makes SSE work across all of them.
  * **Redis required** (`DIVIDE_EVENT_BUS=redis`). Multi-worker
    fan-out is mandatory in prod.
  * **Authentik in production mode** (separate `authentik-server`
    + `authentik-worker` containers + dedicated Postgres) for
    SSO.
  * **Postgres with AOF on** for Redis (durable cache + rate-
    limit buckets).
  * **JSON file logging** with rotation (20 MB × 5 files per
    service). Suitable for shipping to Loki / CloudWatch /
    Datadog.
  * **Resource limits** on every service.
  * **Tight healthchecks** (10 s intervals, 5 s timeouts, 5
    retries, 30 s start period).
  * **All secrets via env vars** -- no defaults. Production
    deployments must supply strong random values for every
    `*_PASSWORD` + `DIVIDE_TOKEN_SECRET`.

The dev compose (`deploy/docker-compose.yml`) is unchanged --
F12.3 adds a parallel production file rather than forking
the dev one.

## Quickstart

```bash
# 1. Build the production API image (one-time).
docker build -t divide/api:latest -f services/api/Dockerfile .

# 2. Generate strong random secrets.
cat > deploy/.env.production <<EOF
POSTGRES_PASSWORD=$(openssl rand -hex 32)
MINIO_ROOT_USER=divide
MINIO_ROOT_PASSWORD=$(openssl rand -hex 32)
DIVIDE_TOKEN_SECRET=$(openssl rand -hex 32)
AUTHENTIK_SECRET_KEY=$(openssl rand -hex 32)
AUTHENTIK_BOOTSTRAP_PASSWORD=$(openssl rand -hex 16)
AUTHENTIK_BOOTSTRAP_EMAIL=admin@divide.example.com
AUTHENTIK_POSTGRESQL_PASSWORD=$(openssl rand -hex 32)
DIVIDE_BOOTSTRAP_ADMIN_SUB=alice
DIVIDE_BOOTSTRAP_ADMIN_PASSWORD=$(openssl rand -hex 16)
PROXMOX_HOST=pve.example.com
PROXMOX_TOKEN_ID=divide@pve!div-api
PROXMOX_TOKEN_SECRET=<from PVE>
ACME_EMAIL=ops@example.com
PUBLIC_HOSTNAME=divide.example.com
DIVIDE_API_TAG=latest
EOF

# 3. Bring up the stack.
docker compose -f deploy/docker-compose.production.yaml \
  --env-file deploy/.env.production up -d

# 4. Verify the stack is healthy.
docker compose -f deploy/docker-compose.production.yaml ps
curl -fsS https://divide.example.com/healthz
```

## Required env vars

| Var | Source | Notes |
|---|---|---|
| `POSTGRES_PASSWORD` | `openssl rand -hex 32` | div:ide app DB |
| `MINIO_ROOT_PASSWORD` | `openssl rand -hex 32` | artifact store |
| `DIVIDE_TOKEN_SECRET` | `openssl rand -hex 32` | HMAC token signing key. **Not the same as `PROXMOX_TOKEN_SECRET`.** |
| `PROXMOX_TOKEN_ID` | PVE → Datacenter → API Tokens | `<user>@<realm>!<tokenid>` |
| `PROXMOX_TOKEN_SECRET` | PVE → API Tokens | UUID-ish secret from PVE |
| `AUTHENTIK_SECRET_KEY` | `openssl rand -hex 32` | Authentik secret key |
| `AUTHENTIK_BOOTSTRAP_PASSWORD` | `openssl rand -hex 16` | Authentik initial admin password |
| `AUTHENTIK_POSTGRESQL_PASSWORD` | `openssl rand -hex 32` | Authentik DB password |
| `DIVIDE_BOOTSTRAP_ADMIN_SUB` | Operator-chosen | First div:ide admin username |
| `DIVIDE_BOOTSTRAP_ADMIN_PASSWORD` | `openssl rand -hex 16` | First div:ide admin password |
| `ACME_EMAIL` | Operator email | Let's Encrypt registration contact |
| `PUBLIC_HOSTNAME` | DNS A record | Public hostname the deployment serves |
| `DIVIDE_API_TAG` | (optional) | Image tag (default `latest`) |

> **Important:** `DIVIDE_BOOTSTRAP_ADMIN_SUB` + `DIVIDE_BOOTSTRAP_ADMIN_PASSWORD`
> are also accepted by the API's `POST /api/v1/auth/setup` endpoint
> (the F10 first-admin bootstrap). For a single-deployment rollout,
> the env-var path is simpler. For multi-admin rollouts where the
> first admin is created by a human via the wizard, leave both
> env vars unset.

## How multi-worker SSE works in prod

R1's Redis bus is what makes multi-worker production deployable
without losing SSE events:

```
   worker A (uvicorn)                worker B (uvicorn)
   +----------------+                +----------------+
   | RedisEventBus  |                | RedisEventBus  |
   | (sync client)  |                | (sync client)  |
   +-------+--------+                +-------+--------+
           |                                  |
           | LPUSH/LTRIM/PUBLISH              |
           v                                  v
   +----------------------------------------------------+
   | Redis (AOF enabled)                               |
   |   LIST divide:events:buffer   (1024-entry ring)    |
   |   CHAN divide:events:global   (pub/sub fan-out)    |
   +----------------------------------------------------+
                                ^
                                | SUBSCRIBE
                                |
              bridge thread in each worker:
              asyncio loop + redis.asyncio pubsub
              -> forwards into per-subscriber queue.Queue
```

Both workers' SSE handlers see the same event stream. See
[`docs/R1-MULTIWORKER.md`](R1-MULTIWORKER.md) for the full design +
failure modes + observability notes.

## TLS / public ingress

Traefik fronts the API on `:443` with a Let's Encrypt cert.
The HTTP→HTTPS redirect runs on `:80` (ACME HTTP-01 challenge
needs :80 reachable). 

The api container exposes only `:8000` internally -- no host
port is published. Traefik reaches the API via the
`divide-net` Docker network.

The dashboard (`/dashboard/...`) is on the same public
hostname but a separate path; an `auth` middleware placeholder
is included so the operator can wire in basic-auth / OIDC
later.

## Logging

Every service ships with the `json-file` log driver, 20 MB
max per file, 5 files retained. That's ~100 MB per service
of structured JSON logs.

```bash
# Tail the api logs.
docker compose -f deploy/docker-compose.production.yaml logs -f --tail=100 api

# Ship to Loki:
docker plugin install grafana/loki-docker-driver:latest --alias loki --grant-all-permissions
# then set LOG_DRIVER=loki in .env.production
```

For CloudWatch / Datadog, swap the logging driver in the
compose file (one-liner per service).

## Resource limits

| Service | CPU limit | Memory limit |
|---|---|---|
| api (4 workers) | 4 | 4 GB |
| postgres | 2 | 2 GB |
| redis | 1 | 1 GB |
| minio | 2 | 2 GB |
| traefik | 1 | 512 MB |
| authentik-server | 2 | 2 GB |
| authentik-worker | 2 | 2 GB |
| authentik-postgres | (default) | (default) |

Total: ~16 vCPU + 13 GB. Tune based on your drill workload:
heavy multi-team exercises (4 VMs × 4 teams) benefit from
more api CPU + more postgres memory.

## Backup

  * **Postgres**: nightly `pg_dump` to a separate volume +
    ship to S3. The `postgres-data` named volume is the
    critical piece of state.
  * **Redis**: AOF file is durable but ephemeral cache --
    rate-limit buckets can rebuild. Backup not critical.
  * **Minio**: artifact store. Back up the `divide-artifacts`
    bucket nightly; the artifacts are the only thing an
    after-action report references that isn't in Postgres.
  * **Traefik certs**: the `traefik-letsencrypt` volume has
    the ACME account + issued certs. Don't lose it -- a
    rebuild re-issues certs, but that takes 60-90 s of downtime.

## Migration from dev compose

```bash
# 1. Stop the dev stack.
make down

# 2. Dump the dev DB so the prod stack has the same data.
docker compose -f deploy/docker-compose.yml exec postgres \
  pg_dump -U divide divide > dump.sql

# 3. Bring up the prod stack -- the api image is built fresh,
#    so the API starts on an empty Postgres. Restore the dump.
docker compose -f deploy/docker-compose.production.yaml \
  --env-file deploy/.env.production up -d -V
docker compose -f deploy/docker-compose.production.yaml \
  exec -T postgres psql -U divide -d divide < dump.sql
```

## What F12.3 is NOT

  * **No HA / multi-host.** This is a single-node deployment.
    For HA, run two stacks behind a load balancer with a
    shared Postgres + Redis. R1's Redis bus works across hosts.
  * **No Prometheus / Grafana.** The dev compose has them; the
    prod compose is intentionally minimal. Wire them in via a
    separate `docker-compose.observability.yaml` (TODO post-F12).
  * **No Wazuh integration.** Phase 3 work; see PLAN.md.
  * **No automated certificate rotation beyond Let's Encrypt's
    default 60-day renewal.** Traefik handles renewal
    automatically; no operator action needed.

## See also

  * [`docs/R1-MULTIWORKER.md`](R1-MULTIWORKER.md) — R1 Redis
    pub/sub. The reason the prod compose requires
    `DIVIDE_EVENT_BUS=redis`.
  * [`docs/SECTION-10-ONBOARDING.md`](SECTION-10-ONBOARDING.md)
    — F10 onboarding wizard. The first-admin UX that the
    prod compose's env-var bootstrap path parallels.
  * [`docs/PROXMOX-SETUP.md`](PROXMOX-SETUP.md) — Proxmox API
    token + ACL setup.
  * [`docs/SETUP-UI.md`](SETUP-UI.md) — Dev-mode setup wizard
    at `/portal/` (used to stand up the very first deployment).
