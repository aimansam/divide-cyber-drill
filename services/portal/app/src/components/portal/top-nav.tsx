/**
 * TopNav — top-of-page brand bar + role-aware view tabs + sign-out.
 *
 * Replaces the implicit "header text in app.tsx" with a proper
 * navigation surface. The previous layout was a vertical stack of
 * cards with no way to jump between "operate a drill" and "audit
 * the past" without scrolling — a real cyber range has 4-5 distinct
 * tasks the operator switches between.
 *
 * Tabs are role-gated via the same COMPOSITIONS matrix that
 * decides which cards render (see app.tsx + sign-in-card.tsx).
 * For example, blue users don't see the "Admin" tab because they
 * can't manage anything; observer users only see "Dashboard",
 * "History", and "Profile".
 *
 * Hash routing: the active tab is derived from window.location.hash
 * (e.g. "#/operate"). Setting it triggers a hashchange event that
 * the parent listens to. No react-router, no extra deps.
 */

import {
  Activity,
  Clock,
  Compass,
  Gauge,
  History,
  KeyRound,
  LogOut,
  Settings,
  Shield,
  User as UserIcon,
} from "lucide-react";
import { useEffect, useState } from "react";
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

interface TabSpec {
  key: ViewKey;
  label: string;
  icon: typeof Activity;
  /** Roles allowed to see this tab. Empty = everyone. */
  roles: readonly Role[];
}

const TABS: readonly TabSpec[] = [
  {
    key: "dashboard",
    label: "Command Center",
    icon: Gauge,
    roles: [], // all roles
  },
  {
    key: "operate",
    label: "Operate",
    icon: Compass,
    roles: [], // all roles can start runs they own
  },
  {
    key: "observe",
    label: "Observe",
    icon: Activity,
    roles: [], // all roles can observe
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
    roles: [], // all roles can browse history
  },
  {
    key: "profile",
    label: "Profile",
    icon: UserIcon,
    roles: [], // all roles
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
  const visibleTabs = tabsForRole(me?.role ?? null);

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

  return (
    <header
      className="sticky top-0 z-20 border-b border-border bg-background/95 backdrop-blur"
      data-testid="top-nav"
    >
      <div className="container mx-auto flex max-w-6xl items-center gap-4 px-4 py-2">
        <div className="flex items-center gap-2">
          <KeyRound className="h-5 w-5 text-primary" aria-hidden="true" />
          <span className="font-mono text-base font-semibold tracking-tight text-primary">
            div:ide
          </span>
          <span className="text-xs text-muted-foreground">cyber range</span>
        </div>

        <nav
          className="ml-4 flex flex-1 items-center gap-1 overflow-x-auto"
          aria-label="View tabs"
        >
          {visibleTabs.map((tab) => {
            const Icon = tab.icon;
            const active = activeView === tab.key;
            return (
              <button
                key={tab.key}
                type="button"
                data-testid={`top-nav-tab-${tab.key}`}
                data-active={active ? "true" : "false"}
                onClick={() => onChangeView(tab.key)}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm transition transition-colors",
                  active
                    ? "bg-primary/10 text-primary ring-1 ring-primary/30"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground",
                )}
                aria-current={active ? "page" : undefined}
              >
                <Icon className="h-4 w-4" aria-hidden="true" />
                {tab.label}
              </button>
            );
          })}
        </nav>

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
              <span className="rounded bg-secondary/40 px-1.5 py-0.5 text-xs text-secondary-foreground">
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
              className="absolute right-0 top-full mt-2 w-44 rounded-md border border-border bg-card p-1 shadow-md"
            >
              <div className="px-2 py-1 text-xs text-muted-foreground">
                Signed in as{" "}
                <span className="font-mono text-foreground">{me.sub}</span>
              </div>
              {/* F-auth-ux (Plan A3): session-expiry pill so the
                  operator isn't blindsided when the token expires.
                  Amber when <1h, red when <15min. */}
              <SessionExpiryPill ttl={me.ttl_remaining_s} />
              <Button
                variant="ghost"
                size="sm"
                onClick={onSignOut}
                className="w-full justify-start"
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
// Plain when >1h, amber when <1h, red when <15min. Self-ticks every 30s
// so the countdown stays accurate without a full useMe() re-fetch.
// ---------------------------------------------------------------------------

function SessionExpiryPill({ ttl: initialTtl }: { ttl: number }) {
  const [ttl, setTtl] = useState(initialTtl);

  useEffect(() => {
    setTtl(initialTtl);
  }, [initialTtl]);

  // Tick every 30s so the countdown stays roughly accurate.
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
      className={`flex items-center gap-1 px-2 py-1 text-xs ${colorClass}`}
    >
      <Clock className="h-3 w-3 shrink-0" />
      <span>
        {ttl > 0 ? `expires in ${formatTtl(ttl)}` : "session expired"}
      </span>
    </div>
  );
}
