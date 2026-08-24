/**
 * EmptyState — friendly placeholder for empty lists.
 *
 * Cards that have nothing to show (no runs yet, no users yet,
 * no audit events) used to render either nothing or a bare "No
 * items." string. EmptyState gives the operator a real reason to
 * keep reading — what's missing, what to do next.
 *
 * Used by: MyRunsCard, AuditExplorerCard, ScenarioAuthoringCard,
 * UserListCard. Each caller customizes title + description +
 * optional CTA icon. No external state; pure visual.
 */

import type { LucideIcon } from "lucide-react";
import { Inbox } from "lucide-react";
import { Button } from "@/components/ui/button";

export function EmptyState({
  title,
  description,
  icon,
  cta,
  onCta,
}: {
  title: string;
  description?: string;
  icon?: LucideIcon;
  cta?: string;
  onCta?: () => void;
}) {
  const Icon = icon ?? Inbox;
  return (
    <div
      data-testid="empty-state"
      className="flex flex-col items-center justify-center gap-2 rounded-md border border-dashed border-border bg-card/40 px-6 py-10 text-center"
    >
      <Icon className="h-8 w-8 text-muted-foreground/60" aria-hidden="true" />
      <h3 className="text-sm font-semibold text-foreground">{title}</h3>
      {description ? (
        <p className="max-w-md text-xs text-muted-foreground">{description}</p>
      ) : null}
      {cta && onCta ? (
        <Button
          variant="outline"
          size="sm"
          onClick={onCta}
          className="mt-2"
        >
          {cta}
        </Button>
      ) : null}
    </div>
  );
}
