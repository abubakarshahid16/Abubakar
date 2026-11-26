"""The paper's SERVICE as a key for book choice (update 13, AIM_U13_ENABLED; planner, 26 Nov 2026: a paper in sour service was reviewed
without the sour-service standards, so a hardness above the service limit was not asked). The table is DATA
(`reference/service_standards.json`): each service's markers, the words a paper uses to DECLARE it, and its standards. When the paper's
stored text declares a service, that service's standards are looked up among the held books with the governing-book lookup and added
as required books, with their own reason (`WHY_SERVICE`). Read at plan time from the stored pages, so the books are on the shown list
before anything is sent (CLAUDE.md rule 1). Off: nothing. No standard or equipment name is written in this code."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from . import WHY_SERVICE  # noqa: F401 - re-exported for the book choice (`library`)

PATH = Path(__file__).resolve().parent.parent / "reference" / "service_standards.json"


@lru_cache(maxsize=1)
def _table() -> dict:
    return json.loads(PATH.read_text()).get("services") or {}


def declared(text: str) -> list[str]:
    """The services the text declares (any marker as a whole phrase), in the table's order."""
    out = []
    for name, entry in _table().items():
        if any(
            re.search(rf"(?<![A-Za-z0-9]){m}(?![A-Za-z0-9])", text or "", re.I)
            for m in entry.get("markers") or []
        ):
            out.append(name)
    return out


def service_books(
    conn, paper_id: str, lib: list[dict]
) -> list[tuple[dict | None, str]]:
    """[(held book or None, standard identifier)] of the services the paper declares, update 13 on; [] off or none declared."""
    from app import applicability

    from .updates import u13

    if not u13() or not paper_id:
        return []
    rows = conn.execute(
        "SELECT text FROM pages WHERE document_id = ? ORDER BY page_no",
        (str(paper_id),),
    ).fetchall()
    services = declared("\n".join(str(r[0] or "") for r in rows))
    if not services:
        return []
    from .library import STANDARD_ROLE

    stds = [e for e in lib if (e.get("document_role") or "") == STANDARD_ROLE]
    out, seen = [], set()
    for s in services:
        for ident in _table()[s].get("standards") or []:
            hit = applicability.find_standard(stds, ident)
            key = hit["id"] if hit else ident
            if key not in seen:
                seen.add(key)
                out.append((hit, ident))
    return out
