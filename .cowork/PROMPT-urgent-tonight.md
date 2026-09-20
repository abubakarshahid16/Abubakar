# URGENT, TONIGHT. Demo is tomorrow, on this laptop, with an unseen datasheet.

No corpus-wide fixes without proof they are correct. A wrong rule that looks
right is worse than no rule. Speed matters, but a false "compliant" or
false clause citation shown live tomorrow is the one failure that cannot
happen. Read that as the constraint on everything below, not as permission
to slow down.

## 1. Confirm SAES-A-105, right now, plainly

734a2a8 ("fix(standards): extract prohibitive numeric limits") is
committed. Its message has no body, so it is unclear whether it actually
produced the PSV requirement or just changed the pattern.

Query standard_requirements for SAES-A-105 (doc_a835c3a15e04) right now.
Report: does a row exist with clause 5.3.3, value 115, unit dB(A),
comparator <=, source_text retained? Yes or no, with the row shown. If no,
say so plainly - do not soften it.

## 2. Find why 252 of 272 standards have zero requirements. FAST, tonight.

This is not the careful multi-day version. It is: find the cause fast,
using the disposable-database approach already set up, and report it
tonight. If it is ONE mechanical cause (extraction never scheduled for
standards added a certain way, a role-assignment path that skips
enqueueing, a version gate, anything like that) say so in one sentence
with the count it explains, e.g. "N of 252 were never scheduled because
X". If it is several causes, give the split. If you genuinely cannot
determine it tonight, say that and stop - do not guess.

## 3. IF AND ONLY IF the cause is a simple, fixable bug:

Fix it. Then run it on FIVE standards only, not all 252. Different
families. For each, show me (not just "N requirements extracted" - the
actual clause, page, comparator, value, unit, source_text for at least
three requirements per standard) so a human can look at them and confirm
they are real, not garbage. Do not touch the remaining 247 tonight.

## 4. IF the cause is unclear, structural, or you cannot verify correctness
## in time: STOP. Do not reprocess anything else tonight.

Report exactly what is proven-correct as of right now (SAES-A-105's status
from step 1, plus whatever the existing 20 standards already had), and
report what remains unproven. That becomes the honest state for tomorrow.

## Reporting

Every claim with the query/command and its actual output. No summary
percentage. A demo depends on this being true, not optimistic.
