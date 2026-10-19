/** OWNER: builder B. Sign-off inside the sheet (PLACEHOLDER - planner team). */
import type { SignOffPanelProps } from "./contract";

export function SignOffPanel({ numbers }: SignOffPanelProps) {
  return <div data-testid="ws-sign-off"><span data-count="undecided">{numbers.undecided}</span> left to decide</div>;
}
