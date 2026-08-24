/**
 * ScenarioAuthoringCard — admin/lead authoring surface.
 *
 * Lists active + archived scenarios (so the lead can restore one
 * that was deleted by mistake). For each non-archived scenario
 * shows an "Archive" button. For each archived scenario shows
 * "Restore". At the top, a textarea + "Import" button to add a
 * new scenario by pasting YAML.
 *
 * Roles (M3.2, Half 2): admin + lead. The server doesn't enforce
 * role on /scenarios/* (all roles can list + read); the role
 * gate here is purely a UX choice to keep the lead's authoring
 * surface out of the red/blue composition.
 *
 * Future L3 work (criterion 3.12): full CRUD UI (edit metadata,
 * edit spec, versioned archives). For Half 2 we ship the import
 * + archive + restore halves; full CRUD is its own plan.
 */

import { useEffect, useState } from "react";
import {
  Archive,
  CheckCircle2,
  FileCode,
  Loader2,
  RotateCcw,
  Trash2,
  Upload,
  XCircle,
} from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { api, ApiError, getToken } from "@/lib/api";

interface ScenarioRow {
  id?: number;
  name: string;
  title?: string | null;
  difficulty?: string | null;
  duration_min?: number | null;
  archived_at?: string | null;
}

interface ScenariosPayload {
  items?: ScenarioRow[];
  total?: number;
}

const STARTER_YAML = `metadata:
  name: my-drill
  title: My custom drill
  version: 0.1.0
  difficulty: easy
  duration_min: 30
  tags: [custom]
  authors: [you]
spec:
  description: |
    Short description of what the drill exercises.
  assets:
    - role: target
      kind: vm
      template: tpl-debian-cloudinit
`;

export function ScenarioAuthoringCard() {
  const [items, setItems] = useState<ScenarioRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [yaml, setYaml] = useState(STARTER_YAML);
  const [busy, setBusy] = useState<string | null>(null);
  const [lastResult, setLastResult] = useState<
    { ok: boolean; msg: string } | null
  >(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const data = await api.get<ScenariosPayload>(
        "/api/v1/scenarios?include_archived=true",
      );
      setItems(data.items ?? []);
    } catch (e: unknown) {
      const msg =
        e instanceof ApiError ? `HTTP ${e.status} ${e.url}` : String(e);
      setError(msg);
      setItems([]);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function onImport() {
    setBusy("import");
    setLastResult(null);
    try {
      const row = await api.post<ScenarioRow>("/api/v1/scenarios", { yaml });
      setLastResult({
        ok: true,
        msg: `Imported scenario '${row.name}' (id=${row.id ?? "?"})`,
      });
      await load();
    } catch (e: unknown) {
      const msg =
        e instanceof ApiError ? `HTTP ${e.status} ${e.url}` : String(e);
      setLastResult({ ok: false, msg });
    } finally {
      setBusy(null);
    }
  }

  async function onArchive(name: string) {
    setBusy(name);
    setLastResult(null);
    try {
      await archiveViaApi(name);
      setLastResult({ ok: true, msg: `Archived '${name}'` });
      await load();
    } catch (e: unknown) {
      const msg =
        e instanceof ApiError ? `HTTP ${e.status} ${e.url}` : String(e);
      setLastResult({ ok: false, msg });
    } finally {
      setBusy(null);
    }
  }

  async function onRestore(name: string) {
    setBusy(name);
    setLastResult(null);
    try {
      await restoreViaApi(name);
      setLastResult({ ok: true, msg: `Restored '${name}'` });
      await load();
    } catch (e: unknown) {
      const msg =
        e instanceof ApiError ? `HTTP ${e.status} ${e.url}` : String(e);
      setLastResult({ ok: false, msg });
    } finally {
      setBusy(null);
    }
  }

  const active = items.filter((s) => !s.archived_at);
  const archived = items.filter((s) => s.archived_at);
return (
    <Card>
      <CardHeader>
        <CardTitle>
          <span className="inline-flex items-center gap-2">
            <FileCode className="h-4 w-4 text-muted-foreground" />
            Scenario authoring
          </span>
        </CardTitle>
        <CardDescription>
          {active.length} active · {archived.length} archived · paste a
          YAML below to import. Schema validation runs on the server
          (`schemas/scenario.schema.json`).
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {error && <div className="text-sm text-destructive">{error}</div>}
        {lastResult && (
          <div
            className={
              "flex items-start gap-2 rounded-md border p-2 text-sm " +
              (lastResult.ok
                ? "border-emerald-700/40 bg-emerald-900/20 text-emerald-200"
                : "border-destructive/40 bg-destructive/10 text-destructive")
            }
          >
            {lastResult.ok ? (
              <CheckCircle2 className="mt-0.5 h-4 w-4" />
            ) : (
              <XCircle className="mt-0.5 h-4 w-4" />
            )}
            <span className="font-mono">{lastResult.msg}</span>
          </div>
        )}

        <div>
          <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Paste scenario YAML
          </label>
          <textarea
            className="mt-1 h-40 w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-xs"
            value={yaml}
            onChange={(e) => setYaml(e.target.value)}
            spellCheck={false}
          />
          <Button
            onClick={onImport}
            disabled={busy !== null || yaml.trim().length === 0}
            className="mt-2"
          >
            {busy === "import" ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Upload className="mr-2 h-4 w-4" />
            )}
            Import
          </Button>
        </div>

        <div>
          <h4 className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Active scenarios
          </h4>
          {loading && active.length === 0 ? (
            <div className="text-sm italic text-muted-foreground">
              Loading…
            </div>
          ) : active.length === 0 ? (
            <div className="text-sm italic text-muted-foreground">
              No active scenarios.
            </div>
          ) : (
            <ul className="divide-y divide-border rounded-md border border-border">
              {active.map((s) => (
                <li
                  key={s.name}
                  className="flex items-center justify-between gap-3 px-3 py-2 text-sm"
                >
                  <div>
                    <div className="font-mono">{s.name}</div>
                    <div className="text-xs text-muted-foreground">
                      {s.title ?? ""}
                      {s.difficulty ? ` · ${s.difficulty}` : ""}
                      {s.duration_min ? ` · ${s.duration_min}m` : ""}
                    </div>
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => onArchive(s.name)}
                    disabled={busy !== null}
                  >
                    {busy === s.name ? (
                      <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                    ) : (
                      <Archive className="mr-1 h-3 w-3" />
                    )}
                    Archive
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </div>

        {archived.length > 0 && (
          <div>
            <h4 className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Archived scenarios
            </h4>
            <ul className="divide-y divide-border rounded-md border border-border">
              {archived.map((s) => (
                <li
                  key={s.name}
                  className="flex items-center justify-between gap-3 px-3 py-2 text-sm"
                >
                  <div className="font-mono text-muted-foreground">
                    {s.name}
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => onRestore(s.name)}
                    disabled={busy !== null}
                  >
                    {busy === s.name ? (
                      <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                    ) : (
                      <RotateCcw className="mr-1 h-3 w-3" />
                    )}
                    Restore
                  </Button>
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="text-xs italic text-muted-foreground">
          <Trash2 className="mr-1 inline h-3 w-3" />
          Archive sets <code>archived_at</code> (soft delete). The run
          history (audit log + drill rows) is preserved; restoring
          sets <code>archived_at = NULL</code>.
        </div>
      </CardContent>
    </Card>
  );
}
// Helpers — api.ts has get + post but no delete. Inline small
// wrappers so the component stays self-contained.

async function archiveViaApi(name: string): Promise<void> {
  const tok = getToken();
  const r = await fetch(
    `/api/v1/scenarios/${encodeURIComponent(name)}`,
    {
      method: "DELETE",
      headers: tok ? { "X-Divide-Token": tok } : {},
    },
  );
  if (!r.ok) {
    throw new ApiError(
      r.status,
      `/api/v1/scenarios/${name}`,
      `HTTP ${r.status}`,
      await r.text().catch(() => undefined),
    );
  }
}

async function restoreViaApi(name: string): Promise<void> {
  const tok = getToken();
  const r = await fetch(
    `/api/v1/scenarios/${encodeURIComponent(name)}/restore`,
    {
      method: "POST",
      headers: {
        "X-Divide-Token": tok,
        "Content-Type": "application/json",
      },
      body: "{}",
    },
  );
  if (!r.ok) {
    throw new ApiError(
      r.status,
      `/api/v1/scenarios/${name}/restore`,
      `HTTP ${r.status}`,
      await r.text().catch(() => undefined),
    );
  }
}