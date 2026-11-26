/**
 * The Dashboard's three tiles (owner, 27 Nov 2026 03:34), built ONLY from the shared kit (standing rule R1; listed in kitPages.ts): a plain
 * headline, then one tile per kind of work, each one button to its list. The figures come from At a glance's rows, unchanged.
 */
import { SectionTitle, Stack, Tile, Tiles } from "../kit/Kit";
import { TILE, lateWords, waitingHeadline, type GlanceRow } from "./AtAGlance";

export function GlanceTiles({ rows, onOpen }: { rows: GlanceRow[]; onOpen: (view: "review" | "technicalQueries" | "deliverables" | "dashboard") => void }) {
  return (
    <section aria-labelledby="at-a-glance-title" data-testid="at-a-glance">
      <Stack gap={3}>
        <SectionTitle id="at-a-glance-title">{waitingHeadline(rows)}</SectionTitle>
        <Tiles label="Waiting for a decision">
          {rows.map((r) => (
            <Tile key={r.label} name={TILE[r.label]?.name ?? r.label} number={r.waiting} label="waiting for you"
              done={r.done} late={r.lateStatus === "counted" ? r.late : null} lateWords={lateWords(r)}
              onOpen={() => onOpen(TILE[r.label]?.view ?? "dashboard")} />
          ))}
        </Tiles>
      </Stack>
    </section>
  );
}
