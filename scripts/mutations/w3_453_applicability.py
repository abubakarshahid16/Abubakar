"""#453 "a requirement about a different kind of equipment is not a check":
each entry deletes one part; backend/tests/test_w3_453_applicability_by_subject.py
must notice."""
from __future__ import annotations

from ._base import APP, FRONTEND_SRC, Mutation

_T = "tests/test_w3_453_applicability_by_subject.py"
_TAG = ("w3_453", "honesty")


def _m(i, desc, path, anchor, repl, kw=None):
    return Mutation(id=f"M{i}", phase=i, description=desc, path=APP / path,
                    anchor=anchor, replacement=repl, target=_T, keyword=kw, tags=_TAG)


MUTATIONS: tuple[Mutation, ...] = (
    _m(3101, "the review checks every requirement again (the subject gate is not applied)",
       "comparison.py", '    requirements = scoped["kept"]\n', "    requirements = requirements\n"),
    _m(3102, "a clause with a silent sentence no longer takes its subject from its heading",
       "subject_scope.py", "        found = vocab.equipment_in(section)\n", "        found = set()\n"),
    _m(3103, "everything a sentence mentions becomes its subject again",
       "subject_scope.py", "    own = vocab.equipment_in(text[:verb.start()] if verb else text)\n",
       "    own = vocab.equipment_in(text)\n"),
    _m(3104, "a component (flange, piping) can exclude a requirement",
       "subject_scope.py", "        return {t for t in self.types_in(text) if self.kind.get(t) == EQUIPMENT}\n",
       "        return set(self.types_in(text))\n"),
    _m(3105, "an unknown submittal equipment hides requirements",
       "subject_scope.py", "        elif not equipment:\n", "        elif False:\n"),
    _m(3106, "a subject that matches the submittal's equipment is not applied",
       "subject_scope.py", "        elif subject & equipment:\n", "        elif False:\n"),
    _m(3107, "requirements not applied are dropped silently (no grouped line)",
       "comparison.py", '    requirements_not_applied = scoped["not_applied"]\n',
       "    requirements_not_applied = []\n"),
    _m(3108, "an edited vocabulary file is not re-read",
       "subject_scope.py", "    return _load(str(target), target.stat().st_mtime)\n",
       "    return _load(str(target), 0.0)\n"),
    _m(3109, "a spelling listed under two types matches only the last one",
       "subject_scope.py", "                    self.phrases.setdefault(folded, set()).add(canonical)\n",
       "                    self.phrases[folded] = {canonical}\n"),
    _m(3110, "the submittal's title no longer names its equipment",
       "subject_scope.py", '        ("title", classification.get("title")),\n', '        ("title", None),\n'),
    _m(3111, "the submittal's classification no longer names its equipment",
       "subject_scope.py", '        ("classification", classification.get("equipment_type")),\n',
       '        ("classification", None),\n'),
    _m(3112, "a general requirement is dropped",
       "subject_scope.py", '            summary["checked_general"] += 1\n            kept.append(requirement)\n',
       '            summary["checked_general"] += 1\n'),
    Mutation(id="M3113", phase=3113, runner="vitest",
             description="the run screen no longer shows the requirements not applied",
             path=FRONTEND_SRC / "views" / "ReviewRunsView.tsx",
             anchor="{run && (run.requirements_not_applied?.length ?? 0) > 0 && (",
             replacement="{false && (",
             target="src/views/ReviewRunsView.test.tsx", keyword="requirements about a different kind of equipment",
             tags=_TAG),
)
