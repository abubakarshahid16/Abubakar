# The blind test

The only real proof that the review reads a datasheet correctly: an engineer
decides what the comments should be **before** the system sees the datasheet,
and the system's output is scored against that. Test counts, code reviews and
demos cannot answer "are the comments right?". This can.

## Who does what

| Role | Does |
|---|---|
| **Engineer** | Writes the answer key. Must not see the system's output for this datasheet first. |
| **Custodian** | Picks the datasheet, keeps the key, records its hash before upload. Should not be the person who tunes the system. |
| **Operator** | Uploads the datasheet, runs the review, runs the scorer. |

One person can hold two roles, never Engineer and Operator on the same datasheet.

## Steps

1. **Custodian picks 2-3 datasheets nobody on the project has opened**, preferably
   of different equipment types and layouts. Not M-03, I-06 or 216400C: those are
   burned (already inspected, and 216400C was used for tuning).
2. **Engineer fills the answer key** (`gold/FINDINGS-TEMPLATE.csv`, copied to
   `gold/FINDINGS-<datasheet>.csv`), from the datasheet and the standards alone:
   - one row per comment they would raise: page, field, tag, and `breach`,
     `missing` or `review`, plus the standard and clause if they know it;
   - one `none` row per field they checked and would **not** comment on. These
     are what catch wrong comments, so include the important fields even when
     they are fine;
   - cover the **whole** sheet if possible. Then every machine row not in the
     key is a real false positive, not just an unjudged one.
3. **Custodian records the key's hash before anything is uploaded:**
   `certutil -hashfile gold\FINDINGS-<datasheet>.csv SHA256` (Windows), and writes
   the hash and the date somewhere the operator cannot edit (an email to
   themselves is enough).
4. **Operator uploads the datasheet and runs the review.** Nobody confirms, edits
   or rejects anything on this run before scoring: the test scores the machine.
5. **Operator scores it:**
   `python scripts/blind_score.py <review_run_id> gold/FINDINGS-<datasheet>.csv`
   The first line prints the key's SHA-256. **If it differs from step 3, the key
   was changed after the output could be seen, and the result is not blind.**
6. **Engineer reads every "missed" and "false alarm" line** (`--show-fields`
   prints the field names; keep that output on the machine). Each one is either a
   real defect to fix, or a key mistake, which must be written down as one and
   never quietly edited out of the key.

## Reading the result

| Number | Meaning |
|---|---|
| Found, right type | The machine raised the comment the engineer expected |
| Found, other type | Raised, but as a different kind (a breach reported as "needs review") |
| Missed | The engineer expected a comment and the machine raised none. **The most important number for a reviewer's safety** |
| False alarms | A comment on a field the engineer said is fine. **A wrong comment sent to a contractor** |
| Not in the answer key | Machine rows no key line accounts for. Real false positives only if the key covers the whole sheet |
| Same clause cited | Of the found comments where the engineer named a clause, how many cite it |

Every number is printed with its denominator. A result is about **those
datasheets**, never "the system": three datasheets are a sample, and are
reported as one.

## What counts as passing

Not set here, on purpose. The owner and the client decide the bar (for example
"no false alarms, at most 1 in 10 missed") **before** the first score is seen, so
the bar cannot be chosen to fit the result.
