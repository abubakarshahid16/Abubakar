import { useState } from "react";
import type { ViewId } from "../components/Shell";

type Step = { id: string; title: string; description: string; view: ViewId };

const STEPS: Step[] = [
  { id: "select", title: "Select submittal", description: "Choose the submitted document and confirm its review scope.", view: "documents" },
  { id: "review", title: "Run engineering review", description: "Inspect cited findings, severity, owners, and required actions.", view: "analysis" },
  { id: "freeze", title: "Freeze report", description: "Open the generated evidence report and verify its citations.", view: "reports" },
];

export function SubmittalReviewView({ onNavigate }: { onNavigate: (view: ViewId) => void }) {
  const [step, setStep] = useState(0);
  const current = STEPS[step];
  return (
    <main className="mx-auto w-full max-w-5xl space-y-6" aria-labelledby="review-flow-title">
      <header>
        <p className="text-sm font-semibold uppercase tracking-[0.16em] text-signal-400">EPC review workflow</p>
        <h1 id="review-flow-title" className="mt-2 text-3xl font-semibold text-slateish-100">Guided submittal review</h1>
        <p className="mt-2 max-w-2xl text-slateish-300">Move from the submitted document to a frozen, evidence-backed report in three revisitable steps.</p>
      </header>
      <ol className="grid gap-3 md:grid-cols-3" aria-label="Review progress">
        {STEPS.map((item, index) => (
          <li key={item.id}>
            <button type="button" onClick={() => setStep(index)} aria-current={index === step ? "step" : undefined}
              className={`w-full rounded-[var(--radius-md)] border p-4 text-left ${index === step ? "border-signal-500 bg-signal-500/10" : index < step ? "border-signal-500/40 bg-ink-850" : "border-ink-700 bg-ink-850"}`}>
              <span className="text-xs font-semibold uppercase tracking-wide text-slateish-400">Step {index + 1}</span>
              <span className="mt-1 block font-semibold text-slateish-100">{item.title}</span>
              <span className="mt-1 block text-sm text-slateish-300">{item.description}</span>
            </button>
          </li>
        ))}
      </ol>
      <section className="rounded-[var(--radius-md)] border border-ink-700 bg-ink-850 p-6" aria-live="polite">
        <h2 className="text-xl font-semibold text-slateish-100">{current.title}</h2>
        <p className="mt-2 text-slateish-300">{current.description}</p>
        <div className="mt-6 flex flex-wrap gap-3">
          <button type="button" onClick={() => onNavigate(current.view)} className="rounded-[var(--radius-sm)] bg-signal-500 px-4 py-2 font-semibold text-ink-950">Open {current.view === "documents" ? "documents" : current.view === "analysis" ? "analysis" : "reports"}</button>
          {step < STEPS.length - 1 && <button type="button" onClick={() => setStep((value) => value + 1)} className="rounded-[var(--radius-sm)] border border-ink-600 px-4 py-2 text-slateish-200">Mark step complete</button>}
        </div>
      </section>
    </main>
  );
}
