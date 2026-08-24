# §15 Cyber-Range Plans — Closure Summary

> **Status:** §15 closed. This page is the **one-stop summary** of
> what shipped across F3-F8 + the operator-facing workflow that
> exercises every feature end-to-end.

## What shipped (F3-F8)

| Plan | Closes | What it adds |
|---|---|---|
| **F3** | G1 | Multi-VM scenarios with `networks[]` + per-asset NICs; PVE bridge per network; runner iterates assets + clones; `ScenariosCard` + `TopologyGraph` |
| **F4** | G2 | noVNC console via PVE `get_vnc_ticket` proxy; one-click browser access; `AssetsCard` "Open console" button |
| **F5** | G3, G5 | Flag planting at scenario start (cloud-init); `submit-flag` endpoint; time-decay scoring (`points = base * max(0, 1 - elapsed/window)`); `score_breakdown` in after-action report |
| **F6** | G4, G6 | `Exercise` + `Team` + `TeamMembership` models; multi-team parallel runs; `IDLE → LIVE → ENDED → ARCHIVED` FSM; `LeaderboardCard` with team colors + first-place crown |
| **F7** | G7 | `Template` model (immutable JSONB snapshot); `POST /drills` accepts `template_id`; `POST /drills/{id}/reset` re-stages assets; `POST /drills/{id}/save-as-template` bookmarks live state; `TemplatesCard` |
| **F8** | G8 | `TelemetryEvent` table + in-process `EventBus` (1024-event ring buffer, fan-out, dedup); runner emits `run.started` / `asset.running` / `run.completed`; `submit-flag` emits `flag.captured`; SSE endpoint `/runs/{id}/events/stream`; `SocViewCard` with severity filter + pause/resume |

**Test growth:** 540 → 859 (+319).

**Bundle discipline:** Portal bundle 251.65 KB JS / 75.11 KB gzipped
(well under the 280 KB budget). No new runtime dependencies
beyond `websockets` (F4).

## End-to-end operator workflow

A complete red-vs-blue drill, exercising every F3-F8 feature, in
~12 minutes of operator time:

```bash
# 1. Sign in (F3-prep — credential login).
#    Open http://localhost:8000/portal/app/, click Sign In.

# 2. Pick the demo scenario (F3 — multi-VM scenarios).
#    Admin tab → ScenariosCard → "red-vs-blue-baseline".
#    3 assets on 2 networks; 3 red-side flags planted at start.

# 3. Create an exercise (F6 — multi-team).
#    Admin tab → Exercises → "Create":
#      name: "demo-tabletop-2026-08-25"
#      scenario: red-vs-blue-baseline
#      teams: [{"name": "red"}, {"name": "blue"}]
#    Add members: alice@red, bob@blue.
#    Start the exercise.

# 4. Start a run per team (F6 — parallel runs + F3 — VM cloning).
#    Operate tab → "Start run".
#      Scenario: red-vs-blue-baseline
#      Exercise: demo-tabletop-2026-08-25
#      Team: red
#    Same again for blue. Two Runs clone in parallel on the
#    same scenario topology but separate VMs.

# 5. Open noVNC consoles (F4 — operator access).
#    Observe tab → Run → AssetsCard → "Open console".
#    Red attacks; blue defends.

# 6. Capture flags (F5 — flag scoring).
#    Blue captures red-side flag: POST /drills/{run_id}/submit-flag.
#    Points roll up into Team.score (F6 — leaderboard).

# 7. Watch the SOC view (F8 — live telemetry).
#    Observe tab → SOC view.
#    Live event stream: run.started, asset.running, flag.captured,
#    plus operator-injected kill-chain signals.
#    Severity filter (info / low / medium / high) + pause/resume.

# 8. Bookmark an interesting state (F7 — save-as-template).
#    "Save as template" mid-drill → POST /drills/{run_id}/save-as-template.
#    Bind is automatic; the template name is forever stable.

# 9. Stop the exercise (F6 — exercise FSM).
#    "Stop" → LIVE → ENDED. Leaderboard freezes.

# 10. Download the after-action report (F2.5 — JSON report).
#     GET /api/v1/drills/{run_id}/report. Includes `score_breakdown`
#     and the F5 per-rule scoring output.

# 11. Next cohort: clone the template (F7 — replay).
#     Operate tab → TemplatesCard → "Clone".
#     POST /drills with template_id. Identical topology, fresh
#     VMs, fresh flags.

# 12. If anything drifts mid-drill: Reset (F7).
#     POST /drills/{run_id}/reset. Wipes + restages assets,
#     clears scores, keeps the template identity.
```

## Why §15 closed now

| Requirement | Status | Evidence |
|---|---|---|
| Multi-VM scenarios | ✅ | F3 commits `2a97525`+`6e9e5b5`+`c3d4e5f` |
| noVNC console | ✅ | F4 commits `9c7a583`+`e28ed7a`+`110e50f` |
| Flag scoring | ✅ | F5 commits `98e4e7c`+`85ecf29`+`749e6c5` |
| Multi-team exercises | ✅ | F6 commits `5386096`+`d7e69f9`+`176dd6d` |
| Range templates | ✅ | F7 commits `fa20fb3`+`7c4f03a`+`d02a188` |
| SOC view + SSE | ✅ | F8 commits `d88dbe6`+`7a987f9`+`d74593f` |

**22 commits across §15** since F2 closure. **+319 tests**.

## Open follow-ons (post-§15)

See [`docs/PLAN.md`](PLAN.md) §17 for the post-§15 roadmap:

| # | Feature | Effort |
|---|---|---|
| R1 | Redis pub/sub for multi-worker SSE | ~3 h |
| R2 | Polish (light theme, mobile, keyboard shortcuts) | ~3 h |
| R3 | Coaching / replay mode | ~6 h |
| R4 | Range bookings calendar | ~3 h |
| R5 | Multi-tenant isolation | ~10 h |
| R6 | Scenario marketplace | ~5 h |
| R7 | Replay UI (scrub past events) | ~4 h |

**My pick (next plan):** R1 — Redis pub/sub for SSE. Smallest
remaining engineering risk, biggest production-readiness win.

## See also

- [`docs/PLAN.md`](PLAN.md) — full §15 history + §17 roadmap
- [`docs/TEST-PRODUCT.md`](TEST-PRODUCT.md) — L1/L2/L3 ship criteria + update log
- [`docs/USER-REQUIREMENTS.md`](USER-REQUIREMENTS.md) — per-role capability matrix
- [`docs/PORTAL-UI.md`](PORTAL-UI.md) — portal cards (F3-F8 additions: Leaderboard, Templates, SOC)
- [`docs/F3-RUNBOOK.md`](F3-RUNBOOK.md), [`F4-NOVNC.md`](F4-NOVNC.md), [`F5-SCORING.md`](F5-SCORING.md), [`F6-MULTITEAM.md`](F6-MULTITEAM.md), [`F7-TEMPLATES.md`](F7-TEMPLATES.md), [`F8-SOC.md`](F8-SOC.md) — per-plan runbooks
- [`docs/DEMO.md`](DEMO.md) — `make demo` exercises the full §15 flow
