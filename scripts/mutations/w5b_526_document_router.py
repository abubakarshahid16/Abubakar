"""#526 "the document-type router": each entry deletes one part;
backend/tests/test_w5b_526_document_router.py (or the chip's vitest file) must
notice. The SQL guard `WHERE document_kinds.state != 'confirmed'` in
`route_document` is deliberately redundant with the Python early return (it
closes a race with a concurrent confirm), so it has no mutation here."""
from __future__ import annotations

from ._base import APP, FRONTEND_SRC, Mutation

_T = "tests/test_w5b_526_document_router.py"
_TAG = ("w5b_526", "document_router")


def _m(i, desc, path, anchor, repl, kw=None):
    return Mutation(id=f"M{i}", phase=i, description=desc, path=APP / path,
                    anchor=anchor, replacement=repl, target=_T, keyword=kw, tags=_TAG)


R = "doc_router.py"
MUTATIONS: tuple[Mutation, ...] = (
    _m(4301, "an unclear document is given a kind anyway", R,
       "    if best_score >= min_score and best_score - second_score >= min_margin:\n",
       "    if True:\n", "unclear"),
    _m(4302, "two close kinds are not told apart (no margin)", R,
       "    if best_score >= min_score and best_score - second_score >= min_margin:\n",
       "    if best_score >= min_score:\n", "close"),
    _m(4303, "body cues are not capped", R,
       "                if body_total >= cap:\n                    continue\n"
       "                weight = min(weight, cap - body_total)\n",
       "", "capped"),
    _m(4304, "a confirmed kind is overwritten by a routing run", R,
       '    if existing is not None and existing["state"] == STATE_CONFIRMED:\n',
       "    if False:\n", "confirmed_kind_is_never"),
    _m(4305, "a document with no text is routed from its name alone", R,
       "    if not any((p or \"\").strip() for p in pages):\n", "    if False:\n", "no_text"),
    _m(4306, "an unknown kind is accepted", R,
       '    if kind not in vocabulary()["kinds"]:\n', "    if False:\n", "unknown_kind"),
    _m(4307, "the counts ignore whose documents they count", R,
       "    if allowed is not None:\n        if not allowed:\n", "    if False:\n        if not allowed:\n", "counts"),
    _m(4308, "documents still being read are routed", R,
       "WHERE d.status IN ('ready', 'partially_searchable', 'no_searchable_content')",
       "WHERE d.status IS NOT NULL", "only_what_has_no_routing"),
    _m(4309, "a routed but unclassified document has no record", "classification.py",
       "        out.setdefault(document_id, empty_record(document_id)).update(kind)\n",
       "        if document_id in out:\n            out[document_id].update(kind)\n", "carry_the_kind"),
    _m(4310, "the worker never routes", "ingest.py",
       "                    _route_document_kind(doc_id, result)\n", "", "worker_routes"),
    _m(4311, "a routing failure fails ingestion", "ingest.py",
       "    except Exception as exc:  # noqa: BLE001 - advice must not block ingestion\n",
       "    except ZeroDivisionError as exc:\n", "does_not_fail_ingestion"),
    _m(4312, "anyone may confirm a kind", "main.py",
       '    actor: dict | None = Depends(admin_mod.current_admin),\n):\n    """A person confirms (or corrects) the document type',
       '    actor: dict | None = None,\n):\n    """A person confirms (or corrects) the document type', "non_admin"),
    _m(4313, "anyone may route the whole library", "main.py",
       "def route_document_kinds(_admin: dict | None = Depends(admin_mod.current_admin)):",
       "def route_document_kinds(_admin: dict | None = None):", "route_all_is_admin"),
    _m(4314, "the kinds route counts every document, not the caller's", "main.py",
       "    allowed = None if scope.unrestricted else scope.allowed_document_ids\n    return {\"kinds\"",
       "    allowed = None\n    return {\"kinds\"", "vocabulary_route"),
    Mutation(id="M4315", phase=4315, runner="vitest", description="a suggestion is shown as a plain type",
             path=FRONTEND_SRC / "components" / "DocumentKindChip.tsx",
             anchor="{`${label}? \u00b7 guessed, not confirmed`}", replacement="{label}",
             target="src/components/DocumentKindChip.test.tsx", keyword="guess", tags=_TAG),
    Mutation(id="M4316", phase=4316, runner="vitest", description="a non-admin is given the confirm control",
             path=FRONTEND_SRC / "components" / "DocumentKindChip.tsx",
             anchor="const canPick = isAdmin && !!onConfirm", replacement="const canPick = !!onConfirm",
             target="src/components/DocumentKindChip.test.tsx", keyword="non-admin", tags=_TAG),
)
