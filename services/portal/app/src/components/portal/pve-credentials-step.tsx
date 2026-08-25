/**
 * PveCredentialsStep -- the very first step of the onboarding wizard
 * (day-1 web setup; F-pve-config-ui).
 *
 * Mounted by OnboardingWizard before Step 0 (PVE bridges). The wizard
 * auto-skips this step when:
 *
 *   1. The API already has a `pve_config` row in DB (operator already
 *      configured PVE via a previous run of this wizard), AND
 *   2. The PVE bridge status is `ready: true`.
 *
 * Why this step exists: before F-pve-config-ui the operator had to
 * edit `deploy/.env` on their laptop with `PROXMOX_*` variables and
 * restart the API container. That's a fatal UX cliff for the
 * "I just want to run a drill in my browser" use case. With this
 * step the operator pastes the PVE host + token once, the API
 * verifies it via `GET /api2/json/version`, and writes the row to
 * DB. The very next PVE call (admin probe, run start, template
 * upload) uses the new credentials. No restart.
 *
 * Pre-reqs documented in docs/PROXMOX-SETUP.md §1-3:
 *   * PVE user `divide@pve@pam` exists with PVEAuditor role
 *   * API token issued for that user (token_id = `divide@pve@pam!drill-token`)
 *   * The operator has the token UUID to hand
 */

import { useEffect, useState } from "react";
import {
  ArrowRight,
  KeyRound,
  Loader2,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  ApiError,
  getPveConfig,
  postPveConfig,
  type PveConfigPublic,
} from "@/lib/api";

interface PveCredentialsStepProps {
  /** Called when the operator clicks "Continue" after a successful save. */
  onContinue: () => void;
  /**
   * Called when the operator chooses to skip this step (escape hatch).
   * Useful in dev when the operator is running with mock adapters
   * and PVE isn't reachable.
   */
  onSkip: () => void;
}

function detailFromError(e: unknown): string {
  if (e instanceof ApiError) {
    // The API puts a useful message in `detail`; it can be a string
    // (validation errors) or a list (Pydantic 422). Normalize to one
    // string for the alert.
    const d = (e.body as { detail?: unknown } | null)?.detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) {
      return d
        .map((item: { msg?: string }) => item.msg ?? JSON.stringify(item))
        .join("; ");
    }
    return `${e.status} ${e.url}`;
  }
  return e instanceof Error ? e.message : "Network error";
}

export function PveCredentialsStep({
  onContinue,
  onSkip,
}: PveCredentialsStepProps) {
  const [checking, setChecking] = useState(true);
  const [existing, setExisting] = useState<PveConfigPublic | null>(null);
  const [host, setHost] = useState("https://");
  const [user, setUser] = useState("divide@pve@pam");
  const [tokenId, setTokenId] = useState("divide@pve@pam!drill-token");
  const [tokenSecret, setTokenSecret] = useState("");
  const [verifySsl, setVerifySsl] = useState(false);
  const [node, setNode] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  // On mount, check whether the API already has a config. Two cases:
  //   cfg.source === "db"  -> operator has already saved a config
  //                          in this session/this deployment. Render
  //                          the "already configured" banner and
  //                          auto-advance past this step on the next
  //                          tick (the parent will short-circuit).
  //   cfg.source === "env" -> nothing in DB; the API is reading from
  //                          PROXMOX_* env vars. Show the empty form
  //                          so the operator can save their preferred
  //                          creds into the DB (Step -1's job).
  // We need admin auth for this endpoint, but Step -1 runs BEFORE
  // Step 1; if we don't have a token yet, the response is 401 and
  // we render an empty form (the operator fills in creds, posts,
  // and progresses normally).
  useEffect(() => {
    let cancelled = false;
    async function probe() {
      setChecking(true);
      setError(null);
      let cfgForAdvance: PveConfigPublic | null = null;
      try {
        const cfg = await getPveConfig();
        if (cancelled) return;
        setExisting(cfg);
        cfgForAdvance = cfg;
        // Pre-fill the form from the existing config so the operator
        // can see what's set. token_secret is always masked; they'll
        // have to re-type it if they want to update.
        if (cfg.host) setHost(cfg.host);
        if (cfg.user) setUser(cfg.user);
        if (cfg.token_id) setTokenId(cfg.token_id);
        if (typeof cfg.node === "string" && cfg.node) setNode(cfg.node);
        if (typeof cfg.verify_ssl === "boolean") setVerifySsl(cfg.verify_ssl);
      } catch (e) {
        // GET /admin/pve-config requires admin auth. If we don't have
        // a token yet (which is the case here -- this step runs before
        // Step 1), the response is 401. That's fine: render an empty
        // form and let the operator fill it in.
        if (cancelled) return;
        setExisting(null);
        // Don't show an error for the expected 401 path; only show
        // errors that suggest a real problem.
        if (!(e instanceof ApiError && e.status === 401)) {
          setError(detailFromError(e));
        }
      } finally {
        if (!cancelled) setChecking(false);
      }
      // Auto-skip only when the API reports source === "db" (a real
      // saved row). The env-var path still gets the form so the
      // operator can promote creds to the DB. We schedule the
      // advance after a brief tick so the operator sees the
      // "already configured" banner (and so React has time to
      // commit the state update).
      if (
        !cancelled &&
        cfgForAdvance &&
        cfgForAdvance.source === "db" &&
        cfgForAdvance.host
      ) {
        setTimeout(() => {
          if (!cancelled) onContinue();
        }, 400);
      }
    }
    probe();
    return () => {
      cancelled = true;
    };
  }, [onContinue]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (submitting) return;
    if (!host.trim() || !user.trim() || !tokenId.trim() || !tokenSecret.trim()) {
      setError(
        "Host, user, token ID, and token secret are all required.",
      );
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await postPveConfig({
        host: host.trim(),
        user: user.trim(),
        token_id: tokenId.trim(),
        token_secret: tokenSecret.trim(),
        verify_ssl: verifySsl,
        node: node.trim() || null,
      });
      setSaved(true);
      // Brief pause so the operator sees the success state, then
      // advance. The wizard handles the actual step transition.
      setTimeout(() => onContinue(), 600);
    } catch (e) {
      setError(detailFromError(e));
      setSubmitting(false);
    }
  }

  return (
    <Card data-testid="pve-credentials-step">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <ShieldCheck className="h-4 w-4" />
          Connect to Proxmox
        </CardTitle>
        <CardDescription>
          Paste the PVE host + API token. The API probes PVE before
          saving -- if anything is off, you'll see the exact error.
          See{" "}
          <a
            className="underline"
            href="/docs/PROXMOX-SETUP.md"
            target="_blank"
            rel="noreferrer"
          >
            docs/PROXMOX-SETUP.md
          </a>{" "}
          if you need to mint a token first.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {checking ? (
          <div
            className="flex items-center gap-2 text-sm text-muted-foreground"
            data-testid="pve-credentials-checking"
          >
            <Loader2 className="h-4 w-4 animate-spin" />
            Checking existing PVE config…
          </div>
        ) : existing?.source === "db" ? (
          <div
            className="space-y-3"
            data-testid="pve-credentials-already-configured"
          >
            <div className="rounded-md border border-green-700 bg-green-950/40 px-3 py-2 text-sm text-green-200">
              <strong>PVE already configured.</strong> Host{" "}
              <code>{existing.host}</code> as{" "}
              <code>{existing.user}</code>{" "}
              {existing.updated_by ? (
                <span className="text-green-300/70">
                  {" "}
                  (last updated by{" "}
                  <code>{existing.updated_by}</code>)
                </span>
              ) : null}
              . You can update the credentials below, or skip to
              Step 1.
            </div>
            <div className="flex justify-end gap-2">
              <Button
                variant="outline"
                onClick={onSkip}
                data-testid="pve-credentials-skip"
              >
                Skip (already set)
              </Button>
              <Button onClick={onContinue} data-testid="pve-credentials-continue">
                Continue <ArrowRight className="ml-2 h-4 w-4" />
              </Button>
            </div>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-3">
            <div>
              <label
                htmlFor="pve-host"
                className="mb-1 block text-sm font-medium"
              >
                PVE host
              </label>
              <Input
                id="pve-host"
                value={host}
                onChange={(e) => setHost(e.target.value)}
                placeholder="https://192.168.0.10"
                disabled={submitting}
                data-testid="pve-host"
              />
            </div>

            <div className="grid gap-3 md:grid-cols-2">
              <div>
                <label
                  htmlFor="pve-user"
                  className="mb-1 block text-sm font-medium"
                >
                  PVE user
                </label>
                <Input
                  id="pve-user"
                  value={user}
                  onChange={(e) => setUser(e.target.value)}
                  placeholder="divide@pve@pam"
                  disabled={submitting}
                  data-testid="pve-user"
                />
              </div>
              <div>
                <label
                  htmlFor="pve-node"
                  className="mb-1 block text-sm font-medium"
                >
                  Node{" "}
                  <span className="text-muted-foreground">
                    (optional)
                  </span>
                </label>
                <Input
                  id="pve-node"
                  value={node}
                  onChange={(e) => setNode(e.target.value)}
                  placeholder="pve"
                  disabled={submitting}
                  data-testid="pve-node"
                />
              </div>
            </div>

            <div>
              <label
                htmlFor="pve-token-id"
                className="mb-1 block text-sm font-medium"
              >
                Token ID
              </label>
              <Input
                id="pve-token-id"
                value={tokenId}
                onChange={(e) => setTokenId(e.target.value)}
                placeholder="divide@pve@pam!drill-token"
                disabled={submitting}
                data-testid="pve-token-id"
              />
              <p className="mt-1 text-xs text-muted-foreground">
                The full <code>{"<user>!<tokenname>"}</code> string,
                exactly as PVE shows it under{" "}
                <em>Datacenter → Permissions → API Tokens</em>.
              </p>
            </div>

            <div>
              <label
                htmlFor="pve-token-secret"
                className="mb-1 block text-sm font-medium"
              >
                Token secret (UUID)
              </label>
              <Input
                id="pve-token-secret"
                type="password"
                autoComplete="off"
                value={tokenSecret}
                onChange={(e) => setTokenSecret(e.target.value)}
                placeholder="a1b2c3d4-…"
                disabled={submitting}
                data-testid="pve-token-secret"
              />
              <p className="mt-1 text-xs text-muted-foreground">
                Shown once when the token is created. We never echo it
                back -- if you lose it, mint a new token.
              </p>
            </div>

            <div className="flex items-center gap-2">
              <input
                id="pve-verify-ssl"
                type="checkbox"
                checked={verifySsl}
                onChange={(e) => setVerifySsl(e.target.checked)}
                disabled={submitting}
                data-testid="pve-verify-ssl"
                className="h-4 w-4"
              />
              <label
                htmlFor="pve-verify-ssl"
                className="text-sm font-medium"
              >
                Verify PVE's TLS certificate
              </label>
              <span className="text-xs text-muted-foreground">
                (off for self-signed)
              </span>
            </div>

            {error && (
              <div
                role="alert"
                data-testid="pve-credentials-error"
                className="rounded-md border border-red-700 bg-red-950/40 px-3 py-2 text-sm text-red-200"
              >
                {error}
              </div>
            )}

            {saved && (
              <div
                role="status"
                data-testid="pve-credentials-saved"
                className="rounded-md border border-green-700 bg-green-950/40 px-3 py-2 text-sm text-green-200"
              >
                PVE accepted the credentials. Continuing…
              </div>
            )}

            <div className="flex gap-2">
              <Button
                type="submit"
                disabled={submitting || saved}
                className="flex-1"
                data-testid="pve-credentials-submit"
              >
                {submitting ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <KeyRound className="mr-2 h-4 w-4" />
                )}
                {submitting
                  ? "Probing PVE…"
                  : saved
                  ? "Saved"
                  : "Save + connect"}
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={onSkip}
                disabled={submitting}
                data-testid="pve-credentials-skip"
              >
                Skip
              </Button>
              <Button
                type="button"
                variant="ghost"
                onClick={() => {
                  setChecking(true);
                  setError(null);
                  // Re-probe by reloading the component state via the
                  // same effect; we just set checking=true and the
                  // effect's onMount already ran. Easiest fix: a tiny
                  // inline re-fetch.
                  void (async () => {
                    try {
                      const cfg = await getPveConfig();
                      setExisting(cfg);
                    } catch {
                      // ignore; preserve current
                    } finally {
                      setChecking(false);
                    }
                  })();
                }}
                disabled={submitting}
                data-testid="pve-credentials-refresh"
                aria-label="Re-check PVE config"
              >
                <RefreshCw className="h-4 w-4" />
              </Button>
            </div>
          </form>
        )}
      </CardContent>
    </Card>
  );
}
