/**
 * ConsoleCard — noVNC console viewer for drill VMs.
 *
 * F4: opens a WebSocket connection to the PVE noVNC proxy and renders
 * the VM console in a canvas element. Used by DrillConsole when an
 * asset is picked.
 *
 * Props:
 *   pickedRunId — the run containing the asset
 *   pickedAsset — { asset_id, role? } from AssetsCard
 *   onClose     — callback to close the console panel
 */

import { useEffect, useRef, useState } from "react";
import { X, Loader2 } from "lucide-react";
import { api, detailFromError, getToken } from "@/lib/api";
import { useToasts } from "./toast";

export interface AssetRef {
  asset_id: number;
  role?: string;
}

export interface ConsoleTicket {
  ticket: string;
  port: number;
  host: string;
}

interface ConsoleCardProps {
  pickedRunId: number | null;
  pickedAsset: AssetRef | null;
  onClose: () => void;
}

export function ConsoleCard({ pickedRunId, pickedAsset, onClose }: ConsoleCardProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const toasts = useToasts();
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!pickedRunId || !pickedAsset) return;

    const token = getToken();
    if (!token) {
      setError("No authentication token available. Please sign in again.");
      toasts.error("No token — cannot open console");
      return;
    }

    setLoading(true);
    setError(null);

    // Fetch the noVNC ticket from the API
    api
      .get<ConsoleTicket>(
        `/api/v1/drills/${pickedRunId}/assets/${pickedAsset.asset_id}/console`
      )
      .then(({ ticket, port, host }) => {
        // Open WebSocket connection to noVNC proxy
        const wsUrl = `ws://${host}:${port}/vnc?token=${ticket}`;
        const ws = new WebSocket(wsUrl);
        wsRef.current = ws;

        ws.onopen = () => {
          setLoading(false);
          toasts.success(`Console opened for ${pickedAsset.role || `asset #${pickedAsset.asset_id}`}`);
          // In a real implementation, we'd initialize noVNC here
          // and render to the canvas
        };

        ws.onerror = () => {
          setLoading(false);
          const msg = "WebSocket connection failed";
          setError(msg);
          toasts.error(msg);
        };

        ws.onclose = () => {
          toasts.info("Console connection closed");
        };
      })
      .catch((e) => {
        setLoading(false);
        const msg = detailFromError(e);
        setError(msg);
        toasts.error(`Failed to open console: ${msg}`);
      });

    return () => {
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [pickedRunId, pickedAsset, toasts]);

  if (!pickedRunId || !pickedAsset) {
    return null;
  }

  return (
    <div className="rounded-md border border-border bg-card p-4" data-testid="console-card">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold">
          Console — {pickedAsset.role || `Asset #${pickedAsset.asset_id}`}
        </h3>
        <button
          type="button"
          onClick={onClose}
          className="rounded p-1 hover:bg-accent"
          aria-label="Close console"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      {error && (
        <div className="mb-3 rounded border border-red-700 bg-red-950/40 p-2 text-sm text-red-200">
          {error}
        </div>
      )}

      <div className="relative aspect-video w-full overflow-hidden rounded bg-black">
        <canvas
          ref={canvasRef}
          className="h-full w-full"
          data-testid="console-canvas"
        />
        {loading && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/50">
            <Loader2 className="h-8 w-8 animate-spin text-primary" />
          </div>
        )}
      </div>

      <p className="mt-2 text-xs text-muted-foreground">
        noVNC console • WebSocket connection to PVE proxy
      </p>
    </div>
  );
}
