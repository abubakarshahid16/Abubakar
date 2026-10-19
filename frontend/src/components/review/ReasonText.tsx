import { splitReason } from "./reasonWords";

/** A text that may open with a reason code: the code's sentence, then the
 *  rest; the code itself only in the tooltip. */
export function ReasonText({ text }: { text: string }) {
  const { code, words, rest } = splitReason(text);
  if (code === null) return <>{text}</>;
  return (
    <span title={`Internal reason code: ${code}`} data-reason-code={code}>
      {[words, rest].filter(Boolean).join(" ")}
    </span>
  );
}
