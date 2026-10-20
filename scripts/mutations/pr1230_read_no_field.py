"""Order 165 item E: a page two readers read and found no field on is read.
`comparison.py` (one rationale sentence) and `page_ledger.py` are on the
review's path; PR #1230: ids M1230-01 onwards, phase 1230."""

from __future__ import annotations

from ._base import APP, Mutation

_L = APP / "page_ledger.py"
_T = "tests/test_165e_read_no_field.py"
_TAGS = ("honesty", "critical", "165e")


def _m(n, description, path, anchor, replacement, keyword) -> Mutation:
    return Mutation(
        id=f"M1230-{n}",
        phase=1230,
        description=description,
        path=path,
        anchor=anchor,
        replacement=replacement,
        target=_T,
        keyword=keyword,
        tags=_TAGS,
    )


MUTATIONS: tuple[Mutation, ...] = (
    _m(
        "01",
        "a page both readers found nothing on is still 'not read into fields'",
        APP / "datasheets.py",
        "outcomes[page] = page_ledger.no_fact(ai_run, page, reason, dropped)\n",
        'outcomes[page] = ("no_facts", 0, reason)\n',
        "is_read_not_unread or no_longer_called_unread",
    ),
    _m(
        "02",
        "any page the AI reader was asked about counts as read, even one it failed on or was refused on",
        _L,
        "    if ai_run is not None and read_page_empty(ai_run, page):\n",
        "    if ai_run is not None:\n",
        "failed_on or proposed_something_refused",
    ),
    _m(
        "03",
        "a page with a recorded reason for having no AI reading counts as empty",
        _L,
        '        and page not in (ai_run.get("reasons") or {})\n',
        "",
        "recorded_reason",
    ),
    _m(
        "04",
        "a page the AI read only in part counts as empty",
        _L,
        '        and page not in (ai_run.get("partly_read") or {})\n',
        "",
        "recorded_reason",
    ),
    _m(
        "05",
        "a refused proposal does not stop a page counting as empty",
        _L,
        '        and not any(\n            out.get(k)\n            for k in (\n                "error",\n                "accepted",\n                "rejected",\n                "counts",\n',
        '        and not any(\n            out.get(k)\n            for k in (\n                "error",\n                "accepted",\n',
        "clean_empty_reading",
    ),
    _m(
        "06",
        "the coverage never lists the pages read with no field",
        _L,
        '        "pages_read_no_field": no_field,\n',
        '        "pages_read_no_field": [],\n',
        "is_read_not_unread",
    ),
    _m(
        "07",
        "the rationale says fields were read from every page even when a page held none",
        _L,
        '    if not none:\n        return f"fields were read from every page ({where} of {total})"\n',
        '    if True:\n        return f"fields were read from every page ({where} of {total})"\n',
        "never_says_fields_were_read",
    ),
    _m(
        "08",
        "the whole-page reader's refusal beside a clean form page is lost, so the page counts as empty",
        APP / "form_reader_run.py",
        '        mine["merge_rejected"] = extra.get("rejected") or []\n        mine["merge_counts"] = extra.get("counts") or {}\n',
        '        mine["merge_rejected"] = []\n        mine["merge_counts"] = {}\n',
        "whole_page_refusal",
    ),
    _m(
        "09",
        "a sheet where no page gave a field counts its pages as read",
        _L,
        "            why = _not_clean(r) if fact_pages else NO_FIELD_ANYWHERE\n",
        "            why = _not_clean(r)\n",
        "no_page_gave_a_field",
    ),
    _m(
        "10",
        "a page whose text layer failed counts as read",
        _L,
        '    if row["ocr_status"] in ("pending", "failed") or row["native_status"] == "empty":\n',
        "    if False:\n",
        "text_layer_was_not_usable",
    ),
    _m(
        "11",
        "a page the picture reader could not be asked about counts as read",
        _L,
        '        "unavailable" in reason\n',
        '        "no such words" in reason\n',
        "picture_reader_could_not",
    ),
    _m(
        "12",
        "the readiness strip omits the pages read with no field",
        _L,
        '        "pages_read_no_field": cov.get("pages_read_no_field") or [],\n',
        '        "pages_read_no_field": [],\n',
        "readiness_strip_names",
    ),
)
