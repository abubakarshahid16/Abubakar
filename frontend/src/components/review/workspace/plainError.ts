/**
 * v2.1 (N2): a failed request said in plain words. The screen never shows
 * the server's raw text alone: it shows one plain sentence about what went
 * wrong and what to do, and keeps the server's words as a detail after it
 * (`detail`), for whoever has to look into it.
 */
import type { ApiError } from "../../../types/api";

export interface PlainError {
  /** One plain sentence (or two): what failed and what to do now. */
  words: string;
  /** The server's own words, or null when it sent none. */
  detail: string | null;
}

/** A failed result as the API client hands it back (only what is needed). */
export interface FailedResult {
  disconnected?: boolean;
  error?: Partial<Pick<ApiError, "code" | "message">> | null;
}

/** `lead` says what could not be done ("Could not open this review."). */
export function plainError(lead: string, failure: FailedResult | null | undefined): PlainError {
  const detail = failure?.error?.message?.trim() || null;
  const code = failure?.error?.code;
  let next: string;
  if (failure?.disconnected) next = "The server could not be reached. Check your connection, then try again.";
  else if (code === "unauthenticated") next = "Your sign-in has ended. Sign in again to carry on.";
  else if (code === "not_found") next = "It could not be found. It may have been removed, or the link may be wrong.";
  else next = "Try again in a moment.";
  return { words: `${lead} ${next}`, detail };
}

/** The same as one line of text, for places that show a single string:
 *  the plain words, then "Details: <server words>" when there are any. */
export function plainErrorText(lead: string, failure: FailedResult | null | undefined): string {
  const { words, detail } = plainError(lead, failure);
  return detail ? `${words} Details: ${detail}` : words;
}
