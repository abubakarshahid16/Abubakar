"""Mutations of the reopen-time permission filter in `backend/app/chat.py` - B9."""

from __future__ import annotations

from ._base import APP, FRONTEND_SRC, Mutation

_C = APP / "chat.py"
_T = "tests/test_b9_reopen_permissions.py"
_CHAT = FRONTEND_SRC / "components" / "chat"
_V = "src/components/chat/answerVerdict.test.tsx"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M829", phase=72, description="B9: a turn citing a revoked document reopens unredacted",
             path=_C, anchor="            message = _withhold(message)\n", replacement="            pass\n",
             target=_T, keyword="revoked_grant_withholds", tags=("privacy",)),
    Mutation(id="M830", phase=72, description="B9: withholding keeps the payload that holds the passage",
             path=_C, anchor='        "payload": {"withheld": True},\n', replacement="",
             target=_T, keyword="revoked_grant_withholds", tags=("privacy",)),
    Mutation(id="M831", phase=72, description="B9: withholding keeps the answer prose that quotes the passage",
             path=_C, anchor='        "text": WITHHELD_TEXT,\n', replacement="",
             target=_T, keyword="revoked_grant_withholds", tags=("privacy",)),
    Mutation(id="M832", phase=72, description="B9: document ids nested below the top level are not seen",
             path=_C, anchor="                found |= referenced_document_ids(item)\n", replacement="                pass\n",
             target=_T, keyword="any_depth", tags=("privacy",)),
    Mutation(id="M833", phase=72, description="B9: scope_ids lists are not treated as document references",
             path=_C, anchor='_ID_LIST_KEYS = frozenset({"scope_ids", "document_ids"})\n',
             replacement='_ID_LIST_KEYS = frozenset({"document_ids"})\n',
             target=_T, keyword="any_depth", tags=("privacy",)),
    Mutation(id="M834", phase=72, description="B9: every assistant turn is withheld, readable ones too",
             path=_C, anchor="                and referenced_document_ids(message[\"payload\"]) - allowed_document_ids):\n",
             replacement="                and True):\n",
             target=_T, keyword="revoked_grant_withholds or before_revocation"),
    Mutation(id="M835", phase=72, description="B9: the route stops passing the caller's scope",
             path=APP / "main.py",
             anchor="        conversation_id, allowed_document_ids=scope.allowed_document_ids)}\n",
             replacement=("        conversation_id, allowed_document_ids=frozenset(\n"
                          "            r[0] for r in connect().execute('SELECT id FROM documents')))}\n"),
             target=_T, keyword="revoked_grant_withholds", tags=("privacy",)),
    Mutation(id="M836", phase=72, runner="vitest", description="B9: the verdict warning is never rendered",
             path=_CHAT / "AnswerCardView.tsx",
             anchor='      {verdict && view.answer_type !== "insufficient_evidence" && <VerdictNotice',
             replacement='      {false && verdict && <VerdictNotice', target=_V, keyword="conflicting evidence", tags=("honesty", "ui")),
    Mutation(id="M837", phase=72, runner="vitest", description="B9: an insufficient verdict on an extract is not shown",
             path=_CHAT / "AnswerVerdict.tsx", anchor='  if (verdict === "supported") return null;',
             replacement='  if (verdict === "supported" || verdict === "insufficient_evidence") return null;',
             target=_V, keyword="gate called insufficient", tags=("honesty", "ui")),
    Mutation(id="M838", phase=72, runner="vitest", description="B9: the refusal no longer says it cannot determine the answer",
             path=_CHAT / "AnswerInsufficient.tsx", anchor=">{NOT_DETERMINED}</p>",
             replacement=">The documents do not answer this</p>", target=_V, keyword="evidence is insufficient", tags=("honesty", "ui")),
    Mutation(id="M839", phase=72, runner="vitest", description="B9: the verdict is dropped when a conversation is reopened",
             path=_CHAT / "AnswerCardContent.tsx", anchor="    answerability: p.answerability ?? null,\n",
             replacement="    answerability: null,\n", target=_V, keyword="carries the verdict", tags=("honesty", "ui")),
    Mutation(id="M840", phase=72, runner="vitest", description="B9: the scope the question was narrowed to is not shown",
             path=_CHAT / "AnswerVerdict.tsx", anchor="      {scoped && <p>Searched: {scoped}</p>}\n",
             replacement="", target=_V, keyword="scope reason", tags=("ui",)),
    Mutation(id="M841", phase=72, runner="vitest", description="B9: a withheld turn renders as an ordinary answer",
             path=_CHAT / "AnswerCardView.tsx", anchor="  if (view.withheld) return <WithheldNotice text={view.answer} />;\n",
             replacement="", target=_V, keyword="withheld turn", tags=("privacy", "ui")),
    Mutation(id="M842", phase=72, runner="vitest", description="B9: the verdict evidence loses its page and clause",
             path=_CHAT / "AnswerVerdict.tsx", anchor="  if (ref.section) parts.push(ref.section);\n",
             replacement="", target=_V, keyword="conflicting evidence", tags=("citation", "ui")),
    Mutation(id="M843", phase=72, description="B9: a follow-up carries the clause of an answer from a revoked document",
             path=APP / "understanding.py",
             anchor="    if context.document_id is not None and context.document_id not in allowed_document_ids:\n        context = PriorContext()\n",
             replacement="", target="tests/test_b6c_understanding.py", keyword="revoked_document_carries_nothing",
             tags=("privacy",)),
)
