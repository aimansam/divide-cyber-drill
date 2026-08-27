/**
 * ConfigCard -- the canonical "is this thing healthy, and how do I fix it"
 * surface for div:ide operators.
 *
 * Single-page aggregator that consolidates the four read-only probes an
 * operator needs to inspect their deployment:
 *
 *   1. PVE connection    -- GET /api/v1/admin/pve-config
 *                           (DB row vs env fallback, masked token, last update)
 *   2. PVE reachability  -- GET /api/v1/admin/pve-sdn-status
 *                           (reachable? SDN.Allocate? zone? vnets?)
 *   3. PVE bridges       -- GET /api/v1/admin/pve-bridge-status
 *                           (expected vs present vs missing)
 *   4. Drill template    -- GET /api/v1/admin/drill-template-status
 *                           (tpl-debian-cloudinit ready?)
 *
 * The card also exposes a single "Edit PVE credentials" button that opens
 * the wizard's existing PveCredentialsStep in a modal, and a "Recreate
 * bridges" button that hits POST /api/v1/admin/pve-setup-bridges for the
 * case where SDN is reachable but VNet creation is needed.
 *
 * This is intentionally READ-ONLY outside of those two actions. Scenarios
 * and users still live in the Admin tab -- this card is for the runtime
 * PVE link, which is what every drill-start error leads to.
 *
 * Roles: admin + lead (mirrors the Admin tab's gate).
 */

import { useCallback, useEffect, useState } from "react";
import {
  Activity,
  AlertCircle,
  CheckCircle2,
  HardDrive,
  KeyRound,
  Loader2,
  Network,
  RefreshCw,
  Server,
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
import {
  api,
  archiveScenario,
  detailFromError,
  getExpectedBridges,
  getPveConfig,
  getServiceStatus,
  type PveConfigPublic,
  type ServiceStatus,
} from "@/lib/api";
import { PveCredentialsStep } from "./pve-credentials-step";
import {
  TroubleshootPlaybook,
  type TroubleshootProbe,
} from "./troubleshoot-playbook";
import { hasRole, type Role } from "@/lib/roles";

interface PveSdnStatus {
  reachable: boolean;
  zone_present: boolean;
  zone_name: string;
  vnets_present: string[];
  vnets_missing: string[];
  error: string | null;
  pveum_hint: string | null;
  required_role: string | null;
}

interface PveBridgeStatus {
  node: string;
  expected: string[];
  present: string[];
  missing: string[];
}

interface TemplateStatus {
  ready: boolean;
  template: string;
  vmid: number | null;
}

interface PveSetupBridgesResponse {
  created: string[];
  reused: string[];
  zone_created: boolean;
  message: string;
}

interface ConfigCardProps {
  meRole: Role;
  /**
   * Optional: jump to another view (e.g. "admin" when the operator
   * needs to see Scenarios after archiving). Mirrors the same
   * navigation pattern used by the wizard's onNavigateToConfig.
   */
  onNavigateToView?: (view: "admin" | "operate" | "dashboard") => void;
}

export function ConfigCard({ meRole, onNavigateToView }: ConfigCardProps) {
const [pveConfig, setPveConfig] = useState<PveConfigPublic | null>(null);
  const [sdn, setSdn] = useState<PveSdnStatus | null>(null);
  const [bridges, setBridges] = useState<PveBridgeStatus | null>(null);
  const [template, setTemplate] = useState<TemplateStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);
  const [showCredsModal, setShowCredsModal] = useState(false);
  const [settingUpBridges, setSettingUpBridges] = useState(false);
  const [serviceStatus, setServiceStatus] = useState<ServiceStatus | null>(
    null,
  );
  const [bridgeConflicts, setBridgeConflicts] = useState<string[]>([]);
  const [expectedBridges, setExpectedBridges] = useState<
    Array<{ name: string; cidr: string; scenario: string }>
  >([]);
  /** Inline error for the Bridges card (separate from the top-level
   * load-error). Shows the user the immediate reason a "Recreate"
   * click failed. */
  const [bridgeActionError, setBridgeActionError] = useState<string | null>(
    null,
  );

  // Aggregated probe passed to TroubleshootPlaybook. Built fresh each
  // render so the playbook always sees the latest snapshot.
  const troubleshootProbe: TroubleshootProbe = {
    pveReachable: sdn?.reachable,
    pveConfigSource: pveConfig?.source ?? null,
    sdnError: sdn?.error ?? null,
    sdnRequiredRole: sdn?.required_role ?? null,
    sdnPveumHint: sdn?.pveum_hint ?? null,
    bridgesMissing: bridges?.missing ?? [],
    bridgesPresent: bridges?.present ?? [],
    bridgeConflicts,
    expectedBridges,
    templateReady: template?.ready ?? null,
  };

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // Single round-trip per probe -- these are independent so we fire
      // them in parallel; failure of one doesn't block the others.
      const [cfg, s, b, t, ss, eb] = await Promise.allSettled([
        getPveConfig(),
        api.get<PveSdnStatus>("/api/v1/admin/pve-sdn-status"),
        api.get<PveBridgeStatus>("/api/v1/admin/pve-bridge-status"),
        api.get<TemplateStatus>("/api/v1/admin/drill-template-status"),
        getServiceStatus(),
        getExpectedBridges(),
      ]);
      if (cfg.status === "fulfilled") setPveConfig(cfg.value);
      else setPveConfig(null);
      if (s.status === "fulfilled") setSdn(s.value);
      else setSdn(null);
      if (b.status === "fulfilled") setBridges(b.value);
      else setBridges(null);
      if (t.status === "fulfilled") setTemplate(t.value);
      else setTemplate(null);
      if (ss.status === "fulfilled") setServiceStatus(ss.value);
      else setServiceStatus(null);
      if (eb.status === "fulfilled") {
        setBridgeConflicts(eb.value.conflicts);
        setExpectedBridges(
          eb.value.bridges.map((b) => ({
            name: b.name,
            cidr: b.cidr,
            scenario: b.scenario,
          })),
        );
      } else {
        setBridgeConflicts([]);
        setExpectedBridges([]);
      }
      // If every probe failed, surface the first failure's message so the
      // operator knows it's a real outage (typically 401/403 -- token is
      // stale or insufficient role) rather than an empty state.
      if (
        cfg.status === "rejected" &&
        s.status === "rejected" &&
        b.status === "rejected" &&
        t.status === "rejected"
      ) {
        setError(detailFromError(cfg.reason));
      }
      setLastRefresh(new Date());
    } catch (e: unknown) {
      setError(detailFromError(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function onSetupBridges() {
    setSettingUpBridges(true);
    setBridgeActionError(null);
    try {
      await api.post<PveSetupBridgesResponse>(
        "/api/v1/admin/pve-setup-bridges",
        {},
      );
      await load();
    } catch (e: unknown) {
      // Inline error under the Bridges card so the operator sees the
      // cause right where they clicked (was previously off-screen at
      // the top of the page).
      setBridgeActionError(detailFromError(e));
    } finally {
      setSettingUpBridges(false);
    }
  }

  /**
   * Called by TroubleshootPlaybook when the operator clicks "Archive
   * scenario X". Handles the three value shapes:
   *   - "phish-to-ransom"  -> archive that scenario, refresh
   *   - "red-vs-blue-baseline" -> same
   *   - "__open_admin__"   -> just jump to Admin tab
   */
  async function onArchiveScenario(name: string) {
    if (name === "__open_admin__") {
      onNavigateToView?.("admin");
      return;
    }
    try {
      await archiveScenario(name);
      // Refresh so the playbook updates (conflict gone, bridges re-fetched).
      await load();
    } catch (e: unknown) {
      setBridgeActionError(
        `Failed to archive '${name}': ${detailFromError(e)}`,
      );
    }
  }

  if (!hasRole(meRole, ["admin", "lead"])) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Config</CardTitle>
          <CardDescription>
            You need admin or drill-lead to inspect PVE configuration.
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }
return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">Deployment configuration</h2>
          <p className="text-sm text-muted-foreground">
            Single page for everything PVE. Read-only except where noted.
            {lastRefresh && (
              <span className="ml-2 text-xs">
                last refreshed{" "}
                {lastRefresh.toLocaleTimeString([], {
                  hour: "2-digit",
                  minute: "2-digit",
                  second: "2-digit",
                })}
              </span>
            )}
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => void load()}
          disabled={loading}
        >
          {loading ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <RefreshCw className="h-4 w-4" />
          )}
          <span className="ml-2">Refresh</span>
        </Button>
      </div>

      {error && (
        <div className="rounded-md border border-destructive/50 bg-destructive/10 p-3 text-sm text-destructive">
          {error}
        </div>
      )}

      <TroubleshootPlaybook
        probe={troubleshootProbe}
        onArchiveScenario={(name) => void onArchiveScenario(name)}
      />

      {/* Deployment status -- live wg-easy / WG env / disk / audit */}
      {serviceStatus && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Server className="h-5 w-5 text-primary" /> Deployment status
            </CardTitle>
            <CardDescription>
              One-shot snapshot of every host-level dependency the API
              needs. Updated on{" "}
              {new Date(serviceStatus.captured_at).toLocaleTimeString([], {
                hour: "2-digit",
                minute: "2-digit",
                second: "2-digit",
              })}
              .
            </CardDescription>
          </CardHeader>
          <CardContent className="grid grid-cols-1 gap-3 text-sm sm:grid-cols-2">
            {/* wg-easy */}
            <div className="rounded border border-border p-3">
              <div className="flex items-center justify-between">
                <span className="font-medium">wg-easy</span>
                {serviceStatus.wg_easy.state === "up" ? (
                  <span className="flex items-center gap-1 text-emerald-500">
                    <CheckCircle2 className="h-4 w-4" /> up
                  </span>
                ) : (
                  <span className="flex items-center gap-1 text-destructive">
                    <XCircle className="h-4 w-4" /> unreachable
                  </span>
                )}
              </div>
              <div className="mt-1 text-xs text-muted-foreground">
                probed {serviceStatus.wg_easy.target}
                {serviceStatus.wg_easy.error && (
                  <div className="mt-1 font-mono text-[11px] text-destructive">
                    {serviceStatus.wg_easy.error}
                  </div>
                )}
              </div>
            </div>

            {/* WireGuard env */}
            <div className="rounded border border-border p-3">
              <div className="flex items-center justify-between">
                <span className="font-medium">WireGuard env</span>
                {serviceStatus.wireguard.ready ? (
                  <span className="flex items-center gap-1 text-emerald-500">
                    <CheckCircle2 className="h-4 w-4" /> ready
                  </span>
                ) : (
                  <span className="flex items-center gap-1 text-amber-500">
                    <XCircle className="h-4 w-4" /> not ready
                  </span>
                )}
              </div>
              <div className="mt-1 space-y-1 text-xs text-muted-foreground">
                <div>
                  WG_HOST:{" "}
                  <span className="font-mono">
                    {serviceStatus.wireguard.wg_host ?? "(unset)"}
                  </span>
                </div>
                <div>
                  DIVIDE_WG_PEER_SECRET:{" "}
                  <span className="font-mono">
                    {serviceStatus.wireguard.peer_secret_set
                      ? "<set>"
                      : "(unset)"}
                  </span>
                </div>
                <div>
                  WG_DEFAULT_DNS:{" "}
                  <span className="font-mono">
                    {serviceStatus.wireguard.wg_default_dns ?? "(unset)"}
                  </span>
                </div>
              </div>
              {!serviceStatus.wireguard.ready && (
                <p className="mt-2 text-xs text-muted-foreground">
                  Set these in <span className="font-mono">deploy/.env</span>{" "}
                  and restart the API container for changes to take effect.
                </p>
              )}
            </div>

            {/* Disk */}
            {"total_gb" in serviceStatus.disk && (
              <div className="rounded border border-border p-3">
                <div className="flex items-center justify-between">
                  <span className="font-medium">
                    Disk ({serviceStatus.disk.path})
                  </span>
                  <span
                    className={
                      serviceStatus.disk.percent_used > 90
                        ? "text-destructive"
                        : serviceStatus.disk.percent_used > 75
                          ? "text-amber-500"
                          : "text-emerald-500"
                    }
                  >
                    {serviceStatus.disk.percent_used}%
                  </span>
                </div>
                <div className="mt-1 text-xs text-muted-foreground">
                  {serviceStatus.disk.used_gb} GB used /{" "}
                  {serviceStatus.disk.total_gb} GB total
                </div>
                <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted">
                  <div
                    className={
                      serviceStatus.disk.percent_used > 90
                        ? "h-full bg-destructive"
                        : serviceStatus.disk.percent_used > 75
                          ? "h-full bg-amber-500"
                          : "h-full bg-emerald-500"
                    }
                    style={{
                      width: `${Math.min(100, serviceStatus.disk.percent_used)}%`,
                    }}
                  />
                </div>
              </div>
            )}

            {/* Audit recency */}
            <div className="rounded border border-border p-3">
              <div className="flex items-center justify-between">
                <span className="font-medium">Audit log</span>
                {serviceStatus.audit.state === "fresh" ? (
                  <span className="flex items-center gap-1 text-emerald-500">
                    <CheckCircle2 className="h-4 w-4" /> fresh
                  </span>
                ) : serviceStatus.audit.state === "stale" ? (
                  <span className="flex items-center gap-1 text-amber-500">
                    <XCircle className="h-4 w-4" /> stale
                  </span>
                ) : serviceStatus.audit.state === "empty" ? (
                  <span className="flex items-center gap-1 text-muted-foreground">
                    <XCircle className="h-4 w-4" /> empty
                  </span>
                ) : (
                  <span className="flex items-center gap-1 text-muted-foreground">
                    <XCircle className="h-4 w-4" /> unknown
                  </span>
                )}
              </div>
              <div className="mt-1 text-xs text-muted-foreground">
                {serviceStatus.audit.latest
                  ? `latest ${new Date(serviceStatus.audit.latest).toLocaleString()} (${
                      serviceStatus.audit.age_hours ?? "?"
                    }h ago)`
                  : "no audit rows yet"}
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* PVE connection card */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Server className="h-5 w-5 text-primary" /> PVE connection
          </CardTitle>
          <CardDescription>
            Where the API is reading its PVE credentials from, and who last
            changed them.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          {pveConfig === null ? (
            <div className="text-muted-foreground">
              no config available
              {error && " (see error above)"}
            </div>
          ) : (
            <>
              <Row label="Source">
                <span className="font-mono text-xs">
                  {pveConfig.source === "db"
                    ? `db row (updated ${
                        pveConfig.updated_at
                          ? new Date(pveConfig.updated_at).toLocaleString()
                          : "?"
                      }${
                        pveConfig.updated_by ? ` by ${pveConfig.updated_by}` : ""
                      })`
                    : "env fallback"}
                </span>
              </Row>
              <Row label="Host">
                <span className="font-mono">
                  {pveConfig.host ?? "(unset)"}
                </span>
              </Row>
              <Row label="User">
                <span className="font-mono">{pveConfig.user}</span>
              </Row>
              <Row label="Token ID">
                <span className="font-mono">
                  {pveConfig.token_id ?? "(unset)"}
                </span>
              </Row>
              <Row label="Token secret">
                <span className="font-mono">{pveConfig.token_secret}</span>
              </Row>
              <Row label="Verify SSL">
                {pveConfig.verify_ssl ? "yes" : "no (self-signed)"}
              </Row>
              <Row label="Node">{pveConfig.node ?? "(auto)"}</Row>
              <div className="pt-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setShowCredsModal(true)}
                >
                  <KeyRound className="h-4 w-4" />
                  <span className="ml-2">Edit credentials</span>
                </Button>
              </div>
            </>
          )}
        </CardContent>
      </Card>
{/* PVE reachability + SDN.Allocate */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Activity className="h-5 w-5 text-primary" /> PVE reachability
            &amp; permissions
          </CardTitle>
          <CardDescription>
            Live probe. SDN.Allocate is required to create bridges + VNets on
            PVE.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          {sdn === null ? (
            <div className="text-muted-foreground">unreachable</div>
          ) : (
            <>
              <Row label="Reachable">
                {sdn.reachable ? (
                  <span className="flex items-center gap-1 text-emerald-500">
                    <CheckCircle2 className="h-4 w-4" /> yes
                  </span>
                ) : (
                  <span className="flex items-center gap-1 text-destructive">
                    <XCircle className="h-4 w-4" /> no
                  </span>
                )}
              </Row>
              <Row label={`SDN zone "${sdn.zone_name}"`}>
                {sdn.zone_present ? (
                  <span className="flex items-center gap-1 text-emerald-500">
                    <CheckCircle2 className="h-4 w-4" /> present
                  </span>
                ) : (
                  <span className="flex items-center gap-1 text-amber-500">
                    <XCircle className="h-4 w-4" /> missing
                  </span>
                )}
              </Row>
              {sdn.error && (
                <div className="rounded-md border border-destructive/40 bg-destructive/10 p-2 text-xs text-destructive">
                  {sdn.error}
                  {sdn.pveum_hint && (
                    <pre className="mt-1 whitespace-pre-wrap font-mono text-[11px]">
                      {sdn.pveum_hint}
                    </pre>
                  )}
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>

      {/* Bridges */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Network className="h-5 w-5 text-primary" /> PVE bridges
          </CardTitle>
          <CardDescription>
            Expected ({bridges?.expected.length ?? "?"}) vs present on node{" "}
            <span className="font-mono">{bridges?.node ?? "pve"}</span>.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          {bridges === null ? (
            <div className="text-muted-foreground">no data</div>
          ) : (
            <>
              {bridgeConflicts.length > 0 && (
                <div className="rounded-md border border-destructive/50 bg-destructive/10 p-3 text-xs text-destructive">
                  <div className="flex items-start gap-2">
                    <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                    <div className="flex-1 space-y-1">
                      <div className="font-medium">
                        {bridgeConflicts.length} bridge plan conflict
                        {bridgeConflicts.length === 1 ? "" : "s"} block the
                        Recreate button:
                      </div>
                      <ul className="ml-4 list-disc space-y-0.5 font-mono">
                        {bridgeConflicts.map((c, i) => (
                          <li key={i}>{c}</li>
                        ))}
                      </ul>
                      <div className="pt-1 text-foreground">
                        Fix it from the Troubleshoot card above (Archive
                        button) or via Admin → Scenarios.
                      </div>
                    </div>
                  </div>
                </div>
              )}
              {bridgeActionError && (
                <div className="rounded-md border border-destructive/40 bg-destructive/10 p-2 text-xs text-destructive">
                  <div className="flex items-start gap-2">
                    <AlertCircle className="mt-0.5 h-3 w-3 shrink-0" />
                    <span className="font-mono whitespace-pre-wrap">
                      {bridgeActionError}
                    </span>
                  </div>
                </div>
              )}
              <div className="grid grid-cols-1 gap-1 sm:grid-cols-2">
                {bridges.expected.map((b) => {
                  const present = bridges.present.includes(b);
                  return (
                    <div
                      key={b}
                      className="flex items-center justify-between rounded border border-border px-2 py-1 font-mono text-xs"
                    >
                      <span>{b}</span>
                      {present ? (
                        <span className="flex items-center gap-1 text-emerald-500">
                          <CheckCircle2 className="h-3 w-3" /> present
                        </span>
                      ) : (
                        <span className="flex items-center gap-1 text-amber-500">
                          <XCircle className="h-3 w-3" /> missing
                        </span>
                      )}
                    </div>
                  );
                })}
              </div>
              {bridges.missing.length > 0 && (
                <div className="pt-2">
                  <Button
                    variant="default"
                    size="sm"
                    onClick={() => void onSetupBridges()}
                    disabled={
                      settingUpBridges ||
                      !sdn?.reachable ||
                      bridgeConflicts.length > 0
                    }
                  >
                    {settingUpBridges ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <HardDrive className="h-4 w-4" />
                    )}
                    <span className="ml-2">
                      Recreate {bridges.missing.length} bridge
                      {bridges.missing.length === 1 ? "" : "s"}
                    </span>
                  </Button>
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>
{/* Drill template */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <HardDrive className="h-5 w-5 text-primary" /> Drill template
          </CardTitle>
          <CardDescription>
            The canonical <span className="font-mono">tpl-debian-cloudinit</span>{" "}
            VMID that every drill clones from.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          {template === null ? (
            <div className="text-muted-foreground">unreachable</div>
          ) : template.ready ? (
            <Row label="Status">
              <span className="flex items-center gap-1 text-emerald-500">
                <CheckCircle2 className="h-4 w-4" /> ready
              </span>
            </Row>
          ) : (
            <Row label="Status">
              <span className="flex items-center gap-1 text-amber-500">
                <XCircle className="h-4 w-4" /> not built
              </span>
            </Row>
          )}
          {template && (
            <Row label="Template">
              <span className="font-mono">{template.template}</span>
            </Row>
          )}
          {template?.vmid && (
            <Row label="VMID">
              <span className="font-mono">{template.vmid}</span>
            </Row>
          )}
        </CardContent>
      </Card>

      {/* Quick links */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Quick links</CardTitle>
          <CardDescription>
            Other configuration surfaces live elsewhere.
          </CardDescription>
        </CardHeader>
        <CardContent className="text-sm">
          <ul className="ml-4 list-disc space-y-1 text-muted-foreground">
            <li>
              Scenarios (YAML import / archive / restore) → Admin tab
            </li>
            <li>
              Users (create / reset password / role change) → Admin tab
            </li>
            <li>Audit log (who did what to PVE) → History → Audit</li>
          </ul>
        </CardContent>
      </Card>

      {/* Edit credentials modal */}
      {showCredsModal && pveConfig && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 p-4"
          onClick={() => setShowCredsModal(false)}
        >
          <div
            className="w-full max-w-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <PveCredentialsStep
              onContinue={() => {
                setShowCredsModal(false);
                void load();
              }}
              onSkip={() => setShowCredsModal(false)}
            />
          </div>
        </div>
      )}
    </div>
  );
}

function Row({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-2 border-b border-border/50 pb-1 last:border-0">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right">{children}</span>
    </div>
  );
}
