/**
 * TemplatesCard -- F7 range-template UI.
 *
 * Shows all templates, with a "Clone" button that POSTs to
 * /drills with template_id. This is the operator's "replay
 * this drill" button.
 *
 * Why a custom card vs reusing ScenariosCard?
 *   Templates are different from scenarios:
 *     - A scenario is YAML.
 *     - A template is a captured, immutable snapshot of a run.
 *   The semantics (clone vs spawn) are different enough that
 *   conflating them would be confusing.
 */

import { useEffect, useState } from "react";
import { Copy, FileBox, Loader2, Trash2 } from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { api, ApiError } from "@/lib/api";

interface TemplateSnapshot {
  scenario_id?: number;
  scenario_name?: string;
  scenario_version?: number;
  assets?: Array<{ role: string; kind: string }>;
  flags?: Array<{ id: string; side: string }>;
  [key: string]: unknown;
}

interface Template {
  id: number;
  name: string;
  title: string;
  description: string;
  from_run_id: number | null;
  scenario_id: number;
  created_by: string;
  created_at: string | null;
  snapshot: TemplateSnapshot;
}

export function TemplatesCard({
  canDelete,
  onClone,
}: {
  canDelete: boolean;
  onClone?: (template: Template) => void;
}) {
  const [templates, setTemplates] = useState<Template[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const refresh = () => {
    setLoading(true);
    api
      .get<{ items: Template[]; total: number }>("/api/v1/templates")
      .then((r) => {
        setTemplates(r.items || []);
        setError(null);
      })
      .catch((e: unknown) => {
        const msg =
          e instanceof ApiError
            ? `HTTP ${e.status} ${e.url}`
            : String(e);
        setError(msg);
      })
      .finally(() => setLoading(false));
  };

  useEffect(refresh, []);

  const handleDelete = (id: number) => {
    api
      .delete(`/api/v1/templates/${id}`)
      .then(() => {
        setTemplates((prev) => prev.filter((t) => t.id !== id));
      })
      .catch((e: unknown) => {
        const msg =
          e instanceof ApiError
            ? `HTTP ${e.status} ${e.url}`
            : String(e);
        setError(msg);
      });
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <FileBox className="h-5 w-5 text-primary" />
          Range Templates
        </CardTitle>
        <CardDescription>
          Immutable snapshots of past drills. Use "Clone" to
          replay; admin can delete obsolete templates.
          {loading && (
            <Loader2 className="ml-2 inline h-3 w-3 animate-spin" />
          )}
          {!loading && error && (
            <span className="ml-2 text-destructive">{error}</span>
          )}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {templates.length === 0 && !loading && (
          <div className="text-sm italic text-muted-foreground">
            No templates yet. Save a drill as a template from the
            drill inspector.
          </div>
        )}
        <ul className="space-y-2">
          {templates.map((t) => (
            <li
              key={t.id}
              data-testid={`template-row-${t.name}`}
              className="flex items-start gap-3 rounded border border-border bg-card/40 p-3 text-sm"
            >
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline gap-2">
                  <span className="font-mono font-medium">{t.name}</span>
                  <span className="text-xs text-muted-foreground">
                    v{t.snapshot?.scenario_version ?? "?"} ·{" "}
                    {t.snapshot?.assets?.length ?? 0} assets ·{" "}
                    {t.snapshot?.flags?.length ?? 0} flags
                  </span>
                </div>
                <p className="text-xs text-muted-foreground">
                  {t.title || "(no title)"}
                </p>
                {t.description && (
                  <p className="mt-1 text-xs text-muted-foreground">
                    {t.description}
                  </p>
                )}
                <p className="mt-1 font-mono text-[10px] text-muted-foreground">
                  by {t.created_by} · from_run_id={t.from_run_id ?? "-"}
                </p>
              </div>
              <div className="flex flex-col gap-1">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => onClone?.(t)}
                  data-testid={`template-clone-${t.name}`}
                >
                  <Copy className="mr-1 h-3 w-3" />
                  Clone
                </Button>
                {canDelete && (
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => handleDelete(t.id)}
                    data-testid={`template-delete-${t.name}`}
                  >
                    <Trash2 className="mr-1 h-3 w-3" />
                    Delete
                  </Button>
                )}
              </div>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
