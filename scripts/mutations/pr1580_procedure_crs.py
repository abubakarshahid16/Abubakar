"""Order 4c / PR 1580, a procedure's CRS fields (crs_numbers is danger zone): each entry
undoes one decision; backend/tests/test_procedure_crs_fields.py must notice."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_procedure_crs_fields.py"
_TAG = ("pr1580", "procedure_crs")
_N = APP / "crs_numbers.py"
_P = APP / "procedure_crs.py"
_K = APP / "kind_rules.py"
_R = APP / "procedure_playbook_rows.py"


def _m(n, desc, path, anchor, repl, kw=None):
    return Mutation(
        id=f"M1580-{n:02d}",
        phase=1580,
        description=desc,
        path=path,
        anchor=anchor,
        replacement=repl,
        target=_T,
        keyword=kw,
        tags=_TAG,
    )


MUTATIONS: tuple[Mutation, ...] = (
    _m(
        1,
        "a suggested document number prints as if it were confirmed",
        _N,
        "        return label + SUGGESTED_SUFFIX\n",
        "        return label\n",
        "marked_suggestion",
    ),
    _m(
        2,
        "a new document sequence prints the document id again",
        _N,
        "    if settings.procedure_crs_fields_enabled:\n        return _DOC_SCOPE + document_id,",
        "    if False:\n        return _DOC_SCOPE + document_id,",
        "neutral_label",
    ),
    _m(
        3,
        "a stored sequence prints the document id it was stored with",
        _N,
        '    out["ref"] = format_ref(shown or r["label"], r["seq"])\n',
        '    out["ref"] = format_ref(r["label"], r["seq"])\n',
        "not_rewritten",
    ),
    _m(
        4,
        "a reference already issued with the id label no longer resolves",
        _N,
        "    return quoted in (NO_NUMBER_LABEL, fragment) or (\n",
        "    return quoted in (NO_NUMBER_LABEL,) or (\n",
        "already_issued or id_label",
    ),
    _m(
        5,
        "a suggested number is stored with the comment's number",
        _N,
        "    return NO_NUMBER_LABEL if _sequenced_document(scope_key) is not None else label\n",
        "    return label\n",
        "never_stored",
    ),
    _m(
        6,
        "another document's reply quoting NO-NUMBER is written to this document's comments",
        _N,
        "    if quoted is not None and procedure_crs.other_document(quoted[0], reply, document_id):\n",
        "    if False:\n",
        "refuses_anothers",
    ),
    _m(
        7,
        "a quote on several pages is given the first of them",
        _P,
        "    return hits[0] if len(hits) == 1 else None\n",
        "    return hits[0] if hits else None\n",
        "no_page_or_several",
    ),
    _m(
        8,
        "an unverified quote keeps the page already printed",
        _P,
        '        rest = _PAGE_LEAD.sub("", str(row.get("page_section") or ""))\n',
        '        rest = str(row.get("page_section") or "")\n',
        "fills_clears",
    ),
    _m(
        9,
        "the CRS of a procedure reads the equipment type again",
        _K,
        "    token = _NO_TYPE.set(on)\n",
        "    token = _NO_TYPE.set(False)\n",
        "names_no_equipment or non_datasheet_kind",
    ),
    _m(
        10,
        "two different numbers on the cover: the first is suggested",
        _P,
        "    if len({classification._identity(n) for n, _p, _q in numbers}) != 1:\n",
        "    if not numbers:\n",
        "two_different_numbers",
    ),
    _m(
        11,
        "the standards sheet prints the stored reason that names the type",
        _P,
        '            "reason": REASON_NOT_FOR_KIND.format(kind=kind),\n',
        '            "reason": row.get("reason"),\n',
        "drops_the_type",
    ),
    _m(
        12,
        "the export never fills the page cell",
        _R,
        "    procedure_crs.fill_pages(merged, list(findings), submittal_id)\n",
        "",
        "export_prints_the_page",
    ),
)
