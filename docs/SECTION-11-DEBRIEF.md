# Section 18.3 — F11: Drill debrief artifact

> **Status:** F11.1 + F11.2 shipped (commits `3683480` +
> `64256e1`). Operators can hand leadership a markdown play-by-play
> of any finished drill with one click.

## What F11 ships

A new endpoint + a new portal button that produce a **markdown
debrief** of a finished drill, intended for hand-off to leadership
after a cyber-range exercise.

  * `GET /api/v1/drills/{run_id}/debrief.md` — returns a
    `text/markdown` response with `Content-Disposition: inline`
    so the operator can open it in a browser tab. Modern browsers
    (Chrome, Firefox, Safari, Edge) render the markdown inline;
    older browsers fall back to plain text.
  * "View debrief" button in `DrillConsole`'s header — appears
    next to "Download report" when the run is in a terminal state.

## Sections of the debrief

The markdown has seven sections, in this order:

1. **Summary** — scenario name + title, run id, status,
   started/ended timestamps, duration, started-by, error
   (if any).
2. **Per-team score** — red vs blue table with capture count,
   raw points, decay-adjusted score, and a winner callout.
3. **Per-flag timing** — one row per `FlagSubmission`: capture
   time, team, flag id, elapsed seconds, points awarded. Empty
   section ("No flags captured.") if no submissions.
4. **Pivot timeline (red)** — chronological table of red-team
   events: `run.started`, `run.completed`, `asset.running`,
   `flag.captured`, `kill-chain.signal`. Empty section ("No
   pivot events recorded.") if no telemetry.
5. **Detection timeline (blue)** — chronological table of
   blue-team events: `audit.alert`, `soc.signal`, `blue.detection`.
   Empty section ("No detection events recorded.") if no telemetry.
6. **Asset table** — every asset role + template + status + IP
   + VMID + error, sorted by role.
7. **Lessons learned** — empty placeholder for the operator to
   fill in after reviewing the timeline. Four suggested prompts.

## Sample output

```markdown
# Drill debrief

**Scenario:** `red-vs-blue-baseline` -- Red vs Blue Baseline
(v1, beginner, 30 min)

## Summary

* **Run id:** `42`
* **Status:** `succeeded`
* **Started:** 2026-08-25T14:00:00+00:00
* **Ended:** 2026-08-25T14:18:22+00:00
* **Duration:** 18m 22s
* **Started by:** alice

## Per-team score

| Team | Captures | Points (raw) | Score (decay-adjusted) |
|------|----------|--------------|------------------------|
| red  | 3        | 300          | 240                    |
| blue | 1        | 100          | 100                    |

**Result:** `red` wins.

## Per-flag timing

| Captured at | Team | Flag | Elapsed (s) | Points |
|-------------|------|------|-------------|--------|
| 2026-08-25T14:04:12+00:00 | red | `red-flag-router` | 252 | 60 |
| 2026-08-25T14:11:08+00:00 | red | `red-flag-file-server` | 668 | 100 |
| 2026-08-25T14:18:22+00:00 | red | `red-flag-log-aggregator` | 1102 | 80 |

... (Pivot timeline, Detection timeline, Asset table, Lessons learned)
```

## Operator workflow

After a drill finishes:

  1. Operator opens the **Observe** tab in the portal.
  2. DrillConsole shows the run status as `SUCCEEDED` (or
     `FAILED` / `TIMEOUT` / `CANCELLED`).
  3. Operator clicks **View debrief** — a new browser tab opens
     with the rendered markdown.
  4. Operator reviews the pivot timeline + asset table to
     understand what happened.
  5. Operator fills in the "Lessons learned" section using
     their editor of choice (paste into Notion / Confluence /
     a follow-up doc, or just `cat run-N-debrief.md >> postmortem.md`).
  6. Operator shares the link (or the file) with leadership.

For an offline / archive workflow:

```bash
curl -H "X-Divide-Token: $DIVIDE_TOKEN" \
     http://localhost:8000/api/v1/drills/42/debrief.md \
  > run-42-debrief.md

# Convert to PDF for hand-off (pandoc):
pandoc run-42-debrief.md -o run-42-debrief.pdf
```

## API contract

| Status | When |
|---|---|
| `200` | Terminal run (succeeded/failed/timeout/cancelled). Body is markdown. |
| `401` | No `X-Divide-Token` header. |
| `403` | Token can see other runs but not this one (red/blue only see their own). |
| `404` | Run id does not exist. |
| `409` | Run is `pending` or `running` (debrief requires terminal state). |

Response headers:

```
Content-Type: text/markdown; charset=utf-8
Content-Disposition: inline; filename="run-{id}-debrief.md"
```

## Visibility rule

Same as `/runs/{id}/report`: any authenticated role can fetch,
but red/blue only see their own runs. Admin/lead/observer see
everything.

This is enforced by `app.services.authorization.can_view_run` —
the same predicate `/report` uses — so a future change to the
visibility rule automatically applies to both endpoints.

## Where the data comes from

  * **Run row** — `score_red`, `score_blue`, `started_at`,
    `ended_at`, `started_by`, `error`. The single source of truth
    for the run summary + per-team score.
  * **FlagSubmission rows** — captured_at, flag_id, team,
    elapsed_seconds, points. Time-decay scoring is frozen at
    capture time; the debrief never recomputes.
  * **TelemetryEvent rows** — ts, kind, severity, source,
    payload. Filtered by kind vocabulary into pivot vs detection
    sections.

No new data is computed by the endpoint; the markdown is a pure
projection of existing tables. If we ever backfill
`FlagSubmission.points` from a new scoring rule, the historical
debriefs keep their original numbers (they're snapshots in the
DB rows themselves).

## Extending the pivot / detection timelines

If you add a new `TelemetryEvent.kind`:

  * Red events → add to `_is_pivot_event` in
    `services/api/app/routers/debrief.py`.
  * Blue events → add to `_is_detection_event` in the same file.

The two vocabulary sets are the single point of update; the
markdown rendering picks them up automatically.

If you need a third timeline category (e.g., "operator actions"),
add a new `_is_X_event` predicate + a new `_render_X_timeline`
helper called from `_render_debrief`. The section ordering is
defined by the order of calls in `_render_debrief`, so new
sections slot in where you call them.

## Tests

`services/api/tests/test_f11_debrief.py` (11 tests) pins:

  * 200 + markdown body with sections in the right order.
  * Per-team scores reflect `Run.score_red` / `Run.score_blue`.
  * Per-flag rows for each `FlagSubmission`.
  * Pivot timeline includes `run.started` / `asset.running` /
    `flag.captured` / `run.completed`.
  * Asset table renders each asset role + IP.
  * Lessons-learned placeholder is always present.
  * `Content-Disposition` header carries the run id.
  * 404 unknown / 401 anonymous / 409 non-terminal /
    403 cross-team.

Per-test DB cleanup autouse fixture (mirrors the F9 pattern)
keeps the suite isolated across files.

## What F11 is NOT

  * **No PDF export.** Pandoc is the recommended path for that —
    one shell command, no library dependency.
  * **No auto-fill of "Lessons learned".** That section is
    intentionally a placeholder; human input is the product.
  * **No new scoring rules.** The debrief surfaces existing
    FlagSubmission.points as-is; scoring changes happen in
    F5's flag-submission endpoint, not here.

## See also

  * [`docs/PLAN.md` §18.3](PLAN.md) — the F11 milestone in
    the plan doc.
  * [`docs/F5-SCORING.md`](F5-SCORING.md) — F5 (flags + scoring)
    — the source of `FlagSubmission` and time-decay points.
  * [`docs/F8-SOC.md`](F8-SOC.md) — F8 (SOC view + telemetry) —
    the source of `TelemetryEvent` and the event vocabulary.
  * [`docs/SECTION-9-INTEGRATION.md`](SECTION-9-INTEGRATION.md)
    — F9 (DrillConsole consolidation) — adds the leaderboard
    + SOC stream inline; F11 adds the debrief artifact button
    inline.
