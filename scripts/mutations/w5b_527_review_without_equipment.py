"""#527: a review runs on a written document with no equipment type. Ids M5601-M5610."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_w5b_527_review_without_equipment.py"
_A = APP / "applicability.py"
_P = APP / "playbooks.py"
_TAG = ("w5b", "honesty")


def _m(i, desc, anchor, repl, kw=None, path=_A):
    return Mutation(id=f"M{i}", phase=i, description=desc, path=path, anchor=anchor,
                    replacement=repl, target=_T, keyword=kw, tags=_TAG)


MUTATIONS: tuple[Mutation, ...] = (
    _m(5601, "the playbook's standards are never offered to selection",
       "        mandatory,\n        _match_attribute(", "        _match_attribute(",
       "gets_the_playbook_standard or draft_playbook"),
    _m(5602, "a draft playbook's standard is included",
       '        method = METHOD_PLAYBOOK if pb.signed_off else "playbook_draft"',
       "        method = METHOD_PLAYBOOK", "draft_playbook"),
    _m(5603, "a signed-off playbook's standard is not included",
       '    "playbook",  # signed-off', '    # signed-off', "gets_the_playbook_standard"),
    _m(5604, "a playbook of another kind is used",
       "        if pb.document_kind != kind or not playbooks.applies_to(pb, text):",
       "        if not playbooks.applies_to(pb, text):", "another_kind"),
    _m(5605, "every procedure gets every procedure playbook (no text cue)",
       "        if pb.document_kind != kind or not playbooks.applies_to(pb, text):",
       "        if pb.document_kind != kind:", "about_something_else"),
    _m(5606, "an undecided kind is used",
       '    if not kind or state not in ("confirmed", "suggested"):', "    if not kind:",
       "could_not_decide"),
    _m(5607, "a suggested kind is not called a guess",
       '    guess = "" if state == "confirmed" else " (document kind suggested, not confirmed)"',
       '    guess = ""', "suggested_kind"),
    _m(5608, "a mandatory standard not held is dropped",
       "                missing.append({\"identifier\": identifier,", "                (lambda *_: None)({\"identifier\": identifier,",
       "not_held"),
    _m(5609, "mandatory gaps already reported as citations are reported twice",
       "            if standard_ids.key(m[\"identifier\"]) not in {standard_ids.key(x[\"identifier\"]) for x in missing}],",
       "            ],", "reported_once"),
    _m(5610, "a playbook with no cues applies to everything",
       "    return bool(pb.applies_when) and bool(_hits(pb.applies_when, text))",
       "    return not pb.applies_when or bool(_hits(pb.applies_when, text))", "applies_to", path=_P),
)
