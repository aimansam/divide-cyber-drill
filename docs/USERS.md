# div:ide Users — Operator Guide

> **Status:** F3-prep complete (commit `78bc332` + `b603c40`).
> **Audience:** platform operators (admin) and the curious.

## What is F3-prep?

F3-prep replaces div:ide's "paste your token" UX with a real
**username + password → HMAC token** flow. The portal now ships a
sign-in screen; the operator types `alice` / `hunter2` and is in.

The token it mints is the **same HMAC-SHA256 token** that
`tools/issue_token.py` always minted. The difference is how the
caller proves their identity to get one:

| Path                  | Identity proof                          | Used by             |
|-----------------------|-----------------------------------------|---------------------|
| `tools/issue_token.py`| SSH session (operator trust)            | SSH operators       |
| `POST /auth/login`    | argon2id password hash in `users` table | Portal (LAN demo)   |

Both paths produce tokens with identical shape. An admin can still
mint a token via SSH and paste it into the portal's `TokenBar`;
the sign-in screen and the legacy paste field coexist.

## Bootstrap admin (first-run)

On a fresh database with no users, set two env vars and start the
API:

```bash
export DIVIDE_BOOTSTRAP_ADMIN_SUB="alice"
export DIVIDE_BOOTSTRAP_ADMIN_PASSWORD="change-me-immediately"
docker compose -f deploy/docker-compose.yml up -d api
```

The API lifespan handler logs one of:

- `divide_api.bootstrap_admin.created sub=alice` — the admin row
  was created. You're done; log in.
- `divide_api.bootstrap_admin.skipped_exists sub=alice` — admin
  already exists; the env vars are no-ops. Remove them.
- `divide_api.bootstrap_admin.skipped_no_env` — neither env var
  is set; nobody got created. Set them and restart.
- `divide_api.bootstrap_admin.failed` — invalid role, etc.; see
  the structured-log error field.

After the first admin exists, **remove both env vars from the
environment**. The bootstrap is one-shot; once an admin exists the
env vars are no-ops but they still expand in your shell history
and process listings.

## Adding more users

There is no self-signup. Admin creates accounts via:

1. **SSH path** — `divide create-user --sub bob --password ... --role red`
   (this CLI command does not exist yet; tracked as L3 work. Today,
   use the API directly via curl, or another admin tool.)
2. **Direct DB** — `INSERT INTO users (sub, password_hash, role,
   disabled) VALUES (...)` with a pre-computed argon2id hash.
3. **Future L3 admin UI** — admin panel at `/portal/admin/users`
   (deferred — the F3-prep endpoint `GET /auth/users` lists them;
   write-side admin UI is its own plan).

## Roles

Five roles, defined in [`app/core/auth.py`](../services/api/app/core/auth.py)
(`Role` enum):

| Role       | Can do                                                  |
|------------|---------------------------------------------------------|
| `admin`    | Everything: manage users, view all runs, PVE ops        |
| `lead`     | Start / cancel any drill, view all runs                 |
| `red`      | Start drills, view own runs only                        |
| `blue`     | View own runs only (read-only — can't start/cancel)     |
| `observer` | View all runs (read-only)                               |

See [`docs/USER-REQUIREMENTS.md`](USER-REQUIREMENTS.md) §2 for the
full permission matrix (canonical source of truth).

## Password reset

Today there is no self-service reset. Reset procedure:

1. Admin opens a DB shell: `psql $DIVIDE_DB_URL`
2. `UPDATE users SET password_hash = '<new argon2id PHC>' WHERE sub = 'alice';`
3. Alice signs in with the new password.

Generating an argon2id PHC for the SQL:

```bash
python3 -c "from argon2 import PasswordHasher; print(PasswordHasher().hash('new-password'))"
```

This is a friction point — the **admin UI for user management**
(L3 work) will replace this with a real "reset password" form.

## Security notes

### Password hashing

- **Algorithm:** argon2id via `argon2-cffi` (OWASP-recommended).
- **Parameters:** library defaults — `time_cost=2`,
  `memory_cost=64 MiB`, `parallelism=4`. Tuned for a dev box on
  a LAN. Bump `time_cost` if the API becomes CPU-bound.
- **Salt:** random per hash (library default, 16 bytes). Two
  users with the same password get different hashes.

### Rate limiting

- **Failed login attempts:** 5 per `sub` per 15 minutes (Redis-backed,
  same shape as the `POST /drills` rate-limit from F2.2). Sixth
  attempt → 429.
- **Successful logins do NOT consume the budget** — only failed
  attempts increment the counter.
- **Fail-open on Redis outage** — by default, Redis errors are
  logged and the request is allowed through. To fail-closed
  instead, set `DIVIDE_RATE_LIMIT_FAIL_CLOSED=true`.

### Token lifetime

- **Default:** 8 hours (covers a working day). Set
  `DIVIDE_LOGIN_TOKEN_TTL_S` to override.
- Tokens self-verify until `exp`. There is **no revocation list**
  yet — once a token is minted, it's valid for the full TTL even
  if the user is disabled or the password changes.
- To force a sign-out: wait for `exp`, or change the signing
  secret (`DIVIDE_TOKEN_SECRET`) — that invalidates ALL existing
  tokens at once.

### Login response messages

- **All 401s say "invalid credentials"** regardless of which axis
  failed (unknown `sub`, wrong password, disabled account). This
  prevents enumeration: an attacker can't tell whether a
  username exists.
- **429 says** "too many failed login attempts for {sub}: {count}/
  {limit} in the last 15m; try again later".
- The `sub` echo in the 429 is the same string the caller
  submitted — not a server-side confirmation that the sub
  exists. The bucket key is the submitted string verbatim.

### What's NOT here

This plan does NOT include:

- **Multi-factor authentication.** L3 3.1 (Keycloak) is the
  long-term answer. Today's password is single-factor.
- **Password rotation policy.** LAN demo; the operator chooses.
- **Account lockout beyond the rate-limit.** A user who forgets
  their password just keeps getting 401s until they reset it.
- **"Forgot password" email flow.** No SMTP. Password reset is
  admin-only via the DB.
- **SSO / OIDC / SAML.** L3 3.1.
- **Session tracking on the server.** Tokens are self-contained.
  The DB has `users.last_login_at` for telemetry; no active
  session list.

## Migration / co-existence

Adding F3-prep does NOT break:

- **Existing tokens minted by `tools/issue_token.py`.** They
  verify against the same HMAC secret and the same `Role` enum.
- **Existing scenario YAML files.** No schema change.
- **Existing audits.** The token's `sub` is whatever the caller
  put in; an admin-minted token with `sub=alice` and a login-minted
  token with `sub=alice` look the same in the audit log.

The first thing you should do after bootstrapping the admin is:

1. Log in via the sign-in screen, verify your role is admin.
2. Add additional users via DB or future admin UI.
3. Remove `DIVIDE_BOOTSTRAP_ADMIN_*` from the env.

## API reference

### `POST /api/v1/auth/login`

```
{
  "sub": "alice",
  "password": "hunter2"
}
```

**Responses:**

- `200` — `{token, sub, role, iat, exp, ttl_remaining_s}`
- `401` — invalid credentials (generic; no enumeration)
- `422` — missing or empty fields
- `429` — too many failed attempts

### `POST /api/v1/auth/logout`

Stateless. Always returns `{"ok": true}`. The client drops the
token from localStorage.

### `GET /api/v1/auth/users`

Admin only. Returns:

```
[
  {
    "sub": "alice",
    "role": "admin",
    "disabled": false,
    "last_login_at": "2026-08-24T14:32:18+00:00" | null,
    "created_at": "2026-08-24T14:32:18+00:00"
  },
  ...
]
```

The `password_hash` field is **never** returned.

## Future work

- **Admin user-management UI** (L3 3.16 or thereabouts) — replace
  the DB-shell password reset with a real form.
- **Keycloak integration** (L3 3.1) — full SSO + MFA + token
  revocation. The argon2id table is retired in favor of the IdP.
- **`divide create-user` CLI** — wraps `POST /api/v1/admin/users`
  (which doesn't exist yet — the admin UI comes first).
- **Forgot-password email flow** — requires SMTP config; deferred.
- **Revocation list** — Redis-backed `divide:revoked:<jti>` set,
  consulted on every `verify_token()` call. Required before
  shipping to production with real users.

## See also

- [`docs/PLAN.md`](PLAN.md) §15 — the cyber-range roadmap that
  builds on this F3-prep foundation
- [`docs/USER-REQUIREMENTS.md`](USER-REQUIREMENTS.md) §2 — the
  full permission matrix
- [`docs/SETUP-UI.md`](SETUP-UI.md) — the setup wizard that can
  mint the first admin token
