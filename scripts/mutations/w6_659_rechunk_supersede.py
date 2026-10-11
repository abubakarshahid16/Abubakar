"""#659: a re-chunk detaches, re-points or supersedes requirements; it never
deletes them. Ids M4961-M4968."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_w6_659_rechunk_supersede.py"
_G = APP / "orphan_guard.py"
_TAG = ("w6", "data-loss")


def _m(i, desc, path, anchor, repl, kw):
    return Mutation(id=f"M{i}", phase=i, description=desc, path=path, anchor=anchor,
                    replacement=repl, target=_T, keyword=kw, tags=_TAG)


MUTATIONS: tuple[Mutation, ...] = (
    _m(4961, "requirements are not detached before the chunks are deleted (the cascade takes them)", _G,
       "    if detached:\n        conn.execute(\n            \"UPDATE standard_requirements SET chunk_id = NULL",
       "    if False:\n        conn.execute(\n            \"UPDATE standard_requirements SET chunk_id = NULL", "keeps_its_link or repointed or superseded"),
    _m(4962, "requirements are never put back on the new chunks", APP / "chunker.py",
       "        orphan_guard.reattach_requirements_after_rechunk(conn, doc_id, detached)",
       "        pass", "keeps_its_link or repointed or superseded"),
    _m(4963, "an unchanged chunk id is not recognised", _G,
       '        if r["chunk_id"] in new_ids:', "        if False:", "unchanged_chunk"),
    _m(4964, "a sentence is not searched for in the new chunks", _G,
       "            if len(needle) >= 12:", "            if False:", "repointed"),
    _m(4965, "an unconfirmed requirement with nowhere to go is left unlinked and active", _G,
       "        else:\n            superseded_ids.append(r[\"id\"])", "        else:\n            pass", "superseded_not_deleted"),
    _m(4966, "a confirmed requirement is superseded like any other", _G,
       '        elif r["confirmed_by"] is not None:\n            counts["confirmed_unlinked"] += 1',
       '        elif False:\n            counts["confirmed_unlinked"] += 1', "never_superseded"),
    _m(4967, "the re-chunk leaves no audit record", _G,
       "VALUES (?, ?, ?, 'requirements.rechunked', 'document', ?, 'ok', ?)",
       "VALUES (?, ?, ?, 'requirements.unrecorded', 'document', ?, 'ok', ?)", "unchanged_chunk"),
    _m(4968, "re-chunking needs the requirements table to exist", _G,
       '        if "no such table" in str(exc):\n            return []\n        raise\n    detached',
       '        if False:\n            return []\n        raise\n    detached', "no_requirements_table"),
)
