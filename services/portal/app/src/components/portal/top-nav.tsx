/**
 * TopNav — top-of-page brand bar + grouped navigation + session/user menu.
 */

import {
  Activity,
  ChevronDown,
  Clock,
  Compass,
  Gauge,
  History,
  KeyRound,
  LogOut,
  Play,
  Settings,
  Shield,
  User as UserIcon,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { api, setToken } from "@/lib/api";
import { emitTokenChange, formatTtl, useMe } from "@/lib/auth";
import { ROLE_LABELS, type Role } from "@/lib/roles";
import { cn } from "@/lib/utils";

export type ViewKey =
  | "dashboard"
  | "operate"
  | "observe"
  | "admin"
  | "config"
  | "history"
  | "profile";

export interface TabSpec {
  key: ViewKey;
  label: string;
  icon: typeof Activity;
  /** Roles allowed to see this tab. Empty = everyone. */
  roles: readonly Role[];
}

export const TABS: readonly TabSpec[] = [
  {
    key: "dashboard",
    label: "Command Center",
    icon: Gauge,
    roles: [],
  },
  {
    key: "operate",
    label: "Operate",
    icon: Compass,
    roles: [],
  },
  {
    key: "observe",
    label: "Observe",
    icon: Activity,
    roles: [],
  },
  {
    key: "admin",
    label: "Admin",
    icon: Shield,
    roles: ["admin", "lead"] as const,
  },
  {
    key: "config",
    label: "Config",
    icon: Settings,
    roles: ["admin", "lead"] as const,
  },
  {
    key: "history",
    label: "History",
    icon: History,
    roles: [],
  },
  {
    key: "profile",
    label: "Profile",
    icon: UserIcon,
    roles: [],
  },
];

export function tabsForRole(role: Role | null): TabSpec[] {
  return TABS.filter((t) => t.roles.length === 0 || (role && t.roles.includes(role)));
}

export function TopNav({
  activeView,
  onChangeView,
}: {
  activeView: ViewKey;
  onChangeView: (v: ViewKey) => void;
}) {
  const { me, loading } = useMe();
  const [menuOpen, setMenuOpen] = useState(false);
  const [drillsOpen, setDrillsOpen] = useState(false);
  const [mgmtOpen, setMgmtOpen] = useState(false);

  const drillsRef = useRef<HTMLDivElement>(null);
  const mgmtRef = useRef<HTMLDivElement>(null);

  const role = me?.role ?? null;
  const canAdmin = role === "admin" || role === "lead";

  const isDrillActive =
    activeView === "operate" || activeView === "observe" || activeView === "history";
  const isMgmtActive = activeView === "admin" || activeView === "config";

  async function onSignOut() {
    try {
      await api.post("/api/v1/auth/logout");
    } catch {
      /* best-effort */
    }
    setToken("");
    emitTokenChange("");
    setMenuOpen(false);
  }

  // Dismiss dropdowns on outside click
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      const target = e.target as Node;
      if (drillsRef.current && !drillsRef.current.contains(target)) {
        setDrillsOpen(false);
      }
      if (mgmtRef.current && !mgmtRef.current.contains(target)) {
        setMgmtOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  return (
    <header
      className="sticky top-0 z-20 border-b border-border bg-background/95 backdrop-blur"
      data-testid="top-nav"
    >
      <div className="container mx-auto flex max-w-6xl items-center gap-4 px-4 py-2">
        {/* Brand */}
        <div
          className="flex items-center gap-2 cursor-pointer select-none"
          onClick={() => onChangeView("dashboard")}
        >
          <KeyRound className="h-5 w-5 text-primary" aria-hidden="true" />
          <span className="font-mono text-base font-semibold tracking-tight text-primary">
            div:ide
          </span>
          <span className="text-xs text-muted-foreground hidden sm:inline">
            cyber range
          </span>
        </div>

        {/* Grouped / Compacted Navigation */}
        <nav
          className="ml-2 flex flex-1 items-center gap-1.5"
          aria-label="View tabs"
        >
          {/* Direct 1-Click: Command Center */}
          <button
            type="button"
            data-testid="top-nav-tab-dashboard"
            data-active={activeView === "dashboard" ? "true" : "false"}
            onClick={() => {
              onChangeView("dashboard");
              setDrillsOpen(false);
              setMgmtOpen(false);
            }}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs sm:text-sm font-medium transition-colors",
              activeView === "dashboard"
                ? "bg-primary/10 text-primary ring-1 ring-primary/30"
                : "text-muted-foreground hover:bg-muted hover:text-foreground",
            )}
            aria-current={activeView === "dashboard" ? "page" : undefined}
          >
            <Gauge className="h-4 w-4" aria-hidden="true" />
            <span>Command Center</span>
          </button>

          {/* Drills Group Dropdown */}
          <div ref={drillsRef} className="relative">
            <button
              type="button"
              data-testid="top-nav-drills-group"
              onClick={() => {
                setDrillsOpen((o) => !o);
                setMgmtOpen(false);
              }}
              className={cn(
                "inline-flex items-center gap-1 rounded-md px-2.5 py-1.5 text-xs sm:text-sm font-medium transition-colors",
                isDrillActive
                  ? "bg-primary/10 text-primary ring-1 ring-primary/30"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground",
              )}
            >
              <Play className="h-3.5 w-3.5 fill-current opacity-80" aria-hidden="true" />
              <span>Drills</span>
              <ChevronDown
                className={cn(
                  "h-3.5 w-3.5 transition-transform duration-200",
                  drillsOpen && "rotate-180",
                )}
                aria-hidden="true"
              />
            </button>

            {drillsOpen && (
              <div
                className="absolute left-0 top-full mt-1.5 w-48 rounded-lg border border-border bg-card p-1 shadow-lg z-50 animate-in fade-in-50 zoom-in-95"
                role="menu"
              >
                <button
                  type="button"
                  data-testid="top-nav-tab-operate"
                  data-active={activeView === "operate" ? "true" : "false"}
                  onClick={() => {
                    onChangeView("operate");
                    setDrillsOpen(false);
                  }}
                  className={cn(
                    "flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left text-xs sm:text-sm transition-colors",
                    activeView === "operate"
                      ? "bg-primary/15 text-primary font-medium"
                      : "text-foreground hover:bg-muted",
                  )}
                  role="menuitem"
                >
                  <Compass className="h-4 w-4 text-muted-foreground shrink-0" />
                  <span className="flex-1">Operate</span>
                  {activeView === "operate" && (
                    <span className="h-1.5 w-1.5 rounded-full bg-primary" />
                  )}
                </button>

                <button
                  type="button"
                  data-testid="top-nav-tab-observe"
                  data-active={activeView === "observe" ? "true" : "false"}
                  onClick={() => {
                    onChangeView("observe");
                    setDrillsOpen(false);
                  }}
                  className={cn(
                    "flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left text-xs sm:text-sm transition-colors",
                    activeView === "observe"
                      ? "bg-primary/15 text-primary font-medium"
                      : "text-foreground hover:bg-muted",
                  )}
                  role="menuitem"
                >
                  <Activity className="h-4 w-4 text-muted-foreground shrink-0" />
                  <span className="flex-1">Observe</span>
                  {activeView === "observe" && (
                    <span className="h-1.5 w-1.5 rounded-full bg-primary" />
                  )}
                </button>

                <button
                  type="button"
                  data-testid="top-nav-tab-history"
                  data-active={activeView === "history" ? "true" : "false"}
                  onClick={() => {
                    onChangeView("history");
                    setDrillsOpen(false);
                  }}
                  className={cn(
                    "flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left text-xs sm:text-sm transition-colors",
                    activeView === "history"
                      ? "bg-primary/15 text-primary font-medium"
                      : "text-foreground hover:bg-muted",
                  )}
                  role="menuitem"
                >
                  <History className="h-4 w-4 text-muted-foreground shrink-0" />
                  <span className="flex-1">History</span>
                  {activeView === "history" && (
                    <span className="h-1.5 w-1.5 rounded-full bg-primary" />
                  )}
                </button>
              </div>
            )}
          </div>

          {/* Management Group Dropdown (Admin & Lead) */}
          {canAdmin && (
            <div ref={mgmtRef} className="relative">
              <button
                type="button"
                data-testid="top-nav-mgmt-group"
                onClick={() => {
                  setMgmtOpen((o) => !o);
                  setDrillsOpen(false);
                }}
                className={cn(
                  "inline-flex items-center gap-1 rounded-md px-2.5 py-1.5 text-xs sm:text-sm font-medium transition-colors",
                  isMgmtActive
                    ? "bg-primary/10 text-primary ring-1 ring-primary/30"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground",
                )}
              >
                <Shield className="h-3.5 w-3.5 opacity-80" aria-hidden="true" />
                <span>Management</span>
                <ChevronDown
                  className={cn(
                    "h-3.5 w-3.5 transition-transform duration-200",
                    mgmtOpen && "rotate-180",
                  )}
                  aria-hidden="true"
                />
              </button>

              {mgmtOpen && (
                <div
                  className="absolute left-0 top-full mt-1.5 w-48 rounded-lg border border-border bg-card p-1 shadow-lg z-50 animate-in fade-in-50 zoom-in-95"
                  role="menu"
                >
                  <button
                    type="button"
                    data-testid="top-nav-tab-admin"
                    data-active={activeView === "admin" ? "true" : "false"}
                    onClick={() => {
                      onChangeView("admin");
                      setMgmtOpen(false);
                    }}
                    className={cn(
                      "flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left text-xs sm:text-sm transition-colors",
                      activeView === "admin"
                        ? "bg-primary/15 text-primary font-medium"
                        : "text-foreground hover:bg-muted",
                    )}
                    role="menuitem"
                  >
                    <Shield className="h-4 w-4 text-muted-foreground shrink-0" />
                    <span className="flex-1">Admin</span>
                    {activeView === "admin" && (
                      <span className="h-1.5 w-1.5 rounded-full bg-primary" />
                    )}
                  </button>

                  <button
                    type="button"
                    data-testid="top-nav-tab-config"
                    data-active={activeView === "config" ? "true" : "false"}
                    onClick={() => {
                      onChangeView("config");
                      setMgmtOpen(false);
                    }}
                    className={cn(
                      "flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left text-xs sm:text-sm transition-colors",
                      activeView === "config"
                        ? "bg-primary/15 text-primary font-medium"
                        : "text-foreground hover:bg-muted",
                    )}
                    role="menuitem"
                  >
                    <Settings className="h-4 w-4 text-muted-foreground shrink-0" />
                    <span className="flex-1">Config</span>
                    {activeView === "config" && (
                      <span className="h-1.5 w-1.5 rounded-full bg-primary" />
                    )}
                  </button>
                </div>
              )}
            </div>
          )}

          {/* Profile Direct Link */}
          <button
            type="button"
            data-testid="top-nav-tab-profile"
            data-active={activeView === "profile" ? "true" : "false"}
            onClick={() => {
              onChangeView("profile");
              setDrillsOpen(false);
              setMgmtOpen(false);
            }}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs sm:text-sm font-medium transition-colors",
              activeView === "profile"
                ? "bg-primary/10 text-primary ring-1 ring-primary/30"
                : "text-muted-foreground hover:bg-muted hover:text-foreground",
            )}
            aria-current={activeView === "profile" ? "page" : undefined}
          >
            <UserIcon className="h-4 w-4" aria-hidden="true" />
            <span>Profile</span>
          </button>
        </nav>

        {/* Right side: Session countdown + User Menu */}
        <div className="relative ml-auto flex items-center gap-3">
          {loading && !me && (
            <span className="text-xs italic text-muted-foreground">
              checking…
            </span>
          )}
          {!loading && me && (
            <button
              type="button"
              onClick={() => setMenuOpen((o) => !o)}
              data-testid="user-menu-button"
              className="inline-flex items-center gap-2 rounded-md px-2 py-1 text-sm hover:bg-muted"
            >
              <span className="font-semibold">{me.sub}</span>
              <span className="rounded bg-secondary/40 px-1.5 py-0.5 text-xs text-secondary-foreground font-mono">
                {ROLE_LABELS[me.role]}
              </span>
              <Settings className="h-3.5 w-3.5 text-muted-foreground" />
            </button>
          )}
          {!loading && !me && (
            <span className="text-xs italic text-muted-foreground">
              anonymous
            </span>
          )}
          {menuOpen && me && (
            <div
              data-testid="user-menu"
              className="absolute right-0 top-full mt-2 w-48 rounded-md border border-border bg-card p-1 shadow-md z-50"
            >
              <div className="px-2 py-1 text-xs text-muted-foreground border-b border-border/60 mb-1">
                Signed in as{" "}
                <span className="font-mono text-foreground font-medium">{me.sub}</span>
              </div>
              <SessionExpiryPill ttl={me.ttl_remaining_s} />
              <Button
                variant="ghost"
                size="sm"
                onClick={onSignOut}
                className="w-full justify-start text-destructive hover:text-destructive hover:bg-destructive/10"
                data-testid="sign-out-button"
              >
                <LogOut className="mr-1 h-3 w-3" />
                Sign out
              </Button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}

// ---------------------------------------------------------------------------
// SessionExpiryPill — shows "expires in 4h 12m" under the user menu.
// Plain when >1h, amber when <1h, red when <15min. Self-ticks every 30s.
// ---------------------------------------------------------------------------

function SessionExpiryPill({ ttl: initialTtl }: { ttl: number }) {
  const [ttl, setTtl] = useState(initialTtl);

  useEffect(() => {
    setTtl(initialTtl);
  }, [initialTtl]);

  useEffect(() => {
    const h = window.setInterval(() => {
      setTtl((t) => Math.max(0, t - 30));
    }, 30_000);
    return () => window.clearInterval(h);
  }, []);

  let colorClass = "text-muted-foreground";
  if (ttl > 0 && ttl < 900) colorClass = "text-red-400";
  else if (ttl > 0 && ttl < 3600) colorClass = "text-amber-400";

  return (
    <div
      data-testid="session-expiry-pill"
      className={`flex items-center gap-1 px-2 py-1 text-xs font-mono ${colorClass}`}
    >
      <Clock className="h-3 w-3 shrink-0" />
      <span>
        {ttl > 0 ? `expires in ${formatTtl(ttl)}` : "session expired"}
      </span>
    </div>
  );
}
