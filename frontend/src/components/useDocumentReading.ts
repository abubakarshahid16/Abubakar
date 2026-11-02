/**
 * What was read of each document (`/api/document-reading`). One request shared by every
 * card, repeated at most once a minute. Empty with the switch off, and on any failure: the
 * status then shows as it always did.
 */
import { useEffect, useState } from "react";

import { request } from "../api/core";
import type { DocumentReading } from "../types/api";

type Readings = Record<string, DocumentReading>;

const MAX_AGE_MS = 60_000;
let shared: { at: number; pending: Promise<Readings> } | null = null;

function load(): Promise<Readings> {
  if (!shared || Date.now() - shared.at > MAX_AGE_MS) {
    const pending = request<{ documents: Readings }>("/api/document-reading")
      .then((result) => (result.ok ? result.data.documents : {}))
      .catch(() => ({}));
    shared = { at: Date.now(), pending };
  }
  return shared.pending;
}

export function useDocumentReading(): Readings {
  const [readings, setReadings] = useState<Readings>({});
  useEffect(() => {
    let live = true;
    void load().then((found) => {
      if (live) setReadings(found);
    });
    return () => {
      live = false;
    };
  }, []);
  return readings;
}
