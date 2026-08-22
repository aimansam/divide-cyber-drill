# Scenario spec (divide/v1)

A **Scenario** is a declarative description of a single cyber drill. It names
the assets that will be cloned from templates, the networks that connect them,
where telemetry goes, how the run is graded, and how to declare victory.

Scenario files are YAML, validated against
[`schemas/scenario.schema.json`](../schemas/scenario.schema.json) (JSON Schema
draft 2020-12). **Every committed file MUST pass validation** — CI runs
`tools/validate_scenario.py` on every PR.

This doc is the prose companion to the schema. For normative definitions
(enums, regex, bounds), the schema wins. Examples live in
[`examples/scenarios/`](../examples/scenarios/).

---

## Top-level shape

```yaml
apiVersion: divide/v1          # pinned; bump on breaking changes
kind: Scenario                 # always Scenario for now
metadata: { ... }              # identity + human-friendly fields
spec:     { ... }              # operational shape (required)
```

`metadata.version` is **independent** of `apiVersion`. The first is the
scenario revision; the second is the schema revision this file was authored
against.

---

## `metadata`

| Field | Type | Notes |
|---|---|---|
| `name` | string | unique slug, `[a-z0-9-]{3..64}`. Used in URLs and run IDs. |
| `title` | string | shown in the portal. |
| `version` | int ≥ 1 | scenario revision; bump on breaking changes. |
| `difficulty` | enum | one of `novice` / `beginner` / `intermediate` / `advanced` / `expert`. Drives default scoring weights. |
| `duration_min` | int | expected run length; used by the scheduler for timeboxing. |
| `tags` | string[] | free-form, max 16, unique. |
| `authors` | object[] | `handle` required; `name` + `email` optional. |

---

## `spec`

### `objectives`

Free-form per-team descriptions of what they must accomplish. Strings, 5–500
chars. The runner uses these as text — no auto-parsing. Keep them concrete
("DCSync of at least one DA account") rather than vague ("achieve AD
dominance").

```yaml
objectives:
  red: ["Compromise at least one domain user via the phishing email."]
  blue: ["Detect the malicious attachment within 10 minutes of receipt."]
```

### `assets`

List of VMs/containers that will be cloned from templates. Each asset has a
**unique** `role` (the runner and telemetry rules reference this string).

```yaml
assets:
  - role: red_attacker
    kind: vm                  # vm | container | kubernetes (vm only in Phase 1)
    template: tpl-kali-cloudinit
    count: 1                  # default 1
    networks: [attacker_vlan]
    resources: { cores: 4, ram_mb: 8192 }
    exposed: true             # reachable via noVNC in the portal
    user_data: cloud-init/red.yaml   # optional, path relative to scenario file
```

`networks` order = NIC order on the VM. `exposed` only matters for the
attacker workstation today; the portal's console panel only attaches to one
exposed asset per run.

### `networks`

Virtual networks defined for this scenario. `cidr` is validated as a real CIDR
(via `ipaddress.IPv4Network`), not just a regex.

```yaml
networks:
  - name: corp_vlan
    cidr: 10.10.10.0/24
    isolation: tight          # tight | loose
    egress: blocked          # blocked | allowed | restricted
    dhcp: true               # default true
```

Safety defaults: `isolation: tight`, `egress: blocked`. **Never** use
`egress: allowed` on a network that hosts production-shaped data.

### `telemetry`

Where events from this run are sent.

```yaml
telemetry:
  sinks:
    - type: wazuh
      endpoint: wazuh-mgr:55000
      channels: [sysmon, edr_alerts]
    - type: misp
      endpoint: misp.local:443
      channels: [iocs]
    - type: minio
      bucket: divide-runs
  alerting:
    rules:
      - severity: [critical, high]
        to: [slack]
```

`sinks[].type` is an enum: `wazuh`, `misp`, `minio`, `stdout`. `wazuh` and
`misp` require `endpoint`; `minio` requires `bucket`; `stdout` writes to the
run log (debug only).

`alerting.rules` is optional. Each rule forwards events whose severity is in
the rule's list to the rule's channels.

### `scoring`

How the run is graded. Two separate rubrics, one per team, each with a
`pass_threshold` (0–100).

```yaml
scoring:
  blue:
    rules:
      - id: detection_speed
        weight: 40
        target_min: 10        # optional: ideal minutes
      - id: containment_speed
        weight: 30
        target_min: 20
      - id: false_positive_penalty
        weight: 30
    pass_threshold: 70
  red:
    rules:
      - id: objective_completion
        weight: 100
    pass_threshold: 60
```

The runner aggregates weighted rule scores into a 0–100 result. Weights do
not have to sum to 100 per rubric — they're normalized at scoring time.

### `win_conditions`

Boolean-ish expressions per team. **Informal in v1** — strings, no DSL. The
runner interprets them heuristically ("did this happen?") and the runner will
grow a small parser as we accumulate more scenarios.

```yaml
win_conditions:
  red:
    - "DCSync of at least one Domain Admin account succeeds."
    - "Ransomware note observed on two or more endpoints in corp_vlan."
  blue:
    - "All compromised endpoints isolated within 30 minutes."
    - "No encryption events on file_server or dc_server."
```

### `artifacts`

What gets collected per run and where it's stored.

```yaml
artifacts:
  sink_to: minio              # minio | local | s3
  bucket: divide-runs
  required_pcaps: [corp_vlan, dmz]
  retention_days: 30
```

`required_pcaps` names networks whose traffic must be captured during the
run. Each must be a name from `spec.networks`.

---

## Authoring workflow

1. Copy an existing scenario from `examples/scenarios/`.
2. Edit in place. Keep the slug (`metadata.name`) unique.
3. Run `python tools/validate_scenario.py path/to/your.scenario.yaml`.
4. Open a PR. CI runs the validator, the schema test, the API tests.

## Versioning

When you change a scenario in a way that breaks replay of prior runs, bump
`metadata.version`. When you need new schema fields, bump `apiVersion` (e.g.
`divide/v2`) and write a migration shim. We do not have migrations yet — for
v1 we just declare the format and live with it.

## What v1 explicitly doesn't do

- ❌ No script DSL — `user_data` is opaque YAML/cloud-init.
- ❌ No scoring evaluator — the YAML is declarative only.
- ❌ No asset dependencies — assets are independent of each other.
- ❌ No live scoring — `target_min` is documented but not enforced.
- ❌ No template validation — `template:` is a string the runner looks up.

These land in v2 once we have real runs to learn from.
