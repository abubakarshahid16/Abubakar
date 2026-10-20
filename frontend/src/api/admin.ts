/**
 * Sign-in, user management and system health calls.
 *
 * Split out of api/client.ts (order 79b). Moved verbatim; screens keep
 * importing from "api/client", which re-exports this module.
 */
import type { Health, WatchStatus } from "./documents";
import type {
  ModelsFreed,
  AuthStatus,
  LoginResult,
  LogoutResult,
  PasswordResetResult,
  Metrics,
  ManagementSummary,
  EscalationRule,
} from "../types/api";

import { request, hasArrayField } from "./core";
export const auth = {
  login: (email: string, password: string) =>
    request<LoginResult>("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      // The browser's way (order 164.2): the server keeps the login in an
      // HttpOnly cookie and sends no token, so the page holds nothing to steal.
      body: JSON.stringify({ email, password, session: "cookie" }),
    }),
  logout: () => request<LogoutResult>("/auth/logout", { method: "POST" }),
  me: () => request<AuthStatus>("/auth/me"),
  resetPassword: (token: string, password: string) =>
    request<PasswordResetResult>("/auth/password/reset", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token, password }),
    }),
};

export const management = {
  summary: () => request<ManagementSummary>("/management/summary"),
  emailSummary: () => request<{ sent: boolean }>("/management/summary/email", { method: "POST" }),
  summarySchedule: () => request<{ schedule: "disabled" | "daily" | "weekly"; weekday_utc: number; hour_utc: number }>("/management/summary/schedule"),
  setSummarySchedule: (body: { schedule: "disabled" | "daily" | "weekly"; weekday_utc: number; hour_utc: number }) => request<typeof body>("/management/summary/schedule", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  escalationRules: () => request<{ rules: EscalationRule[] }>("/management/escalation-rules"),
  updateEscalationRule: (level: number, body: Partial<EscalationRule>) =>
    request<EscalationRule>(`/management/escalation-rules/${level}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
};

export const systemApi = {
  health: () => request<Health>("/health"),
  /** Administrator only (a 404 for anyone else): ask Ollama to unload every
   *  resident model. The next question pays a cold load. */
  freeModelMemory: () =>
    request<ModelsFreed>("/admin/models/unload", { method: "POST" }, hasArrayField("freed")),
  metrics: () => request<Metrics>("/metrics"),
  /** Whether the watched folder is running, and what it last picked up.
   *  Guarded like the other list-bearing reads: a body without `recent`
   *  becomes an ordinary ApiError instead of a crash at the map. */
  watchStatus: () => request<WatchStatus>("/watch/status", undefined, hasArrayField("recent")),
};
