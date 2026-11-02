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
        "    return quoted in (NO_NUMBER_LABEL, fragment, label + SUGGESTED_SUFFIX)\n",
        "    return quoted in (NO_NUMBER_LABEL, label + SUGGESTED_SUFFIX)\n",
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
        "another document's reply quoting a shared label is written to this document's comments",
        _N,
        '        if why:\n            reply["refused"] = why\n',
        '        if False:\n            reply["refused"] = why\n',
        "refuses_anothers or one_suggested_number",
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
    _m(
        13,
        "a section's own leading digits are eaten with the page lead",
        _P,
        '_PAGE_LEAD = re.compile(r"^p\\.\\d+(?:-\\d+)?(?:, \\d+(?:-\\d+)?)*(?: - |$)")\n',
        '_PAGE_LEAD = re.compile(r"^p\\.\\s*\\d[\\d,\\s\\-]*(?:\\s-\\s)?")\n',
        "exact_page_lead or starts_with_digits",
    ),
    _m(
        14,
        "a real number's reply reaches a suggested sequence of the same digits",
        _N,
        "    return quoted in (NO_NUMBER_LABEL, fragment, label + SUGGESTED_SUFFIX)\n",
        "    return quoted in (NO_NUMBER_LABEL, fragment) or quoted.removesuffix(\n"
        "        SUGGESTED_SUFFIX\n"
        "    ) == label.removesuffix(SUGGESTED_SUFFIX)\n",
        "real_number",
    ),
    _m(
        15,
        "the reply guard goes off with the switch, for rows stored NO-NUMBER",
        _N,
        "        scope_key.startswith(_DOC_SCOPE)\n        and quoted[0] != _id_fragment(document_id)\n",
        "        _sequenced_document(scope_key) is not None\n        and quoted[0] != _id_fragment(document_id)\n",
        "guard_stays",
    ),
    _m(
        16,
        "a refused reply gives no reason",
        _N,
        '    return reply.get("refused") or "another submittal\'s number"\n',
        '    return "another submittal\'s number"\n',
        "says_why or one_suggested_number",
    ),
    _m(
        17,
        "two documents of one name both take a reply quoting a shared label",
        _P,
        '    if conn.execute(sql, (name,)).fetchone()["n"] > 1:\n',
        "    if False:\n",
        "two_documents_of_one_name",
    ),
    _m(
        18,
        "a date on the cover is suggested as the document number",
        _P,
        "        and not _DATE_SHAPE.match(value)\n",
        "",
        "date_on_the_cover or date_beside",
    ),
    _m(
        19,
        "every reply reads all the document's pages again",
        _P,
        "@lru_cache(maxsize=32)\n",
        "",
        "pages_once",
    ),
    _m(
        20,
        "the page cache ignores changed pages",
        _P,
        '        str(settings.db_path), document_id, (row["n"], row["chars"])\n',
        "        str(settings.db_path), document_id, ()\n",
        "changed_pages",
    ),
)
