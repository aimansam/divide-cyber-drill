# div:ide demo walkthrough

> _Sample output from `tools/demo.sh --record`._
>
> This file is a placeholder. The real walkthrough is captured
> at deploy time by running:
>
> ```bash
> tools/demo.sh --record
> ```
>
> against a live API. The default output path is
> `examples/demo-output.md`, which is gitignored in real
> deployments so each capture is fresh.
>
> What `tools/demo.sh --record` captures:
>
> 1. `/healthz` response
> 2. `/api/v1/scenarios` catalog (first 60 lines, JSON)
> 3. Auth flow: `POST /api/v1/auth/login` with --admin-sub
>    + --admin-pw (returns the HMAC token)
> 4. `GET /api/v1/drills` (admin view)
> 5. `GET /api/v1/drills/{id}/report` (JSON after-action report
>    for the latest run)
> 6. `GET /api/v1/drills/{id}/debrief.md` (F11 markdown
>    play-by-play for the same run)
> 7. Portal walkthrough notes (which tabs to demo)
>
> The captured file is a **markdown artifact** -- the operator
> can copy snippets into leadership handoff emails, paste into
> Notion/Confluence, or convert to PDF with `pandoc`.
