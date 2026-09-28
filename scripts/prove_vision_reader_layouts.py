"""Step 4 of the AI Submittal Review plan: prove the vision reader (#193 B4
item 1, `app.vision_reader`) works across DIFFERENT real datasheet layouts,
not only the one synthetic pattern its safety-gate tests use
(`backend/tests/test_vision_reader.py`).

WHY A SCRIPT, NOT A PYTEST TEST. `backend/tests/conftest.py` deliberately
scrubs every Claude-reading setting at import, on purpose, because a real
Claude call once slipped into a pytest run and spent the owner's real money
(`env_isolation.isolate`, see its docstring). This proof calls the REAL model
by design - a fake provider only proves the verification gate, never proves
the model itself reads an unfamiliar page correctly - so it must run outside
that guard, as its own deliberate, manual action, reading the real
`backend/.env` exactly as the running server does.

WHAT IT COSTS. Each page is one call already metered by `claude_spend` under
the owner's existing USD 5/step, USD 20 total caps (CLAUDE.md rule 1) - this
script adds no new spending path, it only calls the same `vision_reader.
read_page` the app calls.

WHAT IT NEVER DOES. No document text - no field label, no value, no unit - is
ever printed or written to a file. Only: layout names (this script's own,
made up), page numbers, integer counts, and `vision_reader`'s fixed drop-
reason words (e.g. "value not beside label"). Real submittal copies stay
OUTSIDE git; point --bench-dir at wherever they live on this machine.

Usage:

    python scripts/prove_vision_reader_layouts.py                    # report only
    python scripts/prove_vision_reader_layouts.py --bench-dir D:\\path\\to\\copies
    python scripts/prove_vision_reader_layouts.py --write-doc         # also appends
                                                                       # the aggregate
                                                                       # to docs/

Requires, exactly like the app itself: REASONING_PROVIDER=claude,
STANDARDS_READER_ENABLED=true, STANDARDS_READER_ALLOW_PUBLIC_EGRESS=true and
a real ANTHROPIC_API_KEY in backend/.env. Missing any of these is reported by
name (never a stack trace with a key in it) and the script stops.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))

#: Layout name (made up by this script, never the document's own title) ->
#: (filename, 1-based page). Add a row for every extra real layout dropped
#: into --bench-dir; a missing file skips only that one layout.
LAYOUTS: dict[str, tuple[str, int]] = {
    "vessel_full": ("vessel-full.pdf", 4),
    "pump_full": ("pump-full.pdf", 3),
    "instrument_datasheet": ("DS-0000-DAS-I-01.pdf", 1),
    "mechanical_datasheet": ("DS-0000-DAS-M-01.pdf", 1),
    "piping_spec": ("P-1000001-2003-SP-0810-0003_00 (1).pdf", 1),
}

DEFAULT_BENCH_DIR = r"C:\project\docling-bench\input"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--bench-dir", type=Path, default=Path(DEFAULT_BENCH_DIR),
                    help="folder holding the real submittal copies (never git)")
    ap.add_argument("--write-doc", action="store_true",
                    help="append the aggregate result to docs/b4-vision-reader-layout-proof.md")
    args = ap.parse_args(argv)

    import pymupdf

    from app import geometry_reader as gr
    from app import vision_reader as vr

    provider, why = vr.provider()
    if provider is None:
        print(f"STOP - vision reader not usable right now: {why}")
        print("Fix the setting named above in backend/.env, restart nothing "
              "(this script reads .env fresh), and run again.")
        return 1

    present = 0
    rows: list[dict] = []
    for layout, (filename, page_no) in sorted(LAYOUTS.items()):
        path = args.bench_dir / filename
        if not path.is_file():
            print(f"SKIP  {layout:24s} - copy not present at {path}")
            continue
        present += 1
        doc = pymupdf.open(path)
        try:
            page = doc[page_no - 1]
            geometry_rows = gr.read_form(page).get("pairs", [])
            reading = vr.read_page(page, page_no, provider, geometry_rows=geometry_rows)
        finally:
            doc.close()
        rows.append({
            "layout": layout, "page": page_no, "page_kind": reading.page_kind,
            "asked": reading.asked, "refused": reading.refused,
            "proposed": reading.proposed, "kept": len(reading.kept),
            "dropped": dict(reading.dropped),
        })
        status = "REFUSED: " + reading.refused if reading.refused else f"kept {len(reading.kept)}/{reading.proposed}"
        print(f"{'OK' if reading.kept else 'NONE':5s} {layout:24s} page {page_no:>2} "
              f"({reading.page_kind or '?'}) - {status} - dropped {reading.dropped}")

    if present == 0:
        print(f"\nNo real submittal copies found under {args.bench_dir}.")
        print("Copy the layouts this script names into that folder (or pass "
              "--bench-dir) and run again - nothing here reaches git.")
        return 1

    with_hits = sum(1 for r in rows if r["kept"] > 0)
    total_kept = sum(r["kept"] for r in rows)
    total_dropped: dict[str, int] = {}
    for r in rows:
        for reason, count in r["dropped"].items():
            total_dropped[reason] = total_dropped.get(reason, 0) + count

    print(f"\nSUMMARY: {with_hits}/{present} layouts produced at least one "
          f"proven field; {total_kept} fields kept in total; dropped by reason: {total_dropped}")

    if args.write_doc:
        _append_doc(rows, present, with_hits, total_kept, total_dropped)
        print("Appended to docs/b4-vision-reader-layout-proof.md")

    return 0 if with_hits == present else 2


def _append_doc(rows, present, with_hits, total_kept, total_dropped) -> None:
    out = REPO / "docs" / "b4-vision-reader-layout-proof.md"
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"\n## Run at {stamp}\n",
             "Aggregate numbers only - no document text (CLAUDE.md rules 1 and 3).\n",
             "| Layout | Page | Page kind | Kept | Proposed | Dropped |",
             "|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['layout']} | {r['page']} | {r['page_kind'] or '?'} | "
                     f"{r['kept']} | {r['proposed']} | {r['dropped']} |")
    lines.append(f"\n**{with_hits}/{present} layouts produced at least one proven "
                f"field. {total_kept} fields kept in total. Dropped by reason: "
                f"{total_dropped}.**\n")
    if not out.exists():
        out.write_text("# Vision reader (#193 B4 item 1) - real-layout proof log\n"
                       "\nEach run below used real submittal copies kept outside git. "
                       "See `scripts/prove_vision_reader_layouts.py` for how to "
                       "reproduce.\n", encoding="utf-8")
    with out.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
