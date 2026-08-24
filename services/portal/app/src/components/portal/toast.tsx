/**
 * Toast — minimal non-blocking notification system.
 *
 * No external library; just a small queue managed by useToasts().
 * Toasts auto-dismiss after `timeoutMs` (default 4000ms). A
 * single ToastHost renders the queue at the top-right of the
 * viewport.
 *
 * Used by DrillConsole, OperatorConsole, UserListCard, and any
 * future surface that wants to surface "saved", "failed", or
 * "coming soon" messages without modal noise.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { ReactNode } from "react";
import { CheckCircle2, Info, XCircle, X } from "lucide-react";
import { cn } from "@/lib/utils";

export type ToastKind = "info" | "success" | "error";

export interface Toast {
  id: number;
  kind: ToastKind;
  message: string;
  /** ms before auto-dismiss. 0 = sticky. Default 4000. */
  timeoutMs?: number;
}

interface ToastContextValue {
  push: (kind: ToastKind, message: string, timeoutMs?: number) => void;
  info: (message: string, timeoutMs?: number) => void;
  success: (message: string, timeoutMs?: number) => void;
  error: (message: string, timeoutMs?: number) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

export function useToasts(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (ctx === null) {
    // Allow use outside provider — caller probably hasn't mounted
    // ToastHost yet. Provide a no-op fallback so the call site
    // doesn't crash.
    return {
      push: () => {},
      info: () => {},
      success: () => {},
      error: () => {},
    };
  }
  return ctx;
}

const KIND_CLASS: Record<ToastKind, string> = {
  info: "border-sky-700 bg-sky-950/60 text-sky-100",
  success: "border-emerald-700 bg-emerald-950/60 text-emerald-100",
  error: "border-red-700 bg-red-950/60 text-red-100",
};

const KIND_ICON = {
  info: Info,
  success: CheckCircle2,
  error: XCircle,
};

export function ToastHost({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const idRef = useRef(0);
  const timersRef = useRef<Map<number, number>>(new Map());

  const dismiss = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
    const timer = timersRef.current.get(id);
    if (timer !== undefined) {
      window.clearTimeout(timer);
      timersRef.current.delete(id);
    }
  }, []);

  const push = useCallback(
    (kind: ToastKind, message: string, timeoutMs?: number) => {
      idRef.current += 1;
      const id = idRef.current;
      const t: Toast = { id, kind, message, timeoutMs: timeoutMs ?? 4000 };
      setToasts((prev) => [...prev, t]);
      if (t.timeoutMs && t.timeoutMs > 0) {
        const handle = window.setTimeout(() => dismiss(id), t.timeoutMs);
        timersRef.current.set(id, handle);
      }
    },
    [dismiss],
  );

  const value = useMemo<ToastContextValue>(
    () => ({
      push,
      info: (m, t) => push("info", m, t),
      success: (m, t) => push("success", m, t),
      error: (m, t) => push("error", m, t),
    }),
    [push],
  );

  useEffect(() => {
    return () => {
      // Clear all timers on unmount.
      for (const handle of timersRef.current.values()) {
        window.clearTimeout(handle);
      }
      timersRef.current.clear();
    };
  }, []);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div
        aria-live="polite"
        data-testid="toast-host"
        className="pointer-events-none fixed right-4 top-16 z-50 flex w-80 flex-col gap-2"
      >
        {toasts.map((t) => {
          const Icon = KIND_ICON[t.kind];
          return (
            <div
              key={t.id}
              data-testid="toast"
              data-kind={t.kind}
              className={cn(
                "pointer-events-auto flex items-start gap-2 rounded-md border p-3 shadow-md",
                KIND_CLASS[t.kind],
              )}
              role="status"
            >
              <Icon className="mt-0.5 h-4 w-4 flex-shrink-0" aria-hidden="true" />
              <p className="flex-1 text-sm">{t.message}</p>
              <button
                type="button"
                onClick={() => dismiss(t.id)}
                className="text-current/70 hover:text-current"
                aria-label="Dismiss"
              >
                <X className="h-3 w-3" />
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}
