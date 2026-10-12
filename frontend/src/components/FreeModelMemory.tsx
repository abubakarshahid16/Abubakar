import { useState } from "react";

import { api } from "../api/client";
import type { ModelsFreed } from "../types/api";

/** The administrator's "Free model memory" button (#666).
 *
 *  Ollama keeps a model in RAM after the last call; this asks it to let go now.
 *  What it says afterwards is what Ollama reports, not what was asked: models
 *  still resident are named. The label states the cost, so the button is not
 *  pressed to "speed things up": the next question reloads the model. */
export function FreeModelMemory() {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ModelsFreed | null>(null);
  const [failed, setFailed] = useState<string | null>(null);

  async function free() {
    setBusy(true);
    setFailed(null);
    setResult(null);
    const r = await api.freeModelMemory();
    setBusy(false);
    if (r.ok) setResult(r.data);
    else setFailed(r.disconnected ? "The backend is not reachable." : r.error.message);
  }

  return (
    <div className="mt-3" data-testid="free-model-memory">
      <button
        type="button"
        onClick={() => void free()}
        disabled={busy}
        className="rounded-[var(--radius-sm)] border border-ink-600 bg-ink-800 px-3 py-1.5 text-sm text-slateish-200 hover:bg-ink-700 disabled:opacity-60"
      >
        {busy ? "Freeing..." : "Free model memory"}
      </button>
      <span className="ms-3 text-xs text-slateish-500">
        Unloads the local models from RAM. The next question loads the model again, which takes longer.
      </span>
      {failed && (
        <p role="alert" className="mt-2 text-sm text-danger-500">{failed}</p>
      )}
      {result && (
        <p role="status" className="mt-2 text-sm text-slateish-300">
          {!result.reachable
            ? "Ollama could not be reached, so nothing was asked."
            : result.freed.length === 0 && result.still_loaded.length === 0
              ? "No model was loaded."
              : [
                  result.freed.length > 0 ? `Freed: ${result.freed.join(", ")}.` : null,
                  result.still_loaded.length > 0
                    ? `Still loaded: ${result.still_loaded.join(", ")}.`
                    : null,
                ].filter(Boolean).join(" ")}
        </p>
      )}
    </div>
  );
}
