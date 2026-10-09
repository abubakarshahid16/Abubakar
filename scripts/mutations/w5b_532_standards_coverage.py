"""#532: the reference-standards coverage report. Ids M4981-M4989."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_w5b_532_standards_coverage.py"
_I = APP / "standards_inventory.py"
_TAG = ("w5b", "coverage")


def _m(i, desc, anchor, repl, kw=None, path=_I):
    return Mutation(id=f"M{i}", phase=i, description=desc, path=path, anchor=anchor,
                    replacement=repl, target=_T, keyword=kw, tags=_TAG)


MUTATIONS: tuple[Mutation, ...] = (
    _m(4981, "every listed standard is reported missing",
       '"status": "held" if held is not None else "missing",', '"status": "missing",'),
    _m(4982, "an edition is never read from the file name",
       'edition = (standard_ids.edition_of(held.get("filename") or "")',
       'edition = (None and standard_ids.edition_of(held.get("filename") or "")'),
    _m(4983, "the recorded revision is not used as the edition",
       'or (str(held.get("revision")).strip() if held.get("revision") else None))', "or None)"),
    _m(4984, "a superseded held standard is not flagged",
       '"superseded": bool(held and held.get("superseded_by")),', '"superseded": False,'),
    _m(4985, "the library is read without the caller's grants",
       "allowed_document_ids=allowed_document_ids, include_superseded=True)\n    groups = []",
       "allowed_document_ids=frozenset(r[\"id\"] for r in connect().execute(\"SELECT id FROM documents\")),\n"
       "        include_superseded=True)\n    groups = []"),
    _m(4986, "an unreadable list is reported as an empty pass",
       'if data is None or not isinstance(data.get("groups"), list):', "if False:"),
    _m(4987, "the missing count is always zero",
       '"missing": sum(1 for r in rows if r["status"] == "missing"),', '"missing": 0,'),
    _m(4988, "the route reports for an empty scope",
       "    return standards_inventory_mod.reference_coverage(\n        allowed_document_ids=scope.allowed_document_ids)",
       "    return standards_inventory_mod.reference_coverage(\n        allowed_document_ids=frozenset())", path=APP / "main.py"),
    _m(4989, "a standard is matched by its family only",
       "held = find_standard(library, identifier)",
       "held = next((e for e in library if identifier.split()[0] in (e.get(\"filename\") or \"\")), None)"),
)
