/**
 * AssetsCard — copy-to-clipboard SSH/VPN target for each asset.
 *
 * Drives off the `pickedRunId` prop (the same one `MyRunsCard`
 * emits when a row is clicked). We re-fetch `GET /drills/{id}`
 * here for the canonical asset list — `RunLifecycleCard` keeps
 * its own copy because it also shows run status + cancel button,
 * and it's racy to share React state for two cards.
 *
 * Each asset row shows: role/kind, IP (copy-to-clipboard), vmid,
 * node, status. Trainees connect to the VM over WireGuard VPN
 * (see the VPN config download on the drill start screen) then
 * SSH to the copied IP.
 *
 * Roles: everyone (with `can_view_run` enforced server-side).
 * Copy-to-clipboard falls back to execCommand for older browsers.
 */

import { useEffect, useState } from "react";
import { Clipboard, ClipboardCheck, RefreshCw, Server, CheckCircle2, AlertCircle, XCircle, Trash2, Terminal } from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { api, detailFromError } from "@/lib/api";
import type { RunAsset } from "@/components/portal/run-lifecycle-card";

interface RunPayload {
  run_id: number;
  scenario_id?: number;
  status: string;
  assets?: RunAsset[];
}

interface AssetSyncStatus {
  asset_id: number;
  db_status: string;
  pve_status: string;
  synced: boolean;
  drifted: boolean;
  cleaned_at: string | null;
  pve_ip: string | null;
  last_synced_at: string;
}

export function AssetsCard({
  pickedRunId,
  compact = false,
  onOpenConsole,
}: {
  pickedRunId: number | null;
  compact?: boolean;
  onOpenConsole?: (asset: { asset_id: number; role?: string }) => void;
}) {
  const [assets, setAssets] = useState<RunAsset[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [copiedVmid, setCopiedVmid] = useState<number | null>(null);
  // Q26: per-asset sync state. Keyed by asset_id.
  const [syncStatuses, setSyncStatuses] = useState<Record<number, AssetSyncStatus>>({});
  const [syncingAssetId, setSyncingAssetId] = useState<number | null>(null);
  const [syncingAll, setSyncingAll] = useState(false);
  const [syncError, setSyncError] = useState<string | null>(null);
  // Q27: per-asset delete state.
  const [deletingAssetId, setDeletingAssetId] = useState<number | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

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
        setError(detailFromError(e));
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

  // Q26: sync a single asset's status with PVE.
  async function syncAsset(assetId: number) {
    if (pickedRunId === null) return;
    setSyncingAssetId(assetId);
    setSyncError(null);
    try {
      const status = await api.post<AssetSyncStatus>(
        `/api/v1/drills/${pickedRunId}/assets/${assetId}/sync-status`,
      );
      setSyncStatuses((prev) => ({ ...prev, [assetId]: status }));
      // If drifted, refresh the asset list to show updated status.
      if (status.drifted) {
        const r = await api.get<RunPayload>(`/api/v1/drills/${pickedRunId}`);
        setAssets(r.assets ?? []);
      }
    } catch (e: unknown) {
      const msg = detailFromError(e);
      setSyncError(`Sync failed for asset ${assetId}: ${msg}`);
    } finally {
      setSyncingAssetId(null);
    }
  }

  // Q26: sync all assets in parallel.
  async function syncAll() {
    if (pickedRunId === null || assets.length === 0) return;
    setSyncingAll(true);
    setSyncError(null);
    try {
      const promises = assets
        .filter((a) => a.asset_id !== undefined)
        .map((a) => syncAsset(a.asset_id!));
      await Promise.allSettled(promises);
    } finally {
      setSyncingAll(false);
    }
  }

  // Q26: auto-refresh sync status for live runs every 30s.
  useEffect(() => {
    if (pickedRunId === null || assets.length === 0) return;
    // Only auto-sync for live runs (running/pending).
    const runStatus = assets[0]?.status;
    const isLive = runStatus === "running" || runStatus === "pending" || runStatus === "booting";
    if (!isLive) return;

    const id = window.setInterval(() => {
      void syncAll();
    }, 30000);
    return () => window.clearInterval(id);
  }, [pickedRunId, assets.length]);

  // Q27: delete a single asset's VM from PVE.
  async function deleteAsset(assetId: number) {
    if (pickedRunId === null) return;
    const confirmed = window.confirm(
      `Delete VM ${assetId} from PVE? This cannot be undone.`,
    );
    if (!confirmed) return;

    setDeletingAssetId(assetId);
    setDeleteError(null);
    try {
      const res = await api.post<{pve_vmid: number; pve_node: string; cleaned_at: string}>(`/runs/${pickedRunId}/assets/${assetId}/delete`, {
        confirm: true,
      });
      // Q27: update sync status to show as cleaned.
      setSyncStatuses((prev) => ({
        ...prev,
        [assetId]: {
          asset_id: assetId,
          db_status: "stopped",
          pve_vmid: res.pve_vmid,
          pve_node: res.pve_node,
          synced: true,
          drifted: false,
          pve_status: "stopped",
          cleaned_at: res.cleaned_at,
          pve_ip: null,
          last_synced_at: new Date().toISOString(),
        },
      }));
    } catch (e) {
      setDeleteError(detailFromError(e));
    } finally {
      setDeletingAssetId(null);
    }
  }

  // Q26: format "synced X ago" for display.
  function formatSyncAgo(iso: string): string {
    const t = Date.parse(iso);
    if (Number.isNaN(t)) return "";
    const deltaMs = Date.now() - t;
    const sec = Math.floor(deltaMs / 1000);
    if (sec < 60) return `${sec}s ago`;
    const min = Math.floor(sec / 60);
    if (min < 60) return `${min}m ago`;
    const hr = Math.floor(min / 60);
    return `${hr}h ago`;
  }

  return (
    <Card>
      {!compact && (
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle>Assets</CardTitle>
              <CardDescription>
                {pickedRunId === null
                  ? "Click a run in My runs / All runs to see its assets."
                  : `Run #${pickedRunId} — ${assets.length} asset${assets.length === 1 ? "" : "s"}`}
              </CardDescription>
            </div>
            {/* Q26: Sync All button */}
            {pickedRunId !== null && assets.length > 0 && (
              <Button
                variant="outline"
                size="sm"
                onClick={syncAll}
                disabled={syncingAll}
                aria-label="sync all assets with PVE"
              >
                <RefreshCw className={`mr-1 h-3.5 w-3.5 ${syncingAll ? "animate-spin" : ""}`} />
                {syncingAll ? "Syncing…" : "Sync all"}
              </Button>
            )}
          </div>
        </CardHeader>
      )}
      <CardContent>
        {loading && (
          <div className="text-sm italic text-muted-foreground">Loading…</div>
        )}
        {error && (
          <div className="text-sm text-destructive">{error}</div>
        )}
        {/* Q26: sync error display */}
        {syncError && (
          <div className="mb-2 rounded-md border border-amber-700 bg-amber-950/40 px-3 py-2 text-sm text-amber-200">
            {syncError}
          </div>
        )}
        {/* Q27: delete error display */}
        {deleteError && (
          <div className="mb-2 rounded-md border border-red-700 bg-red-950/40 px-3 py-2 text-sm text-red-200">
            {deleteError}
          </div>
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
                  <div className="flex flex-col items-end gap-0.5">
                    <span className="font-mono text-xs text-muted-foreground">
                      {a.status ?? "?"}
                    </span>
                    {/* Q26: last synced timestamp */}
                    {syncStatuses[a.asset_id ?? 0]?.last_synced_at && (
                      <span className="text-[10px] text-muted-foreground/60">
                        synced {formatSyncAgo(syncStatuses[a.asset_id ?? 0].last_synced_at)}
                      </span>
                    )}
                  </div>
                  {/* Q26: sync status badge */}
                  {syncStatuses[a.asset_id ?? 0] && (() => {
                    const s = syncStatuses[a.asset_id ?? 0];
                    if (s.pve_status === "missing") {
                      return <span title="VM deleted from PVE"><XCircle className="h-3.5 w-3.5 text-red-400" /></span>;
                    }
                    if (s.drifted) {
                      return <span title="DB status differs from PVE"><AlertCircle className="h-3.5 w-3.5 text-amber-400" /></span>;
                    }
                    return <span title="Synced with PVE"><CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" /></span>;
                  })()}
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
                  {/* Q26: sync button */}
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label="sync status with PVE"
                    onClick={() => syncAsset(a.asset_id ?? 0)}
                    disabled={syncingAssetId === a.asset_id}
                  >
                    <RefreshCw className={`h-3.5 w-3.5 ${syncingAssetId === a.asset_id ? "animate-spin" : ""}`} />
                  </Button>
                  {/* F4: Open console button - only for running VMs */}
                  {onOpenConsole && a.status === "running" && a.pve_vmid && (
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label="open VM console"
                      onClick={() => onOpenConsole({ asset_id: a.asset_id ?? 0, role: a.role })}
                    >
                      <Terminal className="h-3.5 w-3.5" />
                    </Button>
                  )}
                  {/* Q27: delete button */}
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label="delete VM from PVE"
                    onClick={() => deleteAsset(a.asset_id ?? 0)}
                    disabled={deletingAssetId === a.asset_id || !a.pve_vmid}
                  >
                    <Trash2 className={`h-3.5 w-3.5 ${deletingAssetId === a.asset_id ? "animate-pulse" : ""}`} />
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