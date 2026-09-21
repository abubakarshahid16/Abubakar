# Saying which rule each datasheet number belongs to, by hand

**Who this is for:** the engineer doing the check. You do not need to read any
code, run anything, or install anything. You need a spreadsheet, the
contractor's datasheet, and the standards it names.

This is the companion to `docs/gold-set.md`. That one asks whether the system
READ a standard correctly. This one asks a different question, and until
somebody answers it nobody can answer it at all.

## Why we are asking you to do this

Reading a standard gives the system a pile of rules. Reading a datasheet gives
it a pile of numbers. Neither is any use until it decides **which rule each
number is about** - and that decision is the one that reaches the contractor.

Today it decides by looking for the field name inside the rule's sentence. On a
real pressure-vessel datasheet last night that produced these two:

- The datasheet says **design life = 25 years**. The system filed it under
  SAES-P-103 clause 5.2.5, which requires a **battery** to last 20 years. There
  is no battery on a pressure vessel.
- The datasheet says **normal operating temperature = 30 °C**. The system filed
  it under SAES-X-500 clause 6.6.3, which is about **electrolyte resistivity**
  measured in ohm-cm. Degrees against ohm-cm.

Both are obvious once you see them. Neither was found by the system, and
neither could have been: nothing anywhere records which pairings are right, so
there is nothing to be wrong against. We could change the matching tomorrow and
have no way of telling whether we made it better or worse.

**A wrong pairing is not the same kind of mistake as a missed one, and this is
the whole reason the file exists.** A missed pairing is silence - the engineer
gets no finding and reads the datasheet themselves, as they do today. A wrong
pairing goes out with a real clause number and a real page attached, looking
exactly like a correct one. If it says a submittal fails, somebody has to
answer it, and that costs money and standing before anybody notices the clause
was about a battery.

So the sheet you fill in has to record the **non-matches** as carefully as the
matches. A blank sheet full of correct pairings proves nothing. It is the rows
that say NONE that prove the system is not inventing them.

**This costs you about two hours per datasheet, once.** After that it is free,
and every future change to the matching is measured against it automatically.

## What to do

1. Open `gold/PAIRS-TEMPLATE.csv` in Excel.
2. Pick a datasheet somebody has already put through the system. Save a copy of
   the template named after it, for example `gold/PAIRS-216400C.csv`.
3. Ask whoever gave you this for the list of fields that datasheet carries, and
   the list of standards the review treated as applicable. **One row per
   field.** They come pre-filled if somebody has run the export for you.
4. For each field, decide one of three things - see below.
5. Save as CSV. Tell whoever gave you this that it is ready.

## One row per datasheet field, and three possible answers

| Column | What to put | Example |
|---|---|---|
| `submittal` | The file name of the datasheet | `216400C-2003-SP-0810-0003_00.pdf` |
| `equipment_tag` | The item this value belongs to, if the sheet covers several | `2003-47-V-0001A/B` |
| `field` | The field name as the datasheet writes it | `internal design pressure` |
| `value` | The number on the datasheet. Copied, not judged | `3.5` |
| `unit` | The unit as the datasheet writes it | `bar (ga)` |
| `page` | The datasheet page it is on | `4` |
| `standard` | **The answer.** See the three below | `SAES-D-001.pdf` |
| `clause` | The clause number, when there is one | `6.2.3` |
| `notes` | Why. Optional, and worth the thirty seconds | `design pressure table` |

The `standard` cell is where the work happens, and it takes exactly one of
three answers:

| What you put in `standard` | What it means |
|---|---|
| a file name, plus a `clause` | **This field is governed by that rule.** |
| the word `NONE`, `clause` empty | **No rule in the applicable standards governs this field.** |
| left **blank** | **You are not sure.** The row is skipped, and skipping it costs nothing. |

**`NONE` and blank are not the same and the difference is the point.** `NONE`
is a statement: nothing governs this, so if the system pairs it with something,
the system is wrong. Blank is an admission: you did not decide, so nothing is
scored either way. If you are tempted to guess, leave it blank - a guess
becomes the right answer the system is measured against, and a wrong right
answer is worse than no answer.

**Most rows will be `NONE`, and that is the expected result, not a failure.** A
datasheet carries weights, shears, moments and operating conditions that no
standard puts a limit on - the contractor states them so the next discipline
can use them. If half your sheet is `NONE`, the sheet is doing its job.

## Rules of thumb

- **Ask "does this clause put a limit on this quantity?"** - not "do these two
  mention the same words". SAES-D-001 clause 6.2.3 sets the *internal design
  pressure* from a table indexed by the *maximum operating pressure*. It
  governs the design pressure. It does not govern the operating pressure - that
  one is a number the contractor tells us, not one we check.
- **A field may legitimately have two homes.** If two clauses genuinely govern
  the same field, write two rows for it. The system is credited for finding
  either.
- **Do not pick the nearest clause.** If nothing really governs a field, the
  answer is `NONE`, even when something in the standard is on a related topic.
  "Related topic" is precisely the mistake we are trying to measure.
- **Check the units before you accept a pairing.** If the clause's number and
  the datasheet's number could not be compared - degrees against ohm-cm, years
  against millimetres - the pairing is wrong whatever the words say.
- **Wrong equipment is wrong, whatever the wording.** A clause about batteries,
  exchangers or anodes does not govern a pressure vessel.
- **Please do not paste sentences from the standard into the file.** The clause
  number is enough to find it again, and it keeps the file safe to store.

## Please do not skip the boring ones

Every field the datasheet carries needs a row, including the twenty that will
obviously be `NONE`. The measurement only works if the list is complete,
because the only way to catch a matcher that invents pairings is to have
written down, in advance, where there was nothing to find.

If you only have time for part of a datasheet, that is fine: do a complete
page or a complete section and say so in `notes` on the first row, for example
`covered page 4 only`.

## An example, filled in

Five fields from a pressure-vessel datasheet:

| submittal | equipment_tag | field | value | unit | page | standard | clause | notes |
|---|---|---|---|---|---|---|---|---|
| 216400C-...pdf | 2003-47-V-0001A/B | internal design pressure | 3.5 | bar (ga) | 4 | SAES-D-001.pdf | 6.2.3 | the design pressure table |
| 216400C-...pdf | 2003-47-V-0001A/B | concrete bearing stress | 8300 | kPa | 4 | SAES-D-001.pdf | 9.1.6 | allowable is stated as 8,300 kPa |
| 216400C-...pdf | 2003-47-V-0001A/B | maximum operating pressure | 2.2 | bar (ga) | 4 | NONE | | the table's input, not something it limits |
| 216400C-...pdf | 2003-47-V-0001A/B | operating weight l3 | 21670 | kg | 5 | NONE | | stated for the civil design, not limited |
| 216400C-...pdf | 2003-47-V-0001A/B | internal maximum design temperature | 95 | °C | 4 | | | left blank - SAES-D-001 section 6.3 may govern it, please check |

## What happens next

Someone runs one command and gets three numbers, kept apart on purpose:

- **Recall** - of the pairings you wrote down, how many did the system make?
- **Precision** - of the pairings the system made, how many were right?
- **False pairings** - the count, on its own, of values the system attached to
  a rule you said was not theirs.

The third is never folded into the second, and never averaged with anything.
Precision is a ratio and it improves when the system pairs less; the count of
false pairings is the thing that reaches a contractor, and a run that makes one
fewer correct pairing and one fewer false one is a better run, not a wash.

You will also get the list of every disagreement. If the system is right and
the sheet is wrong, we fix the sheet. That happens and it is useful.
