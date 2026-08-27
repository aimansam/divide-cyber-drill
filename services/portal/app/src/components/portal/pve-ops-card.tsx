/**
 * PveOpsCard — read-only PVE health summary + orphan janitor.
 *
 * Calls four endpoints:
 *   * GET  /api/v1/admin/probe               → PVE reachability +
 *                                              permissions +
 *                                              version + storage + nodes
 *   * GET  /api/v1/admin/storage             → storage pools
 *   * GET  /api/v1/admin/drill-template-status
 *                                            → is `tpl-debian-cloudinit` ready?
 *   * GET  /api/v1/admin/assets/orphans      → ORPHANED asset rows
 *   * POST /api/v1/admin/assets/cleanup      → retry destroy_vm on orphans
 *
 * Q22 added the orphan-cleanup section. The wizard at /portal/
 * is still the deploy surface for upload + create-template flows;
 * this card is the day-2 health check + the operator's
 * "stale-VM janitor" panel.
 *
 * Roles: admin only (composition table). The /admin/* endpoints
 * are router-level gated by require_role(ADMIN), so non-admin
 * callers would get 403 from the API even if they reached this
 * card.
 */

import { useEffect, useState } from "react";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Database,
  HardDrive,
  Loader2,
  RefreshCw,
  Trash2,
  XCircle,
  X,
} from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { api, detailFromError } from "@/lib/api";

interface Probe {
  reachable?: boolean;
  version?: string | null;
  pve_user?: string | null;
  has_drill_privs?: boolean | null;
  has_setup_privs?: boolean | null;
  drill_privs_missing?: string[] | null;
  setup_privs_missing?: string[] | null;
  storage?: Array<Record<string, unknown>> | null;
  nodes?: string[] | null;
  error?: string | null;
}

interface StorageRow {
  storage?: string;
  content?: string;
  avail_bytes?: number;
  total_bytes?: number;
}

interface StoragePayload {
  items?: StorageRow[];
  total?: number;
}

interface TemplateStatus {
  ready?: boolean;
  template?: string;
  vmid?: number | null;
  error?: string | null;
  available?: string[] | null;
}

/** Q22: one ORPHANED asset row, preview + cleanup. */
interface OrphanRow {
  asset_id: number;
  run_id: number;
  run_status: string;
  role: string;
  pve_vmid: number | null;
  pve_node: string | null;
  error: string | null;
  age_seconds: number;
}

interface OrphanListResponse {
  items?: OrphanRow[];
  total?: number;
}

interface CleanupFailure {
  asset_id: number;
  run_id: number;
  pve_vmid: number | null;
  error: string;
}

interface CleanupResponse {
  scanned: number;
  destroyed: number;
  failed: CleanupFailure[];
  skipped_running: number[];
}

export function PveOpsCard() {
  const [probe, setProbe] = useState<Probe | null>(null);
  const [storage, setStorage] = useState<StoragePayload | null>(null);
  const [tmpl, setTmpl] = useState<TemplateStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  // Q22: orphan-cleanup modal state. We hold the candidates list
  // (so the modal can show "you're about to destroy N VMs") and
  // the cleanup result (so we can show per-asset failure details).
  const [orphans, setOrphans] = useState<OrphanRow[] | null>(null);
  const [orphansTotal, setOrphansTotal] = useState(0);
  const [orphansError, setOrphansError] = useState<string | null>(null);
  const [orphansLoading, setOrphansLoading] = useState(false);
  const [cleanupModal, setCleanupModal] = useState<null | {
    candidates: OrphanRow[];
    graceMinutes: number;
  }>(null);
  const [cleanupResult, setCleanupResult] = useState<CleanupResponse | null>(
    null,
  );
  const [cleanupRunning, setCleanupRunning] = useState(false);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [p, s, t] = await Promise.all([
        api.get<Probe>("/api/v1/admin/probe"),
        api.get<StoragePayload>("/api/v1/admin/storage"),
        api.get<TemplateStatus>("/api/v1/admin/drill-template-status"),
      ]);
      setProbe(p);
      setStorage(s);
      setTmpl(t);
    } catch (e: unknown) {
      setError(detailFromError(e));
    } finally {
      setLoading(false);
    }
  }

  async function loadOrphans(graceMinutes: number) {
    setOrphansLoading(true);
    setOrphansError(null);
    try {
      const r = await api.get<OrphanListResponse>(
        `/api/v1/admin/assets/orphans?grace_minutes=${graceMinutes}`,
      );
      setOrphans(r.items ?? []);
      setOrphansTotal(r.total ?? 0);
    } catch (e: unknown) {
      setOrphansError(detailFromError(e));
      setOrphans([]);
      setOrphansTotal(0);
    } finally {
      setOrphansLoading(false);
    }
  }

  useEffect(() => {
    load();
    loadOrphans(5);
  }, []);

  const reachable =
    probe?.reachable === true &&
    (probe.error === null || probe.error === undefined);

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <div>
          <CardTitle>
            <span className="inline-flex items-center gap-2">
              <Activity className="h-4 w-4 text-muted-foreground" />
              PVE health
            </span>
          </CardTitle>
          <CardDescription>
            Read-only snapshot. Use the setup wizard at /portal/ for
            upload + create-template flows.
          </CardDescription>
        </div>
        <Button
          variant="ghost"
          size="icon"
          onClick={() => {
            load();
            loadOrphans(5);
          }}
          aria-label="Refresh"
        >
          {loading ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <RefreshCw className="h-4 w-4" />
          )}
        </Button>
      </CardHeader>
      <CardContent className="space-y-3">
        {error && (
          <div className="text-sm text-destructive">{error}</div>
        )}
        {!error && probe === null && (
          <div className="text-sm italic text-muted-foreground">
            Loading…
          </div>
        )}
{probe !== null && (
          <div className="space-y-1 text-sm">
            <div className="flex items-center gap-2">
              {reachable ? (
                <CheckCircle2 className="h-4 w-4 text-emerald-400" />
              ) : (
                <XCircle className="h-4 w-4 text-red-400" />
              )}
              <span className="font-mono">
                {reachable ? "reachable" : "unreachable"}
              </span>
              {probe.version ? (
                <span className="font-mono text-muted-foreground">
                  · {probe.version}
                </span>
              ) : null}
              {probe.pve_user ? (
                <span className="font-mono text-muted-foreground">
                  · {probe.pve_user}
                </span>
              ) : null}
            </div>
            <div className="text-xs text-muted-foreground">
              {probe.has_drill_privs === true ? (
                <span className="text-emerald-300">
                  drill privileges: ok
                </span>
              ) : (
                <span className="text-amber-300">
                  drill privileges: missing —{" "}
                  {probe.drill_privs_missing?.join(", ") || "unknown"}
                </span>
              )}
              {" · "}
              {probe.has_setup_privs === true ? (
                <span className="text-emerald-300">setup: ok</span>
              ) : (
                <span className="text-amber-300">
                  setup: missing —{" "}
                  {probe.setup_privs_missing?.join(", ") || "unknown"}
                </span>
              )}
            </div>
            {probe.nodes && probe.nodes.length > 0 ? (
              <div className="text-xs text-muted-foreground">
                nodes: {probe.nodes.join(", ")}
              </div>
            ) : null}
          </div>
        )}

        {storage !== null && (
          <div>
            <h4 className="mb-1 flex items-center gap-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              <HardDrive className="h-3 w-3" /> Storage pools
            </h4>
            {storage.items && storage.items.length > 0 ? (
              <ul className="divide-y divide-border rounded-md border border-border">
                {storage.items.map((s) => (
                  <li
                    key={s.storage}
                    className="flex items-center justify-between gap-3 px-3 py-1 text-xs font-mono"
                  >
                    <span>{s.storage}</span>
                    <span className="text-muted-foreground">
                      {s.content ?? ""}
                    </span>
                    <span className="text-muted-foreground">
                      {s.avail_bytes !== undefined
                        ? `${(s.avail_bytes / 1024 ** 3).toFixed(1)} GiB free`
                        : ""}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="text-xs italic text-muted-foreground">
                No storage pools reported.
              </div>
            )}
          </div>
        )}

        {tmpl !== null && (
          <div>
            <h4 className="mb-1 flex items-center gap-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              <Database className="h-3 w-3" /> Drill template
            </h4>
            <div className="text-sm">
              {tmpl.ready ? (
                <span className="inline-flex items-center gap-1 text-emerald-300">
                  <CheckCircle2 className="h-3 w-3" />
                  <span className="font-mono">
                    {tmpl.template ?? "tpl-debian-cloudinit"} ready
                    {tmpl.vmid !== null && tmpl.vmid !== undefined
                      ? ` (vmid=${tmpl.vmid})`
                      : ""}
                  </span>
                </span>
              ) : (
                <span className="inline-flex items-center gap-1 text-amber-300">
                  <XCircle className="h-3 w-3" />
                  <span className="font-mono">
                    {tmpl.template ?? "tpl-debian-cloudinit"} not ready
                    {tmpl.error ? ` — ${tmpl.error}` : ""}
                  </span>
                </span>
              )}
            </div>
          </div>
        )}

        {/* Q22: orphan-cleanup section. */}
        <div className="border-t pt-3">
          <h4 className="mb-2 flex items-center gap-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            <Trash2 className="h-3 w-3" /> Orphan VMs
          </h4>
          {orphansError && (
            <div
              className="text-xs text-destructive"
              data-testid="orphans-error"
            >
              {orphansError}
            </div>
          )}
          {!orphansError && orphans === null && (
            <div className="text-xs italic text-muted-foreground">
              Loading…
            </div>
          )}
          {!orphansError && orphans !== null && (
            <div
              className="flex items-center justify-between gap-2 text-sm"
              data-testid="orphans-summary"
            >
              <div className="flex items-center gap-2">
                {orphansTotal === 0 ? (
                  <span className="inline-flex items-center gap-1 text-emerald-300">
                    <CheckCircle2 className="h-3 w-3" />
                    <span className="font-mono">none</span>
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1 text-amber-300">
                    <AlertTriangle className="h-3 w-3" />
                    <span
                      className="font-mono"
                      data-testid="orphans-count"
                    >
                      {orphansTotal}
                    </span>
                    <span>asset{orphansTotal === 1 ? "" : "s"}</span>
                  </span>
                )}
                <span className="text-xs text-muted-foreground">
                  (older than 5 min, terminal run)
                </span>
              </div>
              <Button
                variant="outline"
                size="sm"
                disabled={orphansTotal === 0 || orphansLoading}
                onClick={() => {
                  // Open the modal with the previewed candidates;
                  // grace_minutes=0 inside the modal lets the operator
                  // see EVERY orphan (even fresh ones) on demand.
                  setCleanupResult(null);
                  setCleanupModal({
                    candidates: orphans ?? [],
                    graceMinutes: 0,
                  });
                }}
                data-testid="orphans-cleanup-button"
              >
                <Trash2 className="mr-1 h-3 w-3" />
                Clean up…
              </Button>
            </div>
          )}
        </div>
      </CardContent>
      {cleanupModal !== null && (
        <CleanupModal
          candidates={cleanupModal.candidates}
          graceMinutes={cleanupModal.graceMinutes}
          running={cleanupRunning}
          result={cleanupResult}
          onClose={() => {
            setCleanupModal(null);
            setCleanupResult(null);
          }}
          onApply={async (grace) => {
            setCleanupRunning(true);
            try {
              const r = await api.post<CleanupResponse>(
                "/api/v1/admin/assets/cleanup",
                { grace_minutes: grace },
              );
              setCleanupResult(r);
              // Refresh the candidate list so the badge updates.
              await loadOrphans(5);
            } catch (e: unknown) {
              // Surface as a synthetic result so the modal shows it.
              setCleanupResult({
                scanned: 0,
                destroyed: 0,
                failed: [],
                skipped_running: [],
              });
              setOrphansError(detailFromError(e));
            } finally {
              setCleanupRunning(false);
            }
          }}
        />
      )}
    </Card>
  );
}

/**
 * CleanupModal — preview + apply orphan cleanup.
 *
 * Preview is already loaded when the modal opens (the parent
 * fetched candidates via GET /assets/orphans). Apply posts the
 * grace_minutes override; 0 means "destroy every orphan including
 * fresh ones" — only valid because the operator just clicked.
 */
function CleanupModal(props: {
  candidates: OrphanRow[];
  graceMinutes: number;
  running: boolean;
  result: CleanupResponse | null;
  onClose: () => void;
  onApply: (graceMinutes: number) => void | Promise<void>;
}) {
  const { candidates, graceMinutes, running, result, onClose, onApply } = props;
  return (
    <div
      data-testid="cleanup-modal"
      role="dialog"
      aria-modal="true"
      aria-label="Clean up orphaned VMs"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={(e) => {
        if (e.target === e.currentTarget && !running) onClose();
      }}
    >
      <Card className="w-full max-w-2xl">
        <CardHeader className="flex-row items-start justify-between space-y-0">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <Trash2 className="h-4 w-4 text-amber-400" />
              Clean up orphaned VMs
            </CardTitle>
            <CardDescription>
              Q17 leaves an asset row in <code>ORPHANED</code> when
              the teardown loop fails to <code>destroy_vm</code>. This
              retries the destroy. Idempotent — re-running is safe.
            </CardDescription>
          </div>
          <Button
            variant="ghost"
            size="icon"
            onClick={onClose}
            disabled={running}
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </Button>
        </CardHeader>
        <CardContent className="space-y-3">
          {result === null ? (
            <>
              <div className="text-sm">
                <strong data-testid="cleanup-candidate-count">
                  {candidates.length}
                </strong>{" "}
                candidate{candidates.length === 1 ? "" : "s"} selected.
              </div>
              {candidates.length > 0 ? (
                <ul
                  className="max-h-64 overflow-y-auto divide-y divide-border rounded-md border border-border text-xs font-mono"
                  data-testid="cleanup-candidate-list"
                >
                  {candidates.map((c) => (
                    <li
                      key={c.asset_id}
                      className="flex items-center justify-between gap-2 px-3 py-1"
                    >
                      <span>asset #{c.asset_id}</span>
                      <span>run #{c.run_id}</span>
                      <span>
                        vmid={c.pve_vmid ?? "?"}/{c.pve_node ?? "?"}
                      </span>
                      <span>{c.role}</span>
                      <span className="text-muted-foreground">
                        {Math.floor(c.age_seconds / 60)}m old
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="text-sm italic text-muted-foreground">
                  No orphans to clean up.
                </div>
              )}
              <div className="flex items-center justify-end gap-2 pt-2">
                <Button
                  variant="ghost"
                  onClick={onClose}
                  disabled={running}
                >
                  Cancel
                </Button>
                <Button
                  variant="destructive"
                  onClick={() => onApply(graceMinutes)}
                  disabled={candidates.length === 0 || running}
                  data-testid="cleanup-apply-button"
                >
                  {running ? (
                    <>
                      <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                      Cleaning up…
                    </>
                  ) : (
                    <>
                      <Trash2 className="mr-1 h-3 w-3" />
                      Apply cleanup
                    </>
                  )}
                </Button>
              </div>
            </>
          ) : (
            <div className="space-y-2 text-sm" data-testid="cleanup-result">
              <div className="flex items-center gap-2">
                {result.destroyed > 0 ? (
                  <CheckCircle2 className="h-4 w-4 text-emerald-400" />
                ) : (
                  <AlertTriangle className="h-4 w-4 text-amber-400" />
                )}
                <span>
                  Scanned <strong>{result.scanned}</strong>, destroyed{" "}
                  <strong data-testid="cleanup-destroyed-count">
                    {result.destroyed}
                  </strong>
                  , failed{" "}
                  <strong data-testid="cleanup-failed-count">
                    {result.failed.length}
                  </strong>
                  .
                </span>
              </div>
              {result.failed.length > 0 && (
                <ul className="space-y-1 rounded-md border border-amber-700 bg-amber-950/30 p-2 text-xs">
                  {result.failed.map((f) => (
                    <li key={f.asset_id} className="font-mono">
                      asset #{f.asset_id} vmid={f.pve_vmid ?? "?"}:{" "}
                      {f.error}
                    </li>
                  ))}
                </ul>
              )}
              {result.skipped_running.length > 0 && (
                <div className="text-xs text-amber-300">
                  Skipped {result.skipped_running.length} live-run
                  asset{result.skipped_running.length === 1 ? "" : "s"}.
                </div>
              )}
              <div className="flex items-center justify-end pt-2">
                <Button onClick={onClose}>Close</Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
