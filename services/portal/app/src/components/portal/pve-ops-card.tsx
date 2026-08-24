/**
 * PveOpsCard — read-only PVE health summary for the admin.
 *
 * Calls three endpoints:
 *   * GET /api/v1/admin/probe               → PVE reachability +
 *                                              permissions +
 *                                              version + storage + nodes
 *   * GET /api/v1/admin/storage             → storage pools
 *                                              (also embedded in probe,
 *                                              but useful on its own)
 *   * GET /api/v1/admin/drill-template-status
 *                                            → is `tpl-debian-cloudinit`
 *                                              ready?
 *
 * The wizard at /portal/ is the operator's deploy surface and has
 * the upload-qcow2 / create-template / set-template / start-first-drill
 * flow. This card is the day-2 health check — "is PVE still OK?
 * Do I need to re-run the wizard?".
 *
 * Roles: admin only (composition table). Lead / red / blue / observer
 * don't get this card; if they tried to GET /admin/* they'd get 403
 * (the require_role(ADMIN) gate at the router level).
 */

import { useEffect, useState } from "react";
import {
  Activity,
  CheckCircle2,
  Database,
  HardDrive,
  Loader2,
  RefreshCw,
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
import { api, ApiError } from "@/lib/api";

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

export function PveOpsCard() {
  const [probe, setProbe] = useState<Probe | null>(null);
  const [storage, setStorage] = useState<StoragePayload | null>(null);
  const [tmpl, setTmpl] = useState<TemplateStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

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
      const msg = e instanceof ApiError ? `HTTP ${e.status} ${e.url}` : String(e);
      setError(msg);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
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
          onClick={load}
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
      </CardContent>
    </Card>
  );
}