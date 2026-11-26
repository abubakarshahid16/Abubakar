"""A tool, not part of the app (it is started by the exam kit, never by the server). FIGURES INSIDE RULE BOOKS, READ AS RULES (owner, 26 Nov 2026, #1584 comment 7189065710: "Yes, allow it"; job J2).

The figure pages of a HELD rule book (a company standard of the SAES, ISO, API, ASME or NACE family) are read ONCE each as a picture by
Claude, and every requirement a figure shows comes back as a rule marked "from a figure, page N". The rules go to a FILE first (one JSON
line per page), never the database: a judged sample (one page in ten) is scored and its error rate reported to the owner before one live
library step, with a backup, adds them.

  * ONLY through the standards lane, as its own named user ("figure reading", `standards_lane.USERS`): the book is checked
    first (`standards_lane.check`: held, a company standard of an allowed family, not held for an administrator's confirmation); never a
    datasheet, procedure, contract, CRS, submittal or the client's register (the lane refuses them and the gate's blocks still win);
    never inside a review run or another declaration.
  * Claude only through `reasoning_provider.ClaudeProvider` -> `reader_transport`, each call under the `claude_spend` caps with the
    step `standards_convert:<book>`: the owner's USD 25 per standard, shared with that book's text conversion, and the day and month caps.
  * A refused or failed page stops the rest of that book; the file says each page's state. No document text is logged.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from app import pdf_guard, standards_lane
from app.config import settings

log = logging.getLogger(__name__)

PROMPT_VERSION = "figure-rules-v1"
MAX_OUTPUT_TOKENS = 1500
TIMEOUT_S = 300.0
MARK = "from a figure, page {page}"
READ, NONE, FAILED, REFUSED = "read", "no_rule", "failed", "refused"
SYSTEM = (
    "You read ONE page of a held rule book (a standard), given as a picture. The page holds a figure, a chart or a table drawn as a "
    "picture. Write each requirement THE FIGURE ITSELF shows (a dimension, a limit, a value read from a chart or table, a required "
    "arrangement), one rule each, in the book's own terms, with every number and unit exactly as printed. Write nothing the figure does "
    "not show and nothing from general knowledge. Reply with ONE JSON object only: "
    '{"rules": [{"rule": "one sentence", "figure": "the figure or table number and title as printed", '
    '"values": ["each number with its unit, as printed"]}]}; when the page shows no requirement, {"rules": []}.'
)


def parse(text: str) -> list[dict] | None:
    """The rules of one answer (bounded), or None when the answer holds no such JSON object."""
    m = re.search(r"\{.*\}", str(text or ""), re.S)
    try:
        got = json.loads(m.group(0)) if m else None
    except ValueError:
        return None
    if not isinstance(got, dict) or not isinstance(got.get("rules"), list):
        return None
    out = []
    for r in got["rules"][:20]:
        if isinstance(r, dict) and str(r.get("rule") or "").strip():
            out.append({"rule": str(r["rule"]).strip()[:600], "figure": str(r.get("figure") or "").strip()[:160],
                        "values": [str(v)[:60] for v in (r.get("values") or [])][:12] if isinstance(r.get("values"), list) else []})  # fmt: skip
    return out


def identifier(conn, book_id: str) -> str:
    """The book's own number or name (standards text, allowed in the lane): the recorded number, else the file name."""
    row = conn.execute(
        "SELECT c.document_number, d.filename FROM documents d LEFT JOIN document_classification c ON c.document_id = d.id "
        "WHERE d.id = ?", (book_id,)).fetchone()  # fmt: skip
    return str((row[0] if row and row[0] else (row[1] if row else "")) or book_id)


def read_book(
    conn, book_id: str, pages: list[int], pdf_path, out, provider=None
) -> dict:
    """Read the figure `pages` of one held book; write one JSON line per page to `out` (an open text file). Returns the counts.
    Raises `standards_lane.NotStandardsLane` (nothing sent) for a document outside the lane."""
    from app import vision_reader
    from app.claude_spend import STANDARD_STEP_PREFIX
    from app.reasoning_provider import ClaudeProvider, Packet

    checked = standards_lane.check(conn, [book_id])
    if provider is None:
        provider = ClaudeProvider(
            settings.claude_reasoning_model, step=f"{STANDARD_STEP_PREFIX}{book_id}"
        )
    name = identifier(conn, book_id)
    counts = dict.fromkeys((READ, NONE, FAILED, REFUSED), 0)
    stopped = None
    with standards_lane.open_for(conn, [book_id], checked, user="figure reading"):
        for n in pages:
            line: dict = {"book": book_id, "page": n, "mark": MARK.format(page=n)}
            if stopped:
                line.update(state=REFUSED, why=stopped)
            else:
                try:
                    with pdf_guard.opened(str(pdf_path)) as pdf, pdf_guard.held():
                        image = vision_reader.render(pdf.load_page(n - 1))
                    response = provider.reason(Packet(
                        prompt=f"Rule book {name}, page {n}. Read its figure as rules.", system=SYSTEM, num_ctx=32768,
                        num_predict=MAX_OUTPUT_TOKENS, step=vision_reader.VISION_STEP, prompt_version=PROMPT_VERSION,
                        images=(image,), timeout_s=TIMEOUT_S, effort=vision_reader.EFFORT))  # fmt: skip
                except Exception as exc:  # noqa: BLE001 - a refusal (cap, lane, gate) or a failure: this page and the rest say so
                    log.info("figure reading: stopped (%s)", type(exc).__name__)
                    stopped = f"refused or failed ({type(exc).__name__})"
                    line.update(state=REFUSED, why=stopped)
                else:
                    rules = parse(response.text)
                    state = (
                        FAILED
                        if rules is None or response.truncated
                        else (READ if rules else NONE)
                    )
                    line.update(
                        state=state,
                        rules=rules or [],
                        model=response.model_tag,
                        usd=response.cost_usd,
                    )
            counts[line["state"]] += 1
            out.write(json.dumps(line, ensure_ascii=False) + "\n")
    return counts


def judge_sample(lines: list[dict], every: int = 10) -> list[dict]:
    """The judged sample: one read page in `every`, picked by position in the file's order (book, page): never by its rules."""
    read = sorted(
        (x for x in lines if x.get("state") == READ),
        key=lambda x: (x["book"], x["page"]),
    )
    return read[:: max(1, int(every))]


def load(path) -> list[dict]:
    return [json.loads(x) for x in Path(path).read_text().splitlines() if x.strip()]
