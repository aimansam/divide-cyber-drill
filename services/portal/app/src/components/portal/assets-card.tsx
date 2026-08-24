/**
 * AssetsCard — copy-to-clipboard SSH target for each asset on the
 * currently-picked run.
 *
 * Drives off the `pickedRunId` prop (the same one `MyRunsCard`
 * emits when a row is clicked). We re-fetch `GET /drills/{id}`
 * here for the canonical asset list — `RunLifecycleCard` keeps
 * its own copy because it also shows run status + cancel button,
 * and it's racy to share React state for two cards.
 *
 * Roles: everyone (with `can_view_run` enforced server-side; the
 * composition table already filters this card to admin/lead/red/blue
 * because blue/observer still see it — but they get 403 on the
 * underlying /drills/{id} call if the run isn't theirs).
 *
 * Copy-to-clipboard: a small "Copy" button next to each IP. Falls
 * back to a toast if the Clipboard API isn't available (rare;
 * HTTPS or localhost only).
 */

import { useEffect, useState } from "react";
import { Clipboard, ClipboardCheck, Server } from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { api, ApiError } from "@/lib/api";
import type { RunAsset } from "@/components/portal/run-lifecycle-card";

interface RunPayload {
  run_id: number;
  scenario_id?: number;
  status: string;
  assets?: RunAsset[];
}

export function AssetsCard({ pickedRunId, compact = false }: { pickedRunId: number | null; compact?: boolean }) {
  const [assets, setAssets] = useState<RunAsset[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [copiedVmid, setCopiedVmid] = useState<number | null>(null);

  useEffect(() => {
    if (pickedRunId === null) {
      setAssets([]);
      setError(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    api
      .get<RunPayload>(`/api/v1/drills/${pickedRunId}`)
      .then((r) => {
        if (cancelled) return;
        setAssets(r.assets ?? []);
        setError(null);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        const msg = e instanceof ApiError ? `HTTP ${e.status} ${e.url}` : String(e);
        setError(msg);
        setAssets([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [pickedRunId]);

  async function copy(text: string, vmid: number | null) {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        // Fallback for older browsers / insecure contexts.
        const ta = document.createElement("textarea");
        ta.value = text;
        ta.style.position = "fixed";
        ta.style.opacity = "0";
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        document.body.removeChild(ta);
      }
      setCopiedVmid(vmid);
      setTimeout(() => setCopiedVmid(null), 1500);
    } catch (e) {
      // Don't toast — the button just stays in its idle state. The
      // user can try again; clipboard permissions are flaky.
      void e;
    }
  }

  return (
    <Card>
      {!compact && (
        <CardHeader>
          <CardTitle>Assets</CardTitle>
          <CardDescription>
            {pickedRunId === null
              ? "Click a run in My runs / All runs to see its assets."
              : `Run #${pickedRunId} — ${assets.length} asset${assets.length === 1 ? "" : "s"}`}
          </CardDescription>
        </CardHeader>
      )}
      <CardContent>
        {loading && (
          <div className="text-sm italic text-muted-foreground">Loading…</div>
        )}
        {error && (
          <div className="text-sm text-destructive">{error}</div>
        )}
        {!loading && !error && assets.length === 0 && pickedRunId !== null && (
          <div className="text-sm italic text-muted-foreground">
            No assets yet. They appear once the run enters provisioning.
          </div>
        )}
        {!loading && !error && assets.length === 0 && pickedRunId === null && (
          <div className="text-sm italic text-muted-foreground">
            No run selected.
          </div>
        )}
        <ul className="divide-y divide-border">
          {assets.map((a) => {
            const sshTarget = a.pve_ip
              ? `divide@${a.pve_ip}`
              : a.pve_vmid !== null && a.pve_vmid !== undefined
                ? `vmid=${a.pve_vmid}`
                : a.role ?? "asset";
            return (
              <li
                key={a.asset_id ?? `${a.role}-${a.pve_vmid}-${a.pve_ip}`}
                className="flex items-center justify-between gap-3 px-2 py-2 text-sm"
              >
                <div className="flex items-start gap-2">
                  <Server className="mt-0.5 h-4 w-4 text-muted-foreground" />
                  <div>
                    <div className="font-mono">
                      {a.role ?? a.kind ?? "asset"}
                      {a.template ? (
                        <span className="text-muted-foreground">
                          {" "}
                          · {a.template}
                        </span>
                      ) : null}
                    </div>
                    <div className="font-mono text-xs text-muted-foreground">
                      {sshTarget}
                      {a.pve_vmid !== null && a.pve_vmid !== undefined ? (
                        <span className="ml-2">vmid={a.pve_vmid}</span>
                      ) : null}
                      {a.pve_node ? (
                        <span className="ml-2">node={a.pve_node}</span>
                      ) : null}
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <span className="font-mono text-xs text-muted-foreground">
                    {a.status ?? "?"}
                  </span>
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={
                      copiedVmid === a.pve_vmid
                        ? "copied"
                        : "copy SSH target"
                    }
                    onClick={() => copy(sshTarget, a.pve_vmid ?? null)}
                  >
                    {copiedVmid === a.pve_vmid ? (
                      <ClipboardCheck className="h-4 w-4 text-emerald-400" />
                    ) : (
                      <Clipboard className="h-4 w-4" />
                    )}
                  </Button>
                </div>
              </li>
            );
          })}
        </ul>
      </CardContent>
    </Card>
  );
}