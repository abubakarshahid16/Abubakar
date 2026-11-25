"""Which technical rule books a paper of a scope-named kind (a contract) may be checked against (owner, 18 Nov 2026 after live: a
form of agreement got 20 technical books and only "does not apply" rows). By the paper's RECORDED kind, never by a name: a book
stays only when the paper cites it or the paper's own scope text (S1's scope quote, verified by code on its page) names its
subject. Read by code only; the scope is never sent with the catalog."""

from __future__ import annotations

import re

from . import WHY_METHOD
from . import library as L

#: The kinds whose technical rule books need the paper's own scope to name their subject: a contract, a specification (it is
#: checked with the contract-labelled rules, so without this rule the books with the most such rules won: welding and vessel
#: code books on a job specification, #1903), and a procedure or study (a HAZOP got coating, insulation and welding books and
#: used none). The METHOD books of the kind always stay; a book the paper cites always stays.
SCOPE_NAMED_KINDS = frozenset({"contract", "specification", "procedure", "study"})
#: Words that name no subject by themselves (a scope sentence and a rule subject both use them freely).
_STOP = frozenset((
    "the", "and", "for", "with", "from", "that", "this", "these", "those", "such", "shall", "will", "must", "under", "into",
    "onto", "upon", "each", "other", "than", "also", "work", "works", "scope", "project", "contract", "contractor", "company",
    "vendor", "supplier", "purchaser", "owner", "party", "parties", "agreement", "requirement", "requirements", "submittal",
    "submission", "approval", "approved", "review", "document", "documents", "procedure", "procedures", "general",
    "provision", "provisions", "data", "report", "plan", "plans", "list", "content", "contents", "format",
))  # fmt: skip


def _words(text) -> set[str]:
    """The words of 4+ letters that name something (not in `_STOP`)."""
    return {
        w for w in re.findall(r"[a-z]{4,}", str(text or "").lower()) if w not in _STOP
    }


def _fold(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def scope_names(scope: str, subjects: list[str], identifier: str = "") -> bool:
    """Does the paper's own scope text NAME this book's subject: its identifier stands in the scope, or one of its rule subjects
    has naming words and ALL of them stand in the scope (`_words`). An empty scope, or one of only generic words, names nothing."""
    words = _words(scope)
    if not words:
        return False
    if identifier and _fold(identifier) and _fold(identifier) in _fold(scope):
        return True
    for subject in subjects or []:
        need = _words(subject)
        if need and need <= words:
            return True
    return False


def keep(
    cat: list[dict], required: dict, kind, scope: str, cited
) -> tuple[list[dict], dict]:
    """(the catalog lines kept, the required books kept): for a kind in `SCOPE_NAMED_KINDS`, only the books the paper cites or
    its scope names (`scope_names`); any other kind: all, as given."""
    if kind not in SCOPE_NAMED_KINDS:
        return cat, required
    method = {
        b for b, why in required.items() if str(why).startswith(WHY_METHOD)
    }  # the kind's method books always stay
    cat = [
        c
        for c in cat
        if c["book"] in (cited or ())
        or c["book"] in method
        or scope_names(scope, c["subjects"], c["identifier"])
    ]
    kept = {c["book"] for c in cat}
    return cat, {b: w for b, w in required.items() if b in kept}


def saved_fits_scope(
    conn, saved: dict, ident: dict, cited: frozenset[str] = frozenset()
) -> bool:
    """May a SAVED checklist be reused for this paper? For a kind in `SCOPE_NAMED_KINDS`, only when every book it rests on is cited
    by the paper or named by its own scope (`scope_names`, the same rule as `checklist._catalog`); any other kind: yes."""
    kind = ident.get("kind")
    if kind not in SCOPE_NAMED_KINDS:
        return True
    scope = str(ident.get("scope_quote") or "")
    method = {
        e["id"] for e, _name in L.method_books(L.library(conn), kind) if e
    }  # the kind's method books always stay
    books = [
        b
        for b in L.saved_books(saved)
        if b not in (cited or frozenset()) and b not in method
    ]
    if not books:
        return True
    by_id = {e["id"]: e for e in L.library(conn, within=frozenset(books))}
    pool = L.rule_pool(conn, kind, ident.get("equipment_type"), within=frozenset(books))
    lines = {c["book"]: c for c in L.catalog(by_id, pool)}
    for b in books:
        name = L.identifier_of(by_id[b]) if b in by_id else ""
        if not scope_names(scope, (lines.get(b) or {}).get("subjects") or [], name):
            return False
    return True
