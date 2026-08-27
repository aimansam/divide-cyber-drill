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
  detailFromError,
  getPveConfig,
  type PveConfigPublic,
} from "@/lib/api";
import { PveCredentialsStep } from "./pve-credentials-step";
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
}

export function ConfigCard({ meRole }: ConfigCardProps) {
const [pveConfig, setPveConfig] = useState<PveConfigPublic | null>(null);
  const [sdn, setSdn] = useState<PveSdnStatus | null>(null);
  const [bridges, setBridges] = useState<PveBridgeStatus | null>(null);
  const [template, setTemplate] = useState<TemplateStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);
  const [showCredsModal, setShowCredsModal] = useState(false);
  const [settingUpBridges, setSettingUpBridges] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // Single round-trip per probe -- these are independent so we fire
      // them in parallel; failure of one doesn't block the others.
      const [cfg, s, b, t] = await Promise.allSettled([
        getPveConfig(),
        api.get<PveSdnStatus>("/api/v1/admin/pve-sdn-status"),
        api.get<PveBridgeStatus>("/api/v1/admin/pve-bridge-status"),
        api.get<TemplateStatus>("/api/v1/admin/drill-template-status"),
      ]);
      if (cfg.status === "fulfilled") setPveConfig(cfg.value);
      else setPveConfig(null);
      if (s.status === "fulfilled") setSdn(s.value);
      else setSdn(null);
      if (b.status === "fulfilled") setBridges(b.value);
      else setBridges(null);
      if (t.status === "fulfilled") setTemplate(t.value);
      else setTemplate(null);
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
    setError(null);
    try {
      await api.post<PveSetupBridgesResponse>(
        "/api/v1/admin/pve-setup-bridges",
        {},
      );
      await load();
    } catch (e: unknown) {
      setError(detailFromError(e));
    } finally {
      setSettingUpBridges(false);
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
                    disabled={settingUpBridges || !sdn?.reachable}
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
