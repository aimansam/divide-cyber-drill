/**
 * Step0PveSetup -- the PVE bridge provisioning step (F-pve-bridge-wizard).
 *
 * As of the F-pve-bridge-wizard (SDN variant) pivot, this step no
 * longer asks the operator to paste an SSH key into the browser. PVE
 * 8.1+ exposes ``/cluster/sdn/{zones,vnets}`` which creates Linux
 * bridges purely via API. The credentials saved in Step -1
 * (``POST /admin/pve-config``) are reused here.
 *
 * The wizard's only job in this step is:
 *
 *   1. Probe the API to confirm the active credentials can talk to PVE
 *      and that the operator's token has ``SDN.Allocate`` permission.
 *      If not, render a remediation card with a copy-pasteable
 *      ``pveum aclmod`` hint.
 *   2. POST to ``/admin/pve-setup-bridges`` to materialize the SDN
 *      zone + Vnets. PVE auto-propagates the bridges to each node.
 *   3. Surface the result (created / already-present Vnets, propagation
 *      status) and advance on success.
 *
 * The pre-flight banner is rendered from
 * ``GET /admin/pve-sdn-status`` (added in F-pve-bridge-wizard) so the
 * operator never sees a 403 mid-wizard -- they see the fix-it
 * instruction first.
 */

import { useEffect, useState } from "react";
import {
  ArrowRight,
  Check,
  Copy,
  Loader2,
  Network,
  ShieldAlert,
} from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";

// --- types ---------------------------------------------------------------

interface PveSetupBridgesResponse {
  ok: boolean;
  added: string[];
  already_present: string[];
  reload_ok: boolean;
  reload_method: string;
  verify_ok: boolean;
  message: string;
  dry_run: boolean;
  config_path?: string;
  // SDN-only field: rendered in dry-run to show the would-be plan.
  would_create_vnets?: string[];
}

interface SdnStatusResponse {
  reachable: boolean;
  zone_present: boolean;
  zone_name: string;
  vnets_present: string[];
  vnets_missing: string[];
  error?: string | null;
  pveum_hint?: string | null;
  required_role?: string | null;
}

interface ExpectedBridgesResponse {
  bridges: Array<{
    name: string;
    cidr: string;
    gateway_ip: string;
    scenario: string;
    network: string;
  }>;
  conflicts: string[];
}

interface Step0Props {
  onContinue: () => void;
  onSkip: () => void;
}

// --- helpers -------------------------------------------------------------

function detailFromError(e: unknown): string {
  if (
    e &&
    typeof e === "object" &&
    "body" in e &&
    (e as { body?: { detail?: unknown } }).body?.detail
  ) {
    const d = (e as { body: { detail: unknown } }).body.detail;
    if (typeof d === "string") return d;
    if (typeof d === "object" && d && "message" in d) {
      return String((d as { message: unknown }).message);
    }
    return JSON.stringify(d);
  }
  if (e && typeof e === "object" && "status" in e) {
    return `HTTP ${(e as { status: number }).status}`;
  }
  return e instanceof Error ? e.message : "Network error";
}

function authHeader(): Record<string, string> {
  if (typeof window === "undefined") return {};
  const tok = window.localStorage.getItem("divide_token") ?? "";
  return tok ? { "X-Divide-Token": tok } : {};
}

// --- main component ------------------------------------------------------

export function Step0PveSetup({ onContinue, onSkip }: Step0Props) {
  const [checking, setChecking] = useState(true);
  const [sdn, setSdn] = useState<SdnStatusResponse | null>(null);
  const [expected, setExpected] = useState<ExpectedBridgesResponse | null>(
    null,
  );
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<PveSetupBridgesResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copiedHint, setCopiedHint] = useState(false);
  const [probeTick, setProbeTick] = useState(0);

  // Pre-flight: check whether PVE is reachable and whether the token
  // has SDN.Allocate. We also pull the expected-bridges list so the
  // wizard can show "we'll create 8 Vnets" before the operator clicks.
  useEffect(() => {
    let cancelled = false;
    async function probe() {
      try {
        const headers = authHeader();
        const [sdnResp, expectedResp] = await Promise.all([
          fetch("/api/v1/admin/pve-sdn-status", { headers }).then((r) =>
            r.ok ? (r.json() as Promise<SdnStatusResponse>) : null,
          ),
          fetch("/api/v1/admin/expected-bridges", { headers }).then((r) =>
            r.ok ? (r.json() as Promise<ExpectedBridgesResponse>) : null,
          ),
        ]);

        if (cancelled) return;
        if (sdnResp) setSdn(sdnResp);
        if (expectedResp) setExpected(expectedResp);

        // If everything's already there, advance immediately.
        if (
          sdnResp &&
          sdnResp.reachable &&
          sdnResp.zone_present &&
          sdnResp.vnets_missing.length === 0 &&
          (!expectedResp || expectedResp.bridges.length === 0)
        ) {
          onContinue();
          return;
        }
      } catch (e) {
        if (cancelled) return;
        setError(`Probe failed: ${detailFromError(e)}`);
      } finally {
        if (!cancelled) setChecking(false);
      }
    }
    probe();
    return () => {
      cancelled = true;
    };
  }, [onContinue, probeTick]);

  async function onApply() {
    setError(null);
    setResult(null);
    setSubmitting(true);
    try {
      const headers: Record<string, string> = {
        "Content-Type": "application/json",
        ...authHeader(),
      };
      const resp = await fetch("/api/v1/admin/pve-setup-bridges", {
        method: "POST",
        headers,
        body: JSON.stringify({ dry_run: false }),
      });
      const parsed = (await resp.json().catch(() => ({}))) as Record<
        string,
        unknown
      >;
      if (!resp.ok) {
        // Pydantic 422 wraps the detail; SDN errors return a structured
        // detail object with {message, pveum_hint, required_role}.
        if (
          parsed &&
          typeof parsed.detail === "object" &&
          parsed.detail !== null
        ) {
          const d = parsed.detail as Record<string, unknown>;
          const msg =
            typeof d.message === "string" ? d.message : "PVE rejected";
          setError(msg);
        } else {
          const detail =
            (parsed && typeof parsed.detail === "string" && parsed.detail) ||
            `HTTP ${resp.status}`;
          setError(detail);
        }
        return;
      }
      setResult(parsed as unknown as PveSetupBridgesResponse);
      if ((parsed as unknown as PveSetupBridgesResponse).ok) {
        setTimeout(() => onContinue(), 800);
      }
    } catch (err) {
      setError(detailFromError(err));
    } finally {
      setSubmitting(false);
    }
  }

  function onRefresh() {
    setError(null);
    setResult(null);
    setSdn(null);
    setExpected(null);
    setProbeTick((n) => n + 1);
  }

  async function copyPveumHint() {
    if (!sdn?.pveum_hint) return;
    try {
      await navigator.clipboard.writeText(sdn.pveum_hint);
      setCopiedHint(true);
      setTimeout(() => setCopiedHint(false), 1500);
    } catch {
      // Clipboard unavailable -- ignore.
    }
  }

  if (checking) {
    return (
      <Card data-testid="step0-card">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Network className="h-5 w-5" />
            Set up PVE bridges
          </CardTitle>
          <CardDescription>
            Connecting to your Proxmox node via SDN.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            Probing PVE...
          </div>
        </CardContent>
      </Card>
    );
  }

  const bridgeCount = expected?.bridges.length ?? 0;
  const hasPermissionIssue =
    !!sdn?.pveum_hint || !!sdn?.error || (!!sdn && !sdn.reachable);
  const allDone =
    !!sdn &&
    sdn.reachable &&
    sdn.zone_present &&
    sdn.vnets_missing.length === 0 &&
    bridgeCount === 0;

  return (
    <Card data-testid="step0-card">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Network className="h-5 w-5" />
          Set up PVE bridges
        </CardTitle>
        <CardDescription>
          Creates the Linux bridges the runner needs, directly via the
          Proxmox API. No SSH, no host shell access -- just SDN.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {bridgeCount > 0 && (
          <div
            className="rounded-md border border-border bg-muted/40 px-3 py-2 text-sm"
            data-testid="step0-summary"
          >
            Will create <b>{bridgeCount}</b>{" "}
            {bridgeCount === 1 ? "bridge" : "bridges"} on PVE
            {sdn?.vnets_present.length ? (
              <>: {sdn.vnets_present.length} already present,{" "}
                {sdn.vnets_missing.length} to add</>
            ) : (
              <> (none yet)</>
            )}
            .
          </div>
        )}

        {allDone && (
          <div
            className="rounded-md border border-emerald-700 bg-emerald-950/40 px-3 py-2 text-sm text-emerald-200"
            data-testid="step0-already-done"
          >
            <Check className="mr-1 inline h-4 w-4" />
            All required bridges are already configured on PVE.
            Continuing to admin setup...
          </div>
        )}

        {hasPermissionIssue && sdn && (
          <div
            role="alert"
            data-testid="step0-permission-warning"
            className="rounded-md border border-amber-700 bg-amber-950/40 px-3 py-2 text-sm text-amber-100"
          >
            <div className="mb-1 flex items-center gap-1 font-medium">
              <ShieldAlert className="h-4 w-4" />
              {sdn.reachable
                ? "Token permission check failed"
                : "Cannot reach PVE"}
            </div>
            {sdn.error && (
              <div className="font-mono text-xs">{sdn.error}</div>
            )}
            {sdn.required_role && (
              <div className="mt-1 text-xs">
                Required role:{" "}
                <code className="rounded bg-black/30 px-1 py-0.5">
                  {sdn.required_role}
                </code>
              </div>
            )}
            {sdn.pveum_hint && (
              <div className="mt-2 flex items-center gap-2">
                <code
                  data-testid="step0-pveum-hint"
                  className="flex-1 rounded bg-black/40 px-2 py-1 font-mono text-xs"
                >
                  {sdn.pveum_hint}
                </code>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={copyPveumHint}
                  data-testid="step0-copy-hint"
                >
                  <Copy className="h-3 w-3" />
                  {copiedHint ? "Copied" : "Copy"}
                </Button>
              </div>
            )}
            <p className="mt-2 text-xs text-amber-200/80">
              Run that on your PVE host, then click Retry below.
            </p>
          </div>
        )}

        {expected?.conflicts && expected.conflicts.length > 0 && (
          <div
            role="alert"
            data-testid="step0-conflicts"
            className="rounded-md border border-red-700 bg-red-950/40 px-3 py-2 text-sm text-red-200"
          >
            <div className="mb-1 font-medium">Scenario CIDR conflicts</div>
            <ul className="ml-4 list-disc">
              {expected.conflicts.map((c, i) => (
                <li key={i} className="font-mono text-xs">{c}</li>
              ))}
            </ul>
            <p className="mt-1 text-xs text-red-200/80">
              Resolve these in your scenarios before retrying.
            </p>
          </div>
        )}

        {error && (
          <div
            role="alert"
            data-testid="step0-error"
            className="rounded-md border border-red-700 bg-red-950/40 px-3 py-2 text-sm text-red-200"
          >
            {error}
          </div>
        )}

        {result && (
          <div
            data-testid="step0-result"
            className={`rounded-md border px-3 py-2 text-sm ${
              result.ok
                ? "border-emerald-700 bg-emerald-950/40 text-emerald-200"
                : "border-amber-700 bg-amber-950/40 text-amber-100"
            }`}
          >
            <div className="mb-1 font-medium">{result.message}</div>
            {result.added.length > 0 && (
              <div className="text-xs">
                Created:{" "}
                <code className="font-mono">{result.added.join(", ")}</code>
              </div>
            )}
            {result.already_present.length > 0 && (
              <div className="text-xs">
                Already present:{" "}
                <code className="font-mono">
                  {result.already_present.join(", ")}
                </code>
              </div>
            )}
          </div>
        )}

        <div className="flex gap-2 pt-1">
          <Button
            type="button"
            onClick={onApply}
            disabled={
              submitting ||
              (expected?.conflicts?.length ?? 0) > 0 ||
              allDone
            }
            className="flex-1"
            data-testid="step0-submit"
          >
            {submitting ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Network className="mr-2 h-4 w-4" />
            )}
            {submitting ? "Setting up…" : "Set up PVE bridges"}
          </Button>
          <Button
            type="button"
            variant="outline"
            onClick={onRefresh}
            disabled={submitting}
            data-testid="step0-refresh"
            aria-label="Re-probe PVE"
          >
            Retry
          </Button>
          <Button
            type="button"
            variant="ghost"
            onClick={onSkip}
            disabled={submitting}
            data-testid="step0-skip"
          >
            Skip
          </Button>
        </div>

        {result?.ok && (
          <p className="flex items-center gap-1 text-xs text-muted-foreground">
            <ArrowRight className="h-3 w-3" />
            Continuing to admin setup…
          </p>
        )}
      </CardContent>
    </Card>
  );
}