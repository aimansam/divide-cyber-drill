/**
 * TroubleshootPlaybook -- context-aware fix-it card for the Config tab.
 *
 * Given the current PVE / bridges / template status, this component
 * renders the next action an operator should take, with copy-to-clipboard
 * for any required shell command. Designed to keep operators inside the
 * browser: every playbook entry is either a click in the portal (e.g.
 * "Recreate bridges") or a copy-paste for someone with PVE host access.
 *
 * Each playbook entry has:
 *   - `id`: stable identifier (e.g. "sdn-missing", "creds-rejected")
 *   - `severity`: "info" | "warn" | "error" -- colors the card border
 *   - `title`: one-line summary
 *   - `why`: optional expandable explanation
 *   - `steps`: ordered list of fix steps
 *   - `commands`: array of shell commands to copy (each becomes a button)
 *
 * Pattern: callers pass a `probe` object describing the current state;
 * the component picks the best-matching playbook. When the state is
 * healthy, it renders nothing (no false positives).
 */

import { useState } from "react";
import {
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Copy,
  Info,
  Terminal,
  Archive,
} from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";

export interface TroubleshootProbe {
  pveReachable?: boolean;
  pveConfigSource?: "db" | "env" | null;
  sdnError?: string | null;
  sdnRequiredRole?: string | null;
  sdnPveumHint?: string | null;
  bridgesMissing?: string[];
  bridgesPresent?: string[];
  /**
    * CIDR / overlap / ordering conflicts in the bridge plan.
    * Surfaced here so the playbook entry can list them and offer a
    * one-click fix (archive one of the conflicting scenarios).
    */
  bridgeConflicts?: string[];
  /**
    * vmbrN -> scenario mapping from /expected-bridges. Used by the
    * conflict playbook to resolve which scenarios to suggest
    * archiving. Optional: if absent, the entry falls back to a
    * generic "open Admin" hint.
    */
  expectedBridges?: Array<{
    name: string;
    cidr: string;
    scenario: string;
  }>;
  templateReady?: boolean | null;
}

interface PlaybookStep {
  text: string;
  /** Optional shell command to copy. */
  command?: string;
  /**
   * Optional inline button. Used by bridge-conflicts entry to offer
   * "Archive scenario X" without forcing a navigation. The action
   * receives the playbook's onArchiveScenario callback so the parent
   * controls the actual API call + reload.
   */
  button?: {
    label: string;
    /** Stable key so the parent can resolve which scenario to act on. */
    action: "archive-scenario";
    value: string;
  };
}

interface PlaybookEntry {
  id: string;
  severity: "info" | "warn" | "error";
  title: string;
  why?: string;
  steps: PlaybookStep[];
}

interface TroubleshootPlaybookProps {
  probe: TroubleshootProbe;
  /**
   * Optional: invoked when a step's `button.action` is "archive-scenario"
   * and the operator clicks it. The parent owns the API call and any
   * subsequent refresh; the playbook is purely presentational.
   */
  onArchiveScenario?: (name: string) => void;
}

function pickPlaybooks(probe: TroubleshootProbe): PlaybookEntry[] {
  const out: PlaybookEntry[] = [];

  // 1. PVE unreachable -- highest priority, blocks everything else.
  if (probe.pveReachable === false) {
    out.push({
      id: "pve-unreachable",
      severity: "error",
      title: "PVE is not reachable",
      why:
        "The API cannot talk to your Proxmox VE host. Every drill-start " +
        "fails until this is fixed.",
      steps: [
        {
          text:
            "Open the Config tab and click Edit credentials -- verify " +
            "the host URL, user, and token are correct.",
        },
        {
          text:
            "If PVE is on a private LAN, confirm the API container can " +
            "reach it. From the host:",
          command:
            "docker exec divide-api curl -ksSf ${PVE_HOST}/api2/json/version",
        },
      ],
    });
    return out;
  }

  // 2. SDN.Allocate role missing -- the Q7 hot path.
  if (probe.sdnRequiredRole) {
    const steps: PlaybookStep[] = probe.sdnPveumHint
      ? [{ text: "Run on the PVE host:", command: probe.sdnPveumHint }]
      : [
          {
            text:
              "Run on the PVE host (replace user/token-id with your own):",
            command:
              "pveum aclmod divide@pve@pam -role SDN.Allocate -path /sdn",
          },
        ];
    const why =
      probe.sdnError ??
      "Your PVE token cannot create bridges or VNets. The drill runner " +
        "needs this role to provision the cyber-range network.";
    out.push({
      id: "sdn-role-missing",
      severity: "error",
      title: `Missing role: ${probe.sdnRequiredRole}`,
      why,
      steps,
    });
  } else if (probe.sdnError && probe.sdnPveumHint) {
    out.push({
      id: "sdn-generic",
      severity: "warn",
      title: "SDN probe reported an error",
      why: probe.sdnError,
      steps: [
        {
          text: "Try running this on the PVE host:",
          command: probe.sdnPveumHint,
        },
      ],
    });
  }

  // 3. Bridges missing -- recoverable with the in-portal Recreate button.
  if (probe.bridgesMissing && probe.bridgesMissing.length > 0) {
    const firstMissing = probe.bridgesMissing[0];
    out.push({
      id: "bridges-missing",
      severity: "warn",
      title: `${probe.bridgesMissing.length} bridge${
        probe.bridgesMissing.length === 1 ? "" : "s"
      } missing on PVE`,
      why:
        "Drills cannot be started until every expected bridge is present " +
        "on the PVE node. Use the Config tab's Recreate button first.",
      steps: [
        { text: "Click the Recreate button in the Bridges section above." },
        {
          text:
            "If Recreate fails with a permission error, the token needs " +
            "the SDN.Allocate role. You can also do it manually:",
          command: `pvesh create /cluster/sdn/vnets -vnet ${firstMissing} -zone divide`,
        },
      ],
    });
  }

  // 3b. Bridge plan has CIDR conflicts -- a *data* problem, not a
  // permission problem. Two scenarios both claiming 10.10.10.0/24
  // means the bridge plan can't be applied. Resolution: archive one
  // of the conflicting scenarios (the playbook offers a button).
  if (probe.bridgeConflicts && probe.bridgeConflicts.length > 0) {
    // Resolve vmbrN -> scenario names by parsing the conflict string
    // and looking each vmbr up in the expected-bridges plan.
    // Conflict format: "CIDR overlap: vmbr103=10.10.10.0/24 overlaps vmbr107=..."
    const vmbrToScenario = new Map<string, string>();
    if (probe.expectedBridges) {
      for (const eb of probe.expectedBridges) {
        vmbrToScenario.set(eb.name, eb.scenario);
      }
    }
    const parseVmbrs = (s: string): string[] => {
      const matches = s.match(/vmbr\d+/g);
      return matches ?? [];
    };
    const conflictScenarios = new Set<string>();
    for (const c of probe.bridgeConflicts) {
      for (const v of parseVmbrs(c)) {
        const sc = vmbrToScenario.get(v);
        if (sc) conflictScenarios.add(sc);
      }
    }
    const archiveSteps = Array.from(conflictScenarios).map((sc) => ({
      text: `Archive '${sc}' to remove it from the bridge plan (reversible via Admin → Scenarios → Restore).`,
      button: {
        label: `Archive '${sc}'`,
        action: "archive-scenario" as const,
        value: sc,
      },
    }));
    if (archiveSteps.length === 0) {
      // Couldn't resolve scenarios -- fall back to a generic hint.
      archiveSteps.push({
        text:
          "Open Admin → Scenarios and archive whichever scenario you don't need right now.",
        button: {
          label: "Open Admin (scenarios)",
          action: "archive-scenario" as const,
          value: "__open_admin__",
        },
      });
    }
    out.push({
      id: "bridge-conflicts",
      severity: "error",
      title: `Bridge plan has ${probe.bridgeConflicts.length} conflict${
        probe.bridgeConflicts.length === 1 ? "" : "s"
      }`,
      why:
        "Two or more active scenarios declare the same subnet for " +
        "different roles. The API refuses to apply the plan until " +
        "one of them is archived. Recreate bridges will return 409 " +
        "until this is fixed.",
      steps: [
        {
          text:
            "These conflicts are listed in the Bridges card below -- " +
            "each row shows the vmbrN values that overlap.",
        },
        ...archiveSteps,
      ],
    });
  }

  // 4. Template not ready -- only flag if PVE is otherwise healthy.
  if (
    probe.templateReady === false &&
    probe.pveReachable === true &&
    (probe.bridgesMissing?.length ?? 0) === 0
  ) {
    out.push({
      id: "template-not-ready",
      severity: "warn",
      title: "Drill template not built",
      why:
        "Every drill clones from tpl-debian-cloudinit. Until it exists, " +
        "drills cannot start.",
      steps: [
        {
          text:
            "Re-run the wizard's first-run flow to build the template. " +
            "The Quick links section below points to the wizard path.",
        },
      ],
    });
  }

  return out;
}

export function TroubleshootPlaybook({
  probe,
  onArchiveScenario,
}: TroubleshootPlaybookProps) {
  const entries = pickPlaybooks(probe);
  const [expandedWhy, setExpandedWhy] = useState<Set<string>>(new Set());
  const [copied, setCopied] = useState<string | null>(null);

  if (entries.length === 0) return null;

  async function copyCommand(cmd: string, key: string) {
    try {
      await navigator.clipboard.writeText(cmd);
      setCopied(key);
      setTimeout(() => setCopied((c) => (c === key ? null : c)), 1500);
    } catch {
      /* clipboard denied; harmless */
    }
  }

  return (
    <Card className="border-amber-500/50 bg-amber-500/5">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <AlertCircle className="h-5 w-5 text-amber-500" />
          Troubleshoot
          <span className="ml-2 rounded-full bg-amber-500/20 px-2 py-0.5 text-xs text-amber-700 dark:text-amber-300">
            {entries.length} {entries.length === 1 ? "issue" : "issues"}
          </span>
        </CardTitle>
        <CardDescription>
          Context-aware fixes for what's blocking your drills right now.
          Click any command to copy it for your PVE host admin.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {entries.map((entry) => {
          const whyOpen = expandedWhy.has(entry.id);
          const Icon =
            entry.severity === "error"
              ? AlertCircle
              : entry.severity === "warn"
                ? AlertTriangle
                : Info;
          const colour =
            entry.severity === "error"
              ? "border-destructive/50 bg-destructive/5"
              : entry.severity === "warn"
                ? "border-amber-500/50 bg-amber-500/5"
                : "border-sky-500/50 bg-sky-500/5";
          return (
            <div key={entry.id} className={`rounded-md border p-3 text-sm ${colour}`}>
              <div className="flex items-start gap-2">
                <Icon className="mt-0.5 h-4 w-4 shrink-0" />
                <div className="flex-1">
                  <div className="font-medium">{entry.title}</div>
                  {entry.why && (
                    <button
                      type="button"
                      className="mt-1 flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
                      onClick={() => {
                        setExpandedWhy((prev) => {
                          const next = new Set(prev);
                          if (next.has(entry.id)) next.delete(entry.id);
                          else next.add(entry.id);
                          return next;
                        });
                      }}
                    >
                      {whyOpen ? (
                        <ChevronDown className="h-3 w-3" />
                      ) : (
                        <ChevronRight className="h-3 w-3" />
                      )}
                      why?
                    </button>
                  )}
                  {whyOpen && entry.why && (
                    <p className="mt-1 text-xs text-muted-foreground">{entry.why}</p>
                  )}
                  <ol className="mt-2 ml-4 list-decimal space-y-2 text-xs">
                    {entry.steps.map((step, i) => (
                      <li key={i}>
                        <div>{step.text}</div>
                        {step.command && (
                          <div className="mt-1 flex items-center gap-2">
                            <code className="block flex-1 rounded border border-border bg-background px-2 py-1 font-mono text-[11px]">
                              <Terminal className="mr-1 inline h-3 w-3" />
                              {step.command}
                            </code>
                            <Button
                              size="sm"
                              variant="outline"
                              className="h-7 px-2"
                              onClick={() =>
                                void copyCommand(step.command ?? "", `${entry.id}-${i}`)
                              }
                            >
                              {copied === `${entry.id}-${i}` ? (
                                <>
                                  <CheckCircle2 className="h-3 w-3" />
                                  <span className="ml-1">Copied</span>
                                </>
                              ) : (
                                <>
                                  <Copy className="h-3 w-3" />
                                  <span className="ml-1">Copy</span>
                                </>
                              )}
                            </Button>
                          </div>
                        )}
                        {step.button && (
                          <div className="mt-1">
                            <Button
                              size="sm"
                              variant="outline"
                              className="h-7"
                              disabled={
                                !onArchiveScenario ||
                                (step.button.action === "archive-scenario" &&
                                  step.button.value === "__open_admin__" &&
                                  !onArchiveScenario)
                              }
                              onClick={() => {
                                if (!onArchiveScenario) return;
                                if (
                                  step.button?.action === "archive-scenario"
                                ) {
                                  onArchiveScenario(step.button.value);
                                }
                              }}
                            >
                              <Archive className="h-3 w-3" />
                              <span className="ml-1">{step.button.label}</span>
                            </Button>
                          </div>
                        )}
                      </li>
                    ))}
                  </ol>
                </div>
              </div>
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}