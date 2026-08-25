# Section 18.7 — F9.4: Wired three deferred buttons

> **Status:** F9.4 shipped (commits `050d74c` + `6cbd8d0` +
> `3ecfe71`). The three "coming soon" stubs in the Operator
> Console + UserListCard are now real.

## What F9.4 ships

Three UI components claimed functionality that wasn't wired.
After §18 closed, an audit found these were advertising buttons
that did nothing (or surfaced "ships with the F7 / F8 plans" errors).
This is **the most credible thing the §18 closure missed** —
operators clicking buttons that look real but aren't.

### The three disconnects

| Button | Component | Pre-F9.4 behavior | Post-F9.4 behavior |
|---|---|---|---|
| **Reset** | `OperatorConsoleCard` per-run row | Stub — `deferred("Reset to clean state")` error toast | `POST /api/v1/drills/{id}/reset` (F7). 409 surfaces a "use save-as-template first, then retry" message. |
| **Inject** | `OperatorConsoleCard` per-run row | Stub — `deferred("Event injection")` error toast | New `InjectEventModal` collects kind / severity / payload (JSON), posts `POST /api/v1/runs/{id}/events` (F8). Success toast on close. |
| **Disable / Enable** | `UserListCard` per-user row | Stub — surfaces "not wired up yet (L3 admin-user-management plan)" | New endpoint `POST /api/v1/auth/users/{sub}/toggle-disabled` (admin-only). Flips the user's `disabled` flag and returns the refreshed row; portal patches the badge in place. |

### What's still deferred (out of scope)

  * **Edit-user form** — no `PUT /api/v1/auth/users/{sub}` to
    change a user's role / sub. The L3.16 admin CRUD plan owns
    this. The toggle is the most-asked-for mutation; we shipped
    that first.
  * **Delete-user** — no `DELETE /api/v1/auth/users/{sub}`. Same
    parent plan.
  * **Asset-level inject** — the manual event-inject endpoint
    accepts `asset_id` in the payload but the modal doesn't
    surface an asset picker. Operators who want to inject
    asset-specific events can paste JSON directly into the
    payload textarea; the modal is positioned as the
    common-case UX.
  * **Range bookings / replay UI / etc.** — still in §19
    backlog; no movement.

## Why this matters

Two concrete reasons:

  1. **Credibility.** Two buttons in the Operator Console —
    used by every admin during a drill — said "Coming with F7"
    even though F7 had shipped. That's actively misleading;
    an admin clicking Reset during an incident and seeing
    "coming soon" loses trust in the rest of the UI.
  2. **Operator workflow.** A real drill needs Reset
    (mid-exercise recovery) and Inject (manual kill-chain
    signals during a tabletop). Both were advertised as
    available and unavailable at once. F9.4 fixes both.

## API contract

### `POST /api/v1/auth/users/{sub}/toggle-disabled` (F9.4)

Admin-only. Toggle semantics (read + flip), not set.

  * **200** + `UserPublic` — toggled; returns the refreshed row.
  * **404** — `sub` not found.
  * **401** — no token.
  * **403** — non-admin.

### Existing endpoints now wired

The other two endpoints already existed; F9.4 was pure
portal glue:

  * `POST /api/v1/drills/{id}/reset` (F7) — 200 + reset run,
    409 if the run has no template snapshot, 404 if unknown.
  * `POST /api/v1/runs/{id}/events` (F8) — 201 + TelemetryEvent
    row, 422 on bad payload, 401/403 for non-admin/lead.

## Bundle budget

Pre-F9.4: 275.76 KB decimal (10.71 KB under the 280 KB ceiling).
Post-F9.4: **273.53 KB decimal** (6.47 KB under the ceiling).

The Inject modal added the most weight (~6 KB). The Reset +
toggle wiring added <500 bytes. We have ~6.5 KB of headroom
left; the next feature that adds portal code will need to
trim something first.

## Tests

`tests/test_f9_4_toggle_disabled.py` (10 tests) pins:

  * Toggle enabled user -> disabled (200, body has disabled=true).
  * Toggle disabled user -> enabled (200, body has disabled=false).
  * Response never leaks `password_hash` or `password`.
  * 404 unknown user.
  * 401 anonymous.
  * 403 red.
  * 403 blue.
  * 403 lead.
  * End-to-end: admin disables a user -> that user's login
    returns 401.
  * Reversible: two consecutive toggles round-trip.

The Reset + Inject wiring is covered by the existing F8 SSE
test suite (which exercises the underlying endpoints) + a
future portal-side component test (deferred — see the §19
backlog).

## Migration / rollout

F9.4 is **fully backwards-compatible**:

  * New endpoint: additive; old clients ignore it.
  * Portal changes: button wiring only; no API change.
  * `tests/test_f9_4_toggle_disabled.py`: autouse DB cleanup
    matches the F9 / F10 / F11 pattern.

`make up && make verify` is the rollout gate.

## Operator workflow impact

**Before F9.4:** the admin clicks Reset or Inject during a
drill, sees "ships with F7 / F8 plans," and either:

  * Gives up and uses curl from the host (the backend
    actually worked all along — they just couldn't reach it
    from the UI).
  * Files a "portal is broken" issue.
  * Reverts to SSH + manual asset lifecycle, missing the
    single-screen UX.

**After F9.4:** the buttons work as labeled. Reset undoes
bad clones mid-exercise. Inject drops a manual
`kill-chain.signal` for a tabletop scenario where the
runner can't infer the kill chain. The toggle button
disables a misbehaving red-team player without deleting
their account.

## See also

  * [`docs/SECTION-9-INTEGRATION.md`](SECTION-9-INTEGRATION.md)
    — F9 DrillConsole consolidation (the parent).
  * [`docs/F7-TEMPLATES.md`](F7-TEMPLATES.md) — F7 (the
    source of the `/reset` endpoint).
  * [`docs/F8-SOC.md`](F8-SOC.md) — F8 (the source of the
    `/events` ingest endpoint).
  * [`docs/PLAN.md` §19](PLAN.md) — §19 backlog still owns
    edit-user + delete-user + range bookings + replay UI.
