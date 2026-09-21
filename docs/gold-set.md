# Checking the system against a standard, by hand

**Who this is for:** the engineer doing the check. You do not need to read any
code, run anything, or install anything. You need a spreadsheet and a PDF.

## Why we are asking you to do this

The system reads your standards and pulls out the rules it finds. Right now
nobody knows how much it gets right. We can tell you how many rules it found -
1,746 across 272 standards - but "found" is not "correct", and a rule stored
the wrong way round is worse than a rule missed, because it comes with the
right clause and page attached and looks trustworthy.

The only way to know is for someone who knows the standards to write down the
right answer, once, for a few standards. Then the system can be measured
against it automatically, for ever, every time we change anything.

**This costs you about half a day, once.** After that it is free.

## What to do

1. Open `gold/TEMPLATE.csv` in Excel.
2. Pick a standard. Save a copy of the template named after it, for example
   `gold/SAES-A-105.csv`.
3. Read the standard. **Every time you find a rule, add one row.**
4. Save as CSV. Tell whoever gave you this that it is ready.

That is all. Do not worry about getting the format perfect - the columns are
described below and anything unclear is better left blank than guessed.

## One row per rule

| Column | What to put | Example |
|---|---|---|
| `standard` | The file name of the standard | `SAES-A-105.pdf` |
| `clause` | The clause number the rule is in | `5.3.3` |
| `page` | The PDF page it is on (the page number shown in your reader) | `9` |
| `kind` | One of four words - see below | `limit` |
| `operator` | Only for a `limit`. One of `<=`, `>=`, `<`, `>`, `=` | `<=` |
| `value` | Only for a `limit`. Just the number | `90` |
| `unit` | Only for a `limit`. Exactly as the standard writes it | `dB(A)` |
| `notes` | Anything you want to say. Optional | `applies to new equipment only` |

### The four kinds

| Word | Use it when | Example |
|---|---|---|
| `limit` | The rule gives a number you could check a datasheet against | "shall not exceed 90 dB(A)" |
| `statement` | A real requirement, but with no number to check | "shall be painted in accordance with SAES-H-001" |
| `table` | The number lives in a table, not in the sentence | "shall meet the values in Table 3" |
| `trigger` | A number that says WHEN something applies, not a limit | "for lines above 10-inch NPS, a flange is required" |

**The difference between `limit` and `trigger` matters more than anything else
on this page.** "Equipment generating noise in excess of 85 dB(A) shall have a
data sheet submitted" does not forbid 85 dB(A) - it says what paperwork to
file. If the system read that as a ceiling it would fail a perfectly compliant
submittal. Mark those `trigger`.

## Rules of thumb

- **One rule per row.** If a clause says "not less than 63 L/s but not more
  than 252 L/s", that is **two rows** - one `>=` 63 and one `<=` 252.
- **Exceptions get their own row.** If the general limit is 90 dB(A) and relief
  valves may reach 115 dB(A), write both, and say which is the exception in
  `notes`.
- **Unit exactly as written.** If the standard says `dB(A)`, write `dB(A)`, not
  `dBA` or `dB`. If it gives both metric and imperial - "13.1 feet (4000 mm)" -
  use the one the standard states first.
- **Leave it blank if you are not sure.** A blank is honest. A guess becomes
  the "right answer" the system is measured against, and a wrong right answer
  is worse than no answer.
- **Please do not paste sentences from the standard into the file.** The clause
  number and page are enough to find it again. This keeps the file safe to
  store and share.

## Please do not skip the boring ones

It is tempting to write down only the interesting rules. Don't. The measurement
only works if the list is **everything in that clause range**, because we
measure what the system MISSED as well as what it got wrong. If you write 12
rules and the system found 12, that is a perfect score - even if the standard
actually contained 30.

If you only have time to do part of a standard, that is fine: do a complete
clause range and say so in `notes` on the first row, for example
`covered clauses 5 to 7 only`.

## An example, filled in

This is SAES-A-105 clause 5.3.3, which states one general noise limit and four
exceptions:

| standard | clause | page | kind | operator | value | unit | notes |
|---|---|---|---|---|---|---|---|
| SAES-A-105.pdf | 5.3.3 | 9 | limit | <= | 90 | dB(A) | general limit, new equipment |
| SAES-A-105.pdf | 5.3.3 | 9 | limit | <= | 115 | dB(A) | exception, pressure relief valves |
| SAES-A-105.pdf | 5.3.3 | 9 | limit | <= | 105 | dB(A) | exception |
| SAES-A-105.pdf | 5.3.3 | 9 | limit | <= | 97 | dB(A) | exception |
| SAES-A-105.pdf | 5.3.1 | 8 | statement | | | | refers to OSHA limits, no number here |

## What happens next

Someone runs one command and gets two numbers for each standard you did:

- **Recall** - of the rules you wrote down, how many did the system find?
- **Precision** - of the rules the system found, how many are right?

and one more that matters most:

- **Wrong direction** - rules where the system found the right clause and the
  right number but stored `<=` where you wrote `>=`. Those are the dangerous
  ones and they are counted separately, because they pass a bad submittal and
  fail a good one.

You will get the list of every disagreement, so if the system is right and the
sheet is wrong, we fix the sheet. That happens and it is useful.
