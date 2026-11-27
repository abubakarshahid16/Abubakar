import type { MetricWarning } from "../../types/api";
import { NavLink } from "../NavLink";
import { NEW_LOOK } from "../../look";

/** A warning's sentence in everyday words for the new look (owner's design audit, 26 Nov 2026 23:05, J): the engine words of the AI
 *  steps' model warning read as "not on this computer"; every other message is shown as the server wrote it. */
export function plainWarning(message: string): string {
  return message
    .replace(/^The AI review steps: /, "Some review steps: ")
    .replace(/ is not installed on the engine\b/g, " is not on this computer")
    .replace(/\b(neither .+ nor .+) is installed\b/, "$1 is on this computer");
}

/** A warning in everyday words for the new look, by its code (owner's picture, 27 Nov 2026, relayed by A: "Recognition has not run",
 *  "equation-heavy", "mitigation" and the AI model file names were on the main screen). The model names stay only in the folded
 *  technical area (its Models section). A message whose shape is not known keeps plainWarning's words. */
export function plainWarningFor(warning: Pick<MetricWarning, "code" | "message">): string {
  const n = warning.message.match(/^(\d[\d,]*)\b/)?.[1];
  const one = n === "1";
  switch (warning.code) {
    // only the message shapes the server sends today: another shape (an older "OCR is not implemented") keeps its own meaning
    case "needs_ocr":
      if (n && /Recognition has not run/.test(warning.message)) return `${n} scanned page${one ? " has" : "s have"} not been read yet, so ${one ? "it cannot" : "they cannot"} be searched yet.`;
      break;
    case "pages_recognised":
      if (n && /read by OCR/.test(warning.message)) return `${n} scanned page${one ? " was" : "s were"} read as ${one ? "a picture" : "pictures"} and can be searched. Text read this way is marked as such wherever it is quoted.`;
      break;
    case "equation_pages":
      if (n && /equation-heavy/.test(warning.message)) return `${n} page${one ? " is" : "s are"} mostly equations, which do not come through as text. Open the page picture to read ${one ? "it" : "them"}.`;
      break;
    case "ai_steps_model":
      if (!/^The AI review steps: /.test(warning.message)) break;
      return /They run on /.test(warning.message)
        ? "Some review steps run on a different AI on this computer than the one that was set. Which one is under Technical detail."
        : "Some review steps cannot run, because their AI is not on this computer. The details are under Technical detail.";
  }
  return plainWarning(warning.message);
}

export function MetricWarningRow({ warning }: { warning: MetricWarning }) {
  const style = warning.severity === "error"
    ? "border-danger-500/50 bg-danger-500/10 text-danger-500"
    : warning.severity === "warning"
      ? "border-warn-500/50 bg-warn-500/10 text-warn-500"
      : "border-ink-600 bg-ink-850 text-slateish-400";
  // the new look: the kit's notice box (H's audit 2: one notice style), problem for an error, check for a warning
  // one notice shape, its tone by severity; plain information is the quiet notice (owner's picture: three notice styles in a row)
  const kit = warning.severity === "error" ? "kit-notice kit-notice--problem" : warning.severity === "warning" ? "kit-notice kit-notice--warn" : "kit-notice kit-notice--quiet";
  return <li className={NEW_LOOK ? kit : `rounded-[var(--radius-sm)] border px-3 py-2 text-sm ${style}`}>
    <span role={warning.severity === "error" ? "alert" : "status"}>
      {/* The app's own navigation, not a page load: the token is memory-only
          and a reload signed the reader out. */}
      {warning.document_id
        ? <NavLink view="documents" recordId={warning.document_id} className={NEW_LOOK ? "underline-offset-2 hover:underline" : "text-slateish-300 underline-offset-2 hover:underline"}>{NEW_LOOK ? plainWarningFor(warning) : warning.message}</NavLink>
        : <NavLink view="deliverables" className={NEW_LOOK ? "underline-offset-2 hover:underline" : "text-slateish-300 underline-offset-2 hover:underline"}>{NEW_LOOK ? plainWarningFor(warning) : warning.message}</NavLink>}
      {/* The code on its own line, named for a screen reader: a margin alone
          kept it apart on screen, but the text ran "...on thisINTERNAL" when
          read aloud or copied (order 88c, #1097). */}
      {" "}
      {/* the new look shows no setting code on the first screen (the audit's raw "AI_STEPS_MODEL"): it stays as the row's tooltip */}
      {NEW_LOOK ? <span className="sr-only" title={warning.code}> </span> : <span className="mt-0.5 block font-mono text-xs uppercase tracking-wide text-slateish-500">
        <span className="sr-only">Technical detail: </span>{warning.code}
      </span>}
    </span>
  </li>;
}
