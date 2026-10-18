/**
 * API client.
 *
 * Every call goes through here so two rules hold everywhere:
 *  - a failure is a typed result, never a thrown string rendered raw
 *  - a network failure is distinguishable from an API error, because the UI
 *    must say "the backend is not running" rather than spin or show stale
 *    numbers as if they were live
 */
//
// Order 79b: this file is now the single import surface. The code lives in
// core.ts (the shared base) and one module per area; every name a screen
// imported from here is re-exported, so no screen import changes.

export * from "./core";
export * from "./documents";
export * from "./review";
export * from "./chat";
export * from "./admin";

import { systemApi } from "./admin";
import { documentsApi } from "./documents";
import { chatApi } from "./chat";

/** The original `api` object, rebuilt from the three areas it mixed. */
export const api = { ...systemApi, ...documentsApi, ...chatApi };
