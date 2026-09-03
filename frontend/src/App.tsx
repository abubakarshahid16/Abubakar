import { useEffect, useState } from "react";

type Health = { ok: boolean; embed_model_present: boolean; answer_model: string };

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/health")
      .then((r) => r.json())
      .then(setHealth)
      .catch((e) => setErr(String(e)));
  }, []);

  return (
    <div className="min-h-full p-8">
      <h1 className="text-2xl font-semibold">Nabaa</h1>
      <p className="text-sm text-slate-400">Private document intelligence</p>

      <div className="mt-6 rounded-lg border border-slate-700 bg-slate-900/50 p-4 text-sm">
        {err && <span className="text-red-400">API disconnected: {err}</span>}
        {!err && !health && <span className="text-slate-400">Checking API…</span>}
        {health && (
          <ul className="space-y-1">
            <li>API: <span className="text-emerald-400">connected</span></li>
            <li>Embedder staged: {health.embed_model_present ? "yes" : "no"}</li>
            <li>Answer model: {health.answer_model}</li>
          </ul>
        )}
      </div>
    </div>
  );
}
