# The contract rule book: a recorded choice

Order 14 LPD (P3); lead decision of 17 Nov 2026, round 4 of #1880. Behind `contract_rule_book_enabled` (off by default).

When a contract paper is reviewed, its package's general terms paper may serve as its contract rule book: it is part 4 of the
general review, and every line from it says "AI draft, engineer to confirm". **The code never picks that paper by its own
guess.** Four review rounds showed that reading a title can be fooled ("Supplement: General Conditions", "Amendment No. 3 to the
General Conditions"...). So the rule book is a choice an engineer records.

## The file

`backend/app/reference/contract_rule_book.local.json` is local to the app's own machine and git-ignored, because it holds real
document ids. It follows the same pattern as `edition_cutoff.local.json`. If it is absent, no choice is recorded.

```json
{
  "format": "contract-rule-book/1",
  "choices": [
    {
      "papers": ["doc_aaaaaaaaaaaa", "doc_bbbbbbbbbbbb"],
      "rule_book": "doc_cccccccccccc",
      "chosen_by": "the engineer's name or role",
      "chosen_at": "2026-11-17"
    }
  ]
}
```

- `papers` lists the papers under review that this choice applies to (document ids).
- `rule_book` is the id of the chosen general terms paper.
- `chosen_by` and `chosen_at` are required.
- The ids above are invented.

## What the review does

| Case | What happens |
|---|---|
| A choice is recorded for the paper | The recorded paper is used if it is held and the person who started the review may read it. Every send gate still applies: it is on the plan's leaving list before the start, a Claude run carries it only when that list names it, a contract goes to Claude only on an explicit Claude start, and the block list wins. If it is not held or not readable, one line says so and nothing is used. |
| No choice is recorded | Nothing is used. One internal line gives what the title rule would suggest: "suggested contract rule book: <paper>, not used until an engineer confirms it" (or "none suggested"). |
| The file cannot be read | The file is not JSON, not the documented format, lacks a field, or has two entries for one paper that disagree. Nothing is used and one line says why. |
| The contract checklist | CT-01 to CT-08 still run in every case: they need no rule book. |
