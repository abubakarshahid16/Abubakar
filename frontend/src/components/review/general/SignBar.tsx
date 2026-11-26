/**
 * The engineer's SIGN-OFF of a general review (order 14): above the comments, one bar that says where the review stands.
 *
 *   not signed   "N comments still need your decision": Accept the rest, the review code (the engineer's OWN choice of the four; nothing is
 *                preselected or proposed), an optional one-line statement, and Sign off (off until every comment is decided and a code chosen).
 *   signed       who, when, the code, the statement, and the points statement of the contractor copy; the contractor download.
 *   changed      a decision was made after the sign-off: no contractor download until the review is signed again.
 *
 * The server decides everything (what is undecided, whether the copy can be built clean); a refusal is shown in its own words with the
 * comments that stand in the way. Nothing is computed here.
 */
import { useState } from "react";

import { type GeneralReview, type SignoffRefusal, type SignoffStatus, downloadGeneralSheet, generalReview } from "../../../api/generalReview";
import { dayTimeWords } from "../workspace/landing/dateWords";
import { Button } from "../../kit/Kit";

export function SignBar({ review, signoff, onStatus, onChanged }: {
  review: GeneralReview; signoff: SignoffStatus; onStatus: (s: SignoffStatus) => void; onChanged: () => void;
}) {
  const [code, setCode] = useState("");
  const [statement, setStatement] = useState("");
  const [busy, setBusy] = useState(false);
  const [refusal, setRefusal] = useState<SignoffRefusal | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const todo = signoff.undecided_count;

  async function acceptRest() {
    setBusy(true); setProblem(null); setRefusal(null);
    const r = await generalReview.acceptRest(review.paper_document_id, review.run_id);
    setBusy(false);
    if (!r.ok) { setProblem(r.error.code === "unauthenticated" ? "Sign in to record decisions." : r.error.message); return; }
    onChanged(); // the server re-reads: the cards and the bar then show the accepted comments
  }

  async function sign() {
    setBusy(true); setProblem(null); setRefusal(null);
    const r = await generalReview.signOff(review.paper_document_id, { run_id: review.run_id, review_code: code, statement: statement.trim() || undefined });
    setBusy(false);
    if (!r.ok) {
      if (r.error.code === "unauthenticated") setProblem("Sign in to sign off this review.");
      else if (r.error.code === "super_user_only") setProblem(r.error.message);
      else setRefusal({ message: r.error.message, blockers: (r.error as unknown as { blockers?: SignoffRefusal["blockers"] }).blockers ?? [] });
      return;
    }
    onStatus(r.data.signoff);
  }

  async function download() {
    setProblem(null);
    const bad = await downloadGeneralSheet(review.paper_document_id, review.run_id, "contractor");
    if (bad) setProblem(bad);
  }

  const signed = signoff.signed;
  const controls = (
    <div className="space-y-2">
      {todo > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <p data-testid="sign-undecided" className="text-sm text-slateish-200">{todo} comment{todo === 1 ? "" : "s"} still need{todo === 1 ? "s" : ""} your decision.</p>
          {/* a rough draft from the local model is decided one by one: the server refuses a bulk accept, and none is offered */}
          {signoff.may_sign && signoff.bulk_accept !== false && <Button variant="secondary" size="sm" disabled={busy} onClick={() => void acceptRest()}>Accept the rest ({todo})</Button>}
          {signoff.rough_draft_words && <p data-testid="sign-rough-draft" className="text-sm text-pill-review-fg">{signoff.rough_draft_words}</p>}
        </div>
      )}
      {!signoff.may_sign && <p data-testid="sign-super-user" className="text-sm text-slateish-300">{signoff.may_sign_words ?? "Only a super user can sign this review for now."}</p>}
      {signoff.may_sign && <div className="flex flex-wrap items-end gap-2">
        <label className="text-xs text-slateish-400">Review code (your choice)
          <select value={code} onChange={(e) => setCode(e.target.value)} aria-label="Review code"
            className="mt-1 block rounded-[var(--radius-sm)] border border-ink-500 bg-ink-850 px-2 py-1 text-sm text-slateish-100">
            <option value="">Choose the review code</option>
            {signoff.codes.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </label>
        <label className="min-w-[14rem] flex-1 text-xs text-slateish-400">One line for the record (optional)
          <input value={statement} onChange={(e) => setStatement(e.target.value)} maxLength={300}
            className="mt-1 block w-full rounded-[var(--radius-sm)] border border-ink-500 bg-ink-850 px-2 py-1 text-sm text-slateish-100" />
        </label>
        <Button variant="primary" size="sm" disabled={busy || todo > 0 || !code} onClick={() => void sign()} data-testid="sign-button">
          {signoff.state === "changed" ? "Sign off again" : "Sign off"}
        </Button>
      </div>}
    </div>
  );

  return (
    <section data-testid="sign-bar" data-state={signoff.state} aria-label="Sign-off" className="space-y-3 rounded-[var(--radius-md)] border border-ink-600 bg-ink-800 p-4">
      {signoff.state === "signed" && signed && (
        <div className="space-y-1">
          <p data-testid="sign-signed" className="text-sm text-pill-pass-fg"><strong>Signed off</strong> by {signed.by}, {dayTimeWords(signed.at)}. Review code: {signed.code}.</p>
          {signed.rough_draft && <p data-testid="sign-made-from" className="text-sm text-pill-review-fg">Sign-off {signed.rough_draft}.</p>}
          {signed.statement && <p className="text-sm text-slateish-200">{signed.statement}</p>}
          <p data-testid="sign-copy-statement" className="text-xs text-slateish-300">Contractor copy: {signed.copy_statement}.</p>
          {signoff.may_sign && <Button variant="secondary" size="sm" onClick={() => void download()} data-testid="contractor-download">Download the contractor copy</Button>}
          {!signoff.may_sign && <p data-testid="sign-super-user" className="text-xs text-slateish-300">{signoff.may_sign_words}</p>}
        </div>
      )}
      {signoff.state === "changed" && signed && (
        <p data-testid="sign-changed" role="alert" className="text-sm text-pill-review-fg">
          <strong>Changed since sign-off.</strong> A decision was made after {signed.by} signed on {dayTimeWords(signed.at)}. There is no contractor copy until the review is signed again.
        </p>
      )}
      {signoff.state === "not_signed" && <p className="text-sm text-slateish-300">Not signed off. The contractor copy follows the engineer's sign-off, and holds only the comments you accept or edit.</p>}
      {signoff.state !== "signed" && controls}
      {refusal && (
        <div role="alert" data-testid="sign-refusal" className="space-y-1 text-sm text-danger-500">
          <p>{refusal.message}</p>
          {refusal.blockers.length > 0 && <ul className="list-disc pl-5">{refusal.blockers.map((b, i) => <li key={i}>{b.part === "file" ? "" : `${b.part} ${b.n}`}{b.title ? `: ${b.title}` : ""}{b.why ? `: ${b.why}` : ""}</li>)}</ul>}
        </div>
      )}
      {problem && <p role="alert" data-testid="sign-problem" className="text-sm text-danger-500">{problem}</p>}
    </section>
  );
}
