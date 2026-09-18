/**
 * Drag-and-drop multi-file upload with per-file progress.
 *
 * XMLHttpRequest rather than fetch, because fetch cannot report upload
 * progress and a 100 MB specification uploading with no feedback looks
 * identical to a hung application.
 *
 * That makes this the one transport `api.request()` does not own, so the
 * bearer header has to be attached here explicitly - see `api.authorize`.
 * Without it every upload is a 401 under AUTH_MODE=demo_required, and the
 * screen reports "Cannot reach the backend" for a server that answered.
 */
import { useCallback, useRef, useState } from "react";

import { authorize } from "../api/client";

export type UploadState =
  | { phase: "uploading"; percent: number }
  | {
      phase: "done";
      documentId: string;
      duplicateOf: string | null;
      awaitingGrant: boolean;
    }
  | { phase: "error"; code: string; message: string };

export interface UploadItem {
  id: string;
  name: string;
  size: number;
  state: UploadState;
}

function uploadOne(
  file: File,
  onProgress: (percent: number) => void,
): Promise<UploadState> {
  return new Promise((resolve) => {
    const form = new FormData();
    form.append("file", file);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/documents");
    // After open(), before send(): setRequestHeader throws outside that window.
    // The token goes in the header and nowhere else - never on the URL, which
    // is logged by every proxy and kept in browser history.
    authorize((name, value) => xhr.setRequestHeader(name, value));

    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100));
    };
    xhr.onerror = () =>
      resolve({
        phase: "error",
        code: "internal",
        message: "Cannot reach the backend.",
      });
    xhr.onload = () => {
      let body: Record<string, unknown> = {};
      try {
        body = JSON.parse(xhr.responseText) as Record<string, unknown>;
      } catch {
        /* fall through to the generic error below */
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        const doc = body.document as { id: string } | undefined;
        resolve({
          phase: "done",
          documentId: doc?.id ?? "",
          duplicateOf: (body.duplicate_of as string | null) ?? null,
          awaitingGrant: body.awaiting_grant === true,
        });
      } else {
        const detail = (body.detail ?? body) as { code?: string; message?: string };
        resolve({
          phase: "error",
          code: detail?.code ?? "internal",
          message: detail?.message ?? `Upload failed (HTTP ${xhr.status}).`,
        });
      }
    };
    xhr.send(form);
  });
}

export function Uploader({ onUploaded }: { onUploaded: () => void }) {
  const [items, setItems] = useState<UploadItem[]>([]);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const start = useCallback(
    async (files: FileList | File[]) => {
      const list = Array.from(files);
      if (list.length === 0) return;

      const queued: UploadItem[] = list.map((f, i) => ({
        id: `${Date.now()}-${i}-${f.name}`,
        name: f.name,
        size: f.size,
        state: { phase: "uploading", percent: 0 },
      }));
      setItems((prev) => [...queued, ...prev]);

      for (let i = 0; i < list.length; i += 1) {
        const item = queued[i];
        const state = await uploadOne(list[i], (percent) =>
          setItems((prev) =>
            prev.map((it) =>
              it.id === item.id ? { ...it, state: { phase: "uploading", percent } } : it,
            ),
          ),
        );
        setItems((prev) => prev.map((it) => (it.id === item.id ? { ...it, state } : it)));
        onUploaded();
      }
    },
    [onUploaded],
  );

  return (
    <section aria-labelledby="upload-heading">
      <h2 id="upload-heading" className="sr-only">
        Upload documents
      </h2>

      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          void start(e.dataTransfer.files);
        }}
        className={[
          "rounded-lg border-2 border-dashed p-6 text-center motion-safe:transition-colors",
          dragging ? "border-signal-500 bg-signal-500/10" : "border-ink-600 bg-ink-850/50",
        ].join(" ")}
      >
        <p className="text-sm text-slateish-300">
          Drag PDFs here, or{" "}
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            className="underline decoration-dotted underline-offset-4 hover:text-slateish-200"
          >
            choose files
          </button>
        </p>
        <p className="mt-1 text-xs text-slateish-400">
          Files stay on this machine. Multiple files are uploaded one after another.
        </p>
        <input
          ref={inputRef}
          type="file"
          accept="application/pdf,.pdf"
          multiple
          aria-label="Choose PDF files to upload"
          className="sr-only"
          onChange={(e) => {
            if (e.target.files) void start(e.target.files);
            e.target.value = "";
          }}
        />
      </div>

      {items.length > 0 && (
        <ul className="mt-3 space-y-2">
          {items.map((item) => (
            <li
              key={item.id}
              className="rounded border border-ink-700 bg-ink-850 px-3 py-2 text-sm"
            >
              <div className="flex items-center justify-between gap-3">
                <span className="truncate text-slateish-300">{item.name}</span>
                <span className="shrink-0 text-xs">
                  {item.state.phase === "uploading" && (
                    <span className="text-slateish-400">{item.state.percent}%</span>
                  )}
                  {item.state.phase === "done" && item.state.awaitingGrant && (
                    <span className="text-warn-500">awaiting administrator review</span>
                  )}
                  {item.state.phase === "done" && !item.state.awaitingGrant && item.state.duplicateOf && (
                    <span className="text-warn-500">already uploaded</span>
                  )}
                  {item.state.phase === "done" && !item.state.awaitingGrant && !item.state.duplicateOf && (
                    <span className="text-signal-400">queued for processing</span>
                  )}
                  {item.state.phase === "error" && (
                    <span className="text-danger-500">{item.state.code}</span>
                  )}
                </span>
              </div>

              {item.state.phase === "uploading" && (
                <div
                  className="mt-2 h-1 w-full overflow-hidden rounded bg-ink-700"
                  role="progressbar"
                  aria-label={`Uploading ${item.name}`}
                  aria-valuenow={item.state.percent}
                  aria-valuemin={0}
                  aria-valuemax={100}
                >
                  <div
                    className="h-full bg-signal-500 motion-safe:transition-all"
                    style={{ width: `${item.state.percent}%` }}
                  />
                </div>
              )}
              {item.state.phase === "error" && (
                <p className="mt-1 text-xs text-slateish-400">{item.state.message}</p>
              )}
              {item.state.phase === "done" && item.state.awaitingGrant && (
                <p className="mt-1 text-xs text-slateish-400">
                  Uploaded securely. An administrator must grant access before it appears in Documents.
                </p>
              )}
              {item.state.phase === "done" && !item.state.awaitingGrant && item.state.duplicateOf && (
                <p className="mt-1 text-xs text-slateish-400">
                  Identical content already exists — no second copy was stored.
                </p>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
