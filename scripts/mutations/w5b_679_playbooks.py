"""#679 "HAZOP and SIL procedure playbooks": each entry deletes one part;
backend/tests/test_w5b_679_playbooks.py must notice."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_w5b_679_playbooks.py"
_TAG = ("w5b_679", "playbooks")
P = "playbooks.py"
DATA = APP / "reference" / "playbooks"


def _m(i, desc, path, anchor, repl, kw=None):
    return Mutation(id=f"M{i}", phase=i, description=desc, path=path,
                    anchor=anchor, replacement=repl, target=_T, keyword=kw, tags=_TAG)


MUTATIONS: tuple[Mutation, ...] = (
    _m(4701, "a check without a clause citation is accepted", APP / P,
       '        if not str(source.get("standard") or "").strip() or not str(source.get("clause") or "").strip():\n',
       "        if False:\n", "without_a_clause_citation"),
    _m(4702, "two elements may share an id", APP / P, "        if not eid or eid in seen:\n",
       "        if not eid:\n", "unusable_playbook"),
    _m(4703, "an element with no evidence cues is accepted", APP / P, "        if not groups:\n", "        if False:\n",
       "unusable_playbook"),
    _m(4704, "an evidence group with no phrases is accepted", APP / P,
       '            if not phrases or not str((g or {}).get("label") or "").strip():\n',
       "            if False:\n", "unusable_playbook"),
    _m(4705, "a signed-off playbook need not say who signed it", APP / P,
       '    if status == "signed_off" and not (', '    if False and not (', "unusable_playbook"),
    _m(4706, "a broken playbook file is dropped silently", APP / P,
       '            broken.append({"file": path.name, "reason": str(exc)})\n', "            pass\n",
       "broken_playbook_file"),
    _m(4707, "a draft playbook carries no draft notice", APP / P, "    if pb.signed_off:\n        return None\n",
       "    if True:\n        return None\n", "drafts"),
    _m(4708, "a cue matches inside a longer word (start)", APP / P, 'return re.compile(r"(?<![a-z0-9])" + ',
       'return re.compile(r"" + ', "cues_match_whole_words"),
    _m(4709, "a cue matches inside a longer word (end)", APP / P, '+ r"(?![a-z0-9])")', '+ r"")',
       "cues_match_whole_words"),
    _m(4710, "a trailing * is not a wildcard", APP / P,
       'parts.append(re.escape(w) + (r"[a-z0-9]*" if stem else ""))', 'parts.append(re.escape(w) + "")',
       "cues_match_whole_words"),
    _m(4712, "an empty quote is accepted as verified", APP / P, "    return bool(q) and q in ", "    return q in ",
       "quote_is_checked"),
    _m(4713, "every standard is held", APP / P, "    return find_standard(library, identifier) is not None\n",
       "    return True\n", "not_held or held_standard_is_matched"),
    _m(4714, "an element of a standard that is not held is judged anyway", APP / P,
       "        if not held:\n            entry[\"state\"] = STANDARD_NOT_HELD", "        if False:\n            entry[\"state\"] = STANDARD_NOT_HELD",
       "never_met"),
    _m(4715, "the pointer for the engineer is not given", APP / P,
       '            entry["found_at"] = [e["locator"] for e in found["evidence"][:3]]\n', '            entry["found_at"] = []\n',
       "never_met"),
    _m(4716, "a document not read in full can have a missing element", APP / P,
       "            elif not read_in_full:\n", "            elif False:\n", "cannot_be_called_missing"),
    _m(4718, "a document still being processed counts as read", APP / P, '    if doc["status"] != "ready":\n',
       "    if False:\n", "cannot_be_called_missing"),
    _m(4719, "pages that need recognition are ignored", APP / P, "    if unread:\n        return False,",
       "    if False:\n        return False,", "pages_that_were_not_read"),
    _m(4720, "absence is worded as a statement about the author", APP / P,
       'reason="not found in the pages read"', 'reason="the document does not mention it"', "not_found_in_the_pages_read"),
    _m(4721, "one cue group is enough for present", APP / P,
       'complete = [e for e in evidence if len(e["groups"]) == all_groups and e["in_text"]',
       'complete = [e for e in evidence if e["in_text"]', "part_of_an_element_is_unclear"),
    _m(4722, "a heading counts as the passage's own text", APP / P, "    if heading and text.startswith(heading):\n",
       "    if False:\n", "heading_path_alone"),
    _m(4723, "footers, tracked changes and comments count as the body", APP / P,
       '    body = [c for c in chunks if c["kind"] in BODY_KINDS and c["retrievable"]]\n', "    body = list(chunks)\n",
       "footer_or_a_deleted_run"),
    _m(4724, "a proposed quote is kept without being checked", APP / P,
       '                    if c is not None and quote_in(p.get("quote", ""), c["text"]):\n',
       "                    if c is not None:\n", "fabricated_quote"),
    _m(4725, "rejected proposals are not counted", APP / P, '                        ai["rejected"] += 1\n',
       "                        pass\n", "fabricated_quote"),
    _m(4726, "the task's own check lets an invented quote through", APP / P,
       '        return [] if quote_in(data.get("quote", ""), passage) else ["the quote is not in that passage"]\n',
       "        return []\n", "invents_a_quote"),
    _m(4727, "an unknown playbook is not refused", APP / "main.py", "    if playbook is None:\n        raise HTTPException(status_code=422",
       "    if False:\n        raise HTTPException(status_code=422", "refuses_an_unknown_playbook"),
    _m(4728, "a caller who may not read the document can review it", APP / "main.py",
       "    require_document(document_id, scope)\n    found, _broken = playbooks_mod.available()",
       "    found, _broken = playbooks_mod.available()", "may_not_read"),
    _m(4729, "the route never uses the model, or always does", APP / "main.py",
       "    proposer = playbooks_mod.task_proposer() if body.use_ai else None\n", "    proposer = None\n",
       "local_model_only_when_asked"),
    _m(4730, "a shipped playbook is marked signed off", DATA / "hazop_procedure.json", '"status": "draft"',
       '"status": "signed_off"', "shipped_playbooks"),
    _m(4731, "a shipped HAZOP check loses its clause", DATA / "hazop_procedure.json", '"clause": "6.3"', '"clause": ""',
       "shipped_playbooks"),
    _m(4732, "a shipped SIL check loses its clause", DATA / "sil_procedure.json", '"clause": "11.9"', '"clause": ""',
       "shipped_playbooks"),
)
