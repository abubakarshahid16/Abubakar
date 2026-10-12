"""Mutations of OCR routing, merge and per-page failure (audit F6/F7).

`backend/app/ocr.py`, the routing decision in `backend/app/extract.py`, and the
one-line homes of the same claims in `page_ledger.py`, `chunker.py` and
`db.py`. Tests: `backend/tests/test_ocr_routing.py`. Ids M1250-M1264.
"""

from __future__ import annotations

from ._base import APP, TESTS, Mutation

_T = str(TESTS / "test_ocr_routing.py")
_PHASE = 125

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1250", phase=_PHASE,
        description="F6 undone: an image-dominant page with a thin text layer "
                    "is never routed (back to the count-only rule)",
        path=APP / "ocr.py",
        anchor='    if thin:\n        return Route(True, "image_dominant"',
        replacement='    if False:\n        return Route(True, "image_dominant"',
        target=_T,
        keyword="stamped_scan_in_a_stored or digital_header_and_stamp_is_routed "
                "or records_the_decision_and_its_reason",
        tags=("critical",),
    ),
    Mutation(
        id="M1251", phase=_PHASE,
        description="drop the image-coverage gate, so every page with a sparse "
                    "text/image ratio - i.e. every text page - is OCR'd",
        path=APP / "ocr.py",
        anchor="    if coverage < s.ocr_image_coverage_min:\n",
        replacement="    if False:\n",
        target=_T,
        keyword="normal_dense_text_page_is_not_routed",
        tags=("critical",),
    ),
    Mutation(
        id="M1252", phase=_PHASE,
        description="ignore text density: a scan that already has a dense OCR "
                    "text layer is recognised again",
        path=APP / "ocr.py",
        anchor="    thin = density < s.ocr_max_text_density or ratio < s.ocr_max_text_to_image_area\n",
        replacement="    thin = True\n",
        target=_T,
        keyword="already_carries_an_ocr_text_layer or records_the_decision_and_its_reason",
    ),
    Mutation(
        id="M1253", phase=_PHASE,
        description="extraction ignores route_page and uses the old 100-char floor",
        path=APP / "extract.py",
        anchor="out.append((pno + 1, text, route.needs_ocr, eq_heavy, route.reason,",
        replacement="out.append((pno + 1, text, len(text.strip()) < 100, eq_heavy, route.reason,",
        target=_T,
        keyword="records_the_decision_and_its_reason",
        tags=("critical",),
    ),
    Mutation(
        id="M1254", phase=_PHASE,
        description="the routing reason is not stored on the page",
        path=APP / "extract.py",
        anchor="        reason = rest[0] if len(rest) > 0 else None\n",
        replacement="        reason = None\n",
        target=_T,
        keyword="records_the_decision_and_its_reason",
    ),
    Mutation(
        id="M1255", phase=_PHASE,
        description="merge stops de-duplicating: header/stamp appear twice",
        path=APP / "ocr.py",
        anchor="        if f\" {n} \" in haystack:\n            continue\n"
               "        if _near_duplicate(n, y, placed, window):\n"
               "            continue\n",
        replacement="",
        target=_T,
        keyword="merge_keeps_the_text_layer or merged_with_its_text_layer "
                "or adds_nothing_leaves",
    ),
    Mutation(
        id="M1256", phase=_PHASE,
        description="merge drops the text layer (OCR text replaces it)",
        path=APP / "ocr.py",
        anchor="    items = [(y, x, t) for y, x, t in native if t.strip()] + added\n",
        replacement="    items = list(added)\n",
        target=_T,
        keyword="merge_keeps_the_text_layer or merged_with_its_text_layer",
    ),
    Mutation(
        id="M1257", phase=_PHASE,
        description="F7 undone: a page whose recognition raised is skipped, "
                    "stays pending, and fails the document",
        path=APP / "ocr.py",
        anchor="        if err is not None:\n            failed += 1\n",
        replacement="        if err is not None:\n            continue\n",
        target=_T,
        keyword="fails_the_page_not_the_document",
        tags=("critical",),
    ),
    Mutation(
        id="M1258", phase=_PHASE,
        description="the ledger reports a failed page as done",
        path=APP / "page_ledger.py",
        anchor='            ocr_status, ocr_reason = "failed", f"recognition failed: {o[\'error\']}"',
        replacement='            ocr_status = "done"',
        target=_T,
        keyword="fails_the_page_not_the_document",
    ),
    Mutation(
        id="M1259", phase=_PHASE,
        description="chunker's ocr_failed exclusion rule is dead code again",
        path=APP / "chunker.py",
        anchor='                       "error": r["error"]}',
        replacement='                       "error": None}',
        target=_T,
        keyword="fails_the_page_not_the_document",
    ),
    Mutation(
        id="M1260", phase=_PHASE,
        description="pages_with_text is cumulative again",
        path=APP / "ocr.py",
        anchor='        "pages_with_text": with_text,\n',
        replacement='        "pages_with_text": recognised,\n',
        target=_T,
        keyword="counts_this_round_only",
    ),
    Mutation(
        id="M1261", phase=_PHASE,
        description="re-route never requeues a finished document with new OCR pages",
        path=APP / "extract.py",
        anchor='    requeue = newly_pending > 0 and doc["status"] in _REROUTE_RESUMABLE\n',
        replacement="    requeue = False\n",
        target=_T,
        keyword="stamped_scan_in_a_stored",
    ),
    Mutation(
        id="M1262", phase=_PHASE,
        description="the estimate (apply=False) writes the live decision",
        path=APP / "extract.py",
        anchor="    if not apply:\n        return result\n",
        replacement="",
        target=_T,
        keyword="stamped_scan_in_a_stored",
    ),
    Mutation(
        id="M1263", phase=_PHASE,
        description="migration does not add page_ocr.error to an older database",
        path=APP / "db.py",
        anchor='    add_column_if_missing(conn, "page_ocr", "error", "TEXT")\n',
        replacement="",
        target=_T,
        keyword="older_database_gains",
    ),
    Mutation(
        id="M1264", phase=_PHASE,
        description="image area is a plain sum: stacked images over-count coverage",
        path=APP / "ocr.py",
        anchor="    if len(rects) > _UNION_EXACT_MAX:\n",
        replacement="    if True:\n",
        target=_T,
        keyword="not_counted_twice",
    ),
)
