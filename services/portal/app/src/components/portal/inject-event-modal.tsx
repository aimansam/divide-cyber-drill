/**
 * InjectEventModal -- F9.4 manual telemetry event injection.
 *
 * Operator opens this from the OperatorConsole's "Inject"
 * button. Posts ``POST /api/v1/runs/{id}/events`` (the F8
 * ``ingest_event`` endpoint) with a 3-field form:
 *
 *   * kind       -- e.g. "kill-chain.signal", "audit.alert".
 *                   Free-form text; the API doesn't constrain.
 *   * severity   -- info / low / medium / high. Default info.
 *   * payload    -- free-form JSON object. Empty by default.
 *
 * Why a modal (not inline):
 *   The OperatorConsole already shows live runs in a list. An
 *   inline inject form would compete for vertical space with
 *   the run rows. A focused modal keeps the operator's context
 *   ("I want to inject into run #42") while they fill out the
 *   payload.
 *
 * Why no separate "asset_id" field:
 *   The ingest_event endpoint accepts an optional asset_id, but
 *   in practice operators either know the exact id (and can
 *   edit the YAML / curl) or don't care. Forcing them to look
 *   up an asset_id mid-incident slows the flow. We surface a
 *   "raw JSON" mode (the textarea below) for power users who
 *   want to specify asset_id + ts + everything.
 */

import { useEffect, useState } from "react";
import { Loader2, Siren, X } from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api, detailFromError } from "@/lib/api";

interface InjectEventModalProps {
  runId: number;
  onClose: () => void;
  onInjected?: () => void;
}

const SEVERITIES = ["info", "low", "medium", "high"] as const;
type Severity = (typeof SEVERITIES)[number];

export function InjectEventModal({
  runId,
  onClose,
  onInjected,
}: InjectEventModalProps) {
  const [kind, setKind] = useState("kill-chain.signal");
  const [severity, setSeverity] = useState<Severity>("info");
  const [payloadRaw, setPayloadRaw] = useState('{\n  "message": ""\n}');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Close on Escape. Mirrors the toast modal pattern.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape" && !submitting) onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, submitting]);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    // Parse the payload textarea; tolerate empty / invalid by
    // defaulting to {}.
    let payload: Record<string, unknown> = {};
    const trimmed = payloadRaw.trim();
    if (trimmed.length > 0) {
      try {
        const parsed: unknown = JSON.parse(trimmed);
        if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
          setError("payload must be a JSON object (e.g. { ... })");
          return;
        }
        payload = parsed as Record<string, unknown>;
      } catch (err) {
        setError(
          `payload is not valid JSON: ${err instanceof Error ? err.message : String(err)}`,
        );
        return;
      }
    }

    setSubmitting(true);
    try {
      await api.post(`/api/v1/runs/${runId}/events`, {
        kind: kind.trim(),
        severity,
        payload,
      });
      onInjected?.();
      onClose();
    } catch (err) {
      setError(`inject failed: ${detailFromError(err)}`);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div
      data-testid="inject-modal"
      role="dialog"
      aria-modal="true"
      aria-label={`Inject telemetry event into run #${runId}`}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={(e) => {
        // Close when clicking the backdrop (not the card itself).
        if (e.target === e.currentTarget && !submitting) onClose();
      }}
    >
      <Card className="w-full max-w-lg">
        <CardHeader className="flex-row items-start justify-between space-y-0">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <Siren className="h-4 w-4 text-primary" />
              Inject event into run #{runId}
            </CardTitle>
            <CardDescription>
              Manually emit a TelemetryEvent for this run. Useful for
              red/blue team exercises where the runner doesn't emit
              the kill-chain signal you want to see.
            </CardDescription>
          </div>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            onClick={onClose}
            disabled={submitting}
            aria-label="Close"
            data-testid="inject-modal-close"
          >
            <X className="h-4 w-4" />
          </Button>
        </CardHeader>
        <CardContent>
          <form onSubmit={onSubmit} className="space-y-3">
            <div>
              <label
                htmlFor="inject-kind"
                className="block text-sm font-medium"
              >
                Kind
              </label>
              <Input
                id="inject-kind"
                value={kind}
                onChange={(e) => setKind(e.target.value)}
                placeholder="kill-chain.signal"
                data-testid="inject-kind"
              />
            </div>
            <div>
              <label
                htmlFor="inject-severity"
                className="block text-sm font-medium"
              >
                Severity
              </label>
              <select
                id="inject-severity"
                value={severity}
                onChange={(e) => setSeverity(e.target.value as Severity)}
                className="w-full rounded-md border border-border bg-background p-2 text-sm"
                data-testid="inject-severity"
              >
                {SEVERITIES.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label
                htmlFor="inject-payload"
                className="block text-sm font-medium"
              >
                Payload (JSON object)
              </label>
              <textarea
                id="inject-payload"
                value={payloadRaw}
                onChange={(e) => setPayloadRaw(e.target.value)}
                rows={6}
                className="min-h-[8rem] w-full rounded-md border border-border bg-background p-2 font-mono text-xs"
                placeholder='{ "message": "...", "asset_id": 5 }'
                data-testid="inject-payload"
              />
              <p className="mt-1 text-xs text-muted-foreground">
                Empty payload OK. Must be a JSON object (not array, not
                scalar). For asset_id / ts / message, free-form keys.
              </p>
            </div>
            {error && (
              <div
                role="alert"
                className="rounded-md border border-red-700 bg-red-950/40 px-3 py-2 text-sm text-red-200"
              >
                {error}
              </div>
            )}
            <div className="flex justify-end gap-2">
              <Button
                type="button"
                variant="outline"
                onClick={onClose}
                disabled={submitting}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                disabled={submitting || kind.trim().length === 0}
                data-testid="inject-modal-submit"
              >
                {submitting ? (
                  <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                ) : (
                  <Siren className="mr-1 h-3 w-3" />
                )}
                {submitting ? "Injecting…" : "Inject"}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
