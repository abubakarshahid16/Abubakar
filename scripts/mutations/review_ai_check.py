"""Owner order 2d: the AI engineering check (kind C) and its CRS column."""
from __future__ import annotations

from ._base import APP, FRONTEND_SRC, Mutation

_T = "tests/test_review_ai_check.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M1026", phase=86, description="a datasheet value not on the cited page is kept",
             path=APP / "ai_engineering_check.py",
             anchor="    if value and not numparse.value_in_text(value, page_text):\n",
             replacement="    if False:\n",
             target=_T, keyword="refuses_with_a_named_reason and value_not_on_page",
             tags=("honesty", "critical")),
    Mutation(id="M1027", phase=86, description="a number from memory (not on the page) is kept",
             path=APP / "ai_engineering_check.py",
             anchor="    if not _numbers(stripped) <= _numbers(page_text):\n",
             replacement="    if False:\n",
             target=_T, keyword="refuses_with_a_named_reason and number_not_on_page",
             tags=("honesty", "critical")),
    Mutation(id="M1028", phase=86, description="a clause the check cannot verify is kept",
             path=APP / "ai_engineering_check.py",
             anchor="    if (item.get(\"clause\") and verified is None) or (refs and (verified is None\n",
             replacement="    if False and (item.get(\"clause\") and verified is None) or False and (refs and (verified is None\n",
             target=_T, keyword="refuses_with_a_named_reason and clause_not_verified",
             tags=("honesty", "critical")),
    Mutation(id="M1029", phase=86, description="a pass/fail word is kept in a draft",
             path=APP / "ai_engineering_check.py",
             anchor="    if any(_contains(folded, word) for word in PASS_FAIL_WORDS):\n",
             replacement="    if False:\n",
             target=_T, keyword="refuses_with_a_named_reason and pass_fail_word or never_move_the_code",
             tags=("honesty", "critical")),
    Mutation(id="M1030", phase=86, description="a 'high' confidence is kept",
             path=APP / "ai_engineering_check.py",
             anchor='    if item.get("confidence") not in CONFIDENCES:\n',
             replacement="    if False:\n",
             target=_T, keyword="refuses_with_a_named_reason and confidence",
             tags=("honesty",)),
    Mutation(id="M1035", phase=86, description="a quoted sentence not on the datasheet page is kept",
             path=APP / "ai_engineering_check.py",
             anchor="        if len(quoted.split()) >= 5 and _fold(quoted) not in _fold(pages[page]):\n",
             replacement="        if False:\n",
             target=_T, keyword="refuses_with_a_named_reason and quote_not_on_page",
             tags=("honesty", "critical")),
    Mutation(id="M1036", phase=86, description="a rerun deletes an engineer's confirmed item",
             path=APP / "ai_engineering_check.py",
             # Re-anchored 2026-09-30 (audit): any engineer decision is kept.
             anchor='                     f" AND {review_mod.UNDECIDED_SQL}", (review_run_id, ORIGIN))\n',
             replacement='                     "", (review_run_id, ORIGIN))\n',
             target=_T, keyword="never_an_engineers_confirmation", tags=("honesty",)),
    Mutation(id="M1033", phase=86, description="the review job drafts with the flag off",
             path=APP / "ai_engineering_check.py",
             anchor="    if not settings.review_ai_check_enabled:\n        return False,",
             replacement="    if False:\n        return False,",
             target=_T, keyword="off_by_default_and_off_sends_nothing", tags=("privacy", "critical")),
    Mutation(id="M1037", phase=86, description="the route runs with the flag or Claude lane off",
             path=APP / "claude_api.py",
             anchor="    ok, why = ai_engineering_check.available()\n    if not ok:\n",
             replacement="    ok, why = ai_engineering_check.available()\n    if False:\n",
             target=_T, keyword="409_when_off", tags=("privacy",)),
    Mutation(id="M1031", phase=86, description="the contractor's copy keeps unconfirmed AI rows",
             path=APP / "crs_export.py",
             # Re-anchored 2026-09-27 (CRS quick wins): the issue-copy filter
             # now also requires engineer confirmation (M1305 removes that half).
             anchor=('        findings = [f for f in findings\n'
                     '                    if not str(f.get("ai_review_comment") or "").strip()\n'
                     '                    and f.get("engineer_confirmed") is True]\n'),
             replacement="        pass\n",
             target=_T, keyword="issue_copy_carries_no_ai_column", tags=("honesty", "critical")),
    Mutation(id="M1032", phase=86, description="an unconfirmed AI item is printed in COMPANY Comments",
             path=APP / "crs_mapping.py",
             anchor='            "comment": text if confirmed else "",\n',
             replacement='            "comment": text,\n',
             target=_T, keyword="only_in_the_ai_column", tags=("honesty", "critical")),
    Mutation(id="M1034", phase=86,
             description="confirmation does not name the engineer on the CRS "
                         "(re-anchored 2026-09-27: `confirmed_by_prefix` now "
                         "covers both kind C and kind D)",
             path=APP / "crs_mapping.py",
             anchor="            \"comment_by\": (f\"{confirmed_by_prefix}{f.get('confirmed_by_name') or f['confirmed_by']}\"\n"
                    "                           if confirmed else unconfirmed_by),\n",
             replacement="            \"comment_by\": (\"AI Review\"\n"
                        "                           if confirmed else unconfirmed_by),\n",
             target=_T, keyword="under_the_engineers_name", tags=("honesty",)),
    Mutation(id="M1038", phase=86, description="a rejected AI item stays on the sheet",
             path=APP / "crs_mapping.py",
             # Re-anchored 2026-10-01 (audit entry 90). The old anchor was the
             # inner per-origin check, which is redundant: `build_crs_rows`
             # already drops every rejected finding at its top. A rejection is
             # therefore guarded in TWO places, and removing either one alone is
             # (correctly) invisible. This mutation removes the rejection from
             # the findings before BOTH places see them - the feature "a
             # rejected item stays off the sheet" is then truly gone.
             anchor="    findings = [f for f in findings if not _rejected(f)]\n",
             replacement=("    findings = [{**f, \"approval_status\": None} if _rejected(f) else f\n"
                          "                for f in findings]\n"),
             target=_T, keyword="rejected_item_is_not_on_the_sheet", tags=("honesty",)),
    Mutation(id="M1132", phase=95,
             description="honesty: an unconfirmed AI/web item's Comment By "
                         "goes back to blank instead of naming it a draft",
             path=APP / "crs_mapping.py",
             anchor="            \"comment_by\": (f\"{confirmed_by_prefix}{f.get('confirmed_by_name') or f['confirmed_by']}\"\n"
                    "                           if confirmed else unconfirmed_by),\n",
             replacement="            \"comment_by\": (f\"{confirmed_by_prefix}{f.get('confirmed_by_name') or f['confirmed_by']}\"\n"
                        "                           if confirmed else \"\"),\n",
             target=_T, keyword="comment_by_is_never_blank",
             tags=("honesty", "critical")),
    Mutation(id="M1039", phase=86, runner="vitest",
             description="an AI engineering check item reads as a status, not as a draft",
             path=FRONTEND_SRC / "components/review/reviewFormat.ts",
             anchor="  if (finding.origin === AI_ENGINEERING_CHECK) return AI_ENGINEERING_CHECK_LABEL;\n",
             replacement="",
             target="src/components/review/reviewFormat.test.ts",
             keyword="AI engineering check item", tags=("honesty", "ui")),
    Mutation(id="M1040", phase=86, description="a number is laundered through the item's own standard name",
             path=APP / "ai_engineering_check.py",
             anchor="    names = [*cited, *held]\n",
             replacement='    names = [*cited, *held, item.get("relates_to") or ""]\n',
             target=_T, keyword="refuses_with_a_named_reason and number_not_on_page",
             tags=("honesty",)),

    # ---------------------------------------------------------- 2026-09-27
    # Every historical `review_ai_check` call hit the 4000-token output cap
    # (finish_reason == "length") and was thrown away whole - zero rows ever
    # stored. M1118-M1121: a truncated reply keeps its complete items, a
    # capped retry covers what is missing, the same gate applies to a
    # retry's items too, and the outcome is always recorded on the run.
    Mutation(id="M1118", phase=94,
             description="a truncated reply's complete items are thrown away, not kept",
             path=APP / "ai_engineering_check.py",
             anchor="            items = parse_partial(response.text)\n",
             replacement="            items = []\n",
             target=_T, keyword="parse_partial or truncated_reply_is_completed or retry_is_capped",
             tags=("honesty", "critical")),
    Mutation(id="M1119", phase=94,
             description="a truncated reply is never retried, even once",
             path=APP / "ai_engineering_check.py",
             anchor="            covered = _covered_lines(all_kept)\n            continue  # eligible for the retry, if one is left\n",
             replacement="            covered = _covered_lines(all_kept)\n            break\n",
             target=_T, keyword="truncated_reply_is_completed or retry_is_capped",
             tags=("critical",)),
    Mutation(id="M1120", phase=94,
             description="the retry cap is not enforced - MAX_CALLS grows without bound",
             path=APP / "ai_engineering_check.py",
             anchor="MAX_CALLS = 2",
             replacement="MAX_CALLS = 99",
             target=_T, keyword="retry_is_capped",
             tags=("critical",)),
    Mutation(id="M1121", phase=94,
             description="an item recovered from a retry skips the acceptance gate",
             path=APP / "ai_engineering_check.py",
             anchor="    for item in items[:MAX_ITEMS]:\n        gate = accept(item, pages, held, cited)\n        if gate[\"accepted\"]:\n            all_kept.append(item)\n        else:\n            rejected[gate[\"reason\"]] = rejected.get(gate[\"reason\"], 0) + 1\n",
             replacement="    all_kept.extend(items[:MAX_ITEMS])\n",
             target=_T, keyword="accept_still_gates_items_recovered_from_a_retry",
             tags=("honesty", "critical")),
    Mutation(id="M1122", phase=94,
             description="an incomplete AI check is never recorded on the run - silent again",
             path=APP / "ai_engineering_check.py",
             anchor="    status[\"plain\"] = _plain_status(status)\n    _store_status(review_run_id, status)\n",
             replacement="    status[\"plain\"] = _plain_status(status)\n",
             target=_T, keyword="retry_is_capped or truncated_reply_is_completed",
             tags=("honesty", "critical")),
)
