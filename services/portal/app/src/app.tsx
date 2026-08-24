import { useState } from "react";
import { ScenariosCard, type Scenario } from "@/components/portal/scenarios-card";
import { TokenBar } from "@/components/portal/token-bar";

/**
 * Top-level portal layout. Cards own their own fetch lifecycle
 * (React useEffect + cleanup); state that crosses cards (e.g.
 * "which scenario is loaded for the run panel") lives here.
 */
export default function App() {
  const [picked, setPicked] = useState<Scenario | null>(null);

  return (
    <div className="min-h-screen bg-background">
      <TokenBar />
      <main className="container mx-auto max-w-3xl space-y-6 py-8">
        <header>
          <h1 className="text-2xl font-bold tracking-tight text-primary">
            div:ide portal
          </h1>
          <p className="text-sm text-muted-foreground">
            Run a drill, watch it live, download the debrief. Paste a token
            above to identify yourself; everything below works anonymously
            for read-only public endpoints.
          </p>
        </header>

        <ScenariosCard
          pickedId={picked?.id ?? null}
          onPick={(s) => setPicked(s)}
        />

        {picked && (
          <div className="rounded-md border border-dashed border-border p-4 text-sm text-muted-foreground">
            Loaded scenario: <span className="font-mono">{picked.name}</span>{" "}
            (id={picked.id}). Next milestone: a Run-lifecycle card with
            Start / Refresh / Cancel and a live progress bar.
          </div>
        )}
      </main>
    </div>
  );
}
