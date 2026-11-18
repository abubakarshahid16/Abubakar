# REVIEW.md

Read before every review and before every push. The owner's standing order (17 Nov 2026): every repeated mistake becomes one line
in "Rules learned" below. Older called-out mistakes: `docs/claude-md-detail.md`, section "Mistakes not to repeat".

## Rules learned

- A word list run on the AI's own wording cannot prove that a comment states ONLY a pass: every list of pass, contrast and
  request words let a real conflict through in another phrasing ("acceptable for sweet service, and this line is sour").
  Keep such a code rule to marks the judge itself gave ("confirm"), and put the rest to the judge prompt, measured by a
  score. (18 Nov 2026: three review rounds on the pass-word rule; dropped.)
- Never put a real client identifier (document number, project, company or person name) or any document text into code, tests,
  commits, PR text, branch names or briefs to helpers: use invented values. The commit hook scans every commit against the local,
  git-ignored list `.githooks/client-identifiers.local`; a missing list means NO scan, so keep it present. (17 Nov 2026: real
  identifiers reached a branch through a brief that quoted a reviewer's examples.)
- Read the clock (`TZ=Asia/Karachi date`) before writing any time in a report, the live file or a log. (17 Nov 2026: times were
  written ahead of the clock and had to be corrected.)
- Check that every lane is moving, not only the one in hand: list all lanes with their state at every report. (17 Nov 2026.)
- After three review rounds on the same change, stop and rethink the approach instead of patching again. (17 Nov 2026: three rounds
  of shape rules for search names each leaked a new shape; the rethink sent only names from the app's own tables.)
- Decide by what is correct and safe, never by which old tests would break; update old tests honestly, one assertion each, with
  the reason. (17 Nov 2026, owner.)
- A builder's scratch files are named with its own prefix; never share a fixed name such as `pr_body.md` or `revert_check.py`
  between parallel helpers. (17 Nov 2026: one helper overwrote another's file.)
- Never commit with a failing test, even locally; run the touched tests after every edit, and check an edit actually applied.
  (17 Nov 2026.)
