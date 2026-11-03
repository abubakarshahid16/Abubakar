# Why no review run ever produced a Fail (#1475)

Counts and code only. No document text, no contractor value. Measured 1 Nov 2026 on a read-only diagnostic copy of the live database (77 review runs, 182,933 findings) and on the five bench runs of `eval/bench/truth.json`, replayed with `scripts/crs_bench.py` (no model call). Live trust switches (`rule_auto_use_enabled`, `tested_cards_decide_enabled`) ON for the replay, as the live setup runs; the bench default has them off.

## The finding in five lines

1. The code CAN say Fail. Every NON_COMPLIANT path below was exercised on invented sheets with planted defects (`backend/tests/test_1475_planted_defects.py`): 15 of 15 planted datasheet defects and 6 of 6 planted standard-limit breaches came back NON_COMPLIANT, 0 false passes. No code defect hides a Fail that a gate then drops.
2. No gate ever held a Fail in a stored run: `rule_said` (the verdict a held row would have had) is COMPLIANT on all 47 held rows in the whole database and never NON_COMPLIANT. A gate cannot swallow what never arrived.
3. The standards comparison almost never reaches a number. Of 182,933 findings only 1,253 pair a requirement with a datasheet value; 9 of those compared as COMPLIANT, 0 as NON_COMPLIANT. In the five bench runs 0 requirement rows reached the numeric compare (table below).
4. Only the datasheet checklist and the sheet's own consistency checks can fail, and on the three approved sheets none of their checkable values breaches a limit: 859 COMPLIANT rows ever (850 checklist, 9 comparison), 0 NON_COMPLIANT. Three of the four committed checklists (pump, vessel, exchanger: 54 items) hold only "is stated" items, which cannot fail by construction; only the relief-valve checklist has 16 limit rules.
5. Separate defect found on the way (owner decision D2): a value printed as "<figure> By Contractor" was judged as if the figure were final. That is where the Pass on a deferred value comes from (below).

## Every path that can produce NON_COMPLIANT

| path | where |
|---|---|
| standard limit against a sheet value (numeric, converted units) | `comparison.py:1165` (`status = COMPLIANT if verdict else NON_COMPLIANT`), reached through `compare` (`:675`) and `_compare` (`:758`) |
| two-sided limit, either end breached | `comparison.py:693` `_compare_range`, breach taken from its two ordinary limits |
| a single stated value | `comparison.py:732` `_compare_nominal` turns every breach into NEEDS_ENGINEER_REVIEW on purpose (planner 14 Oct); it never fails |
| unit of the wrong kind (DS-U2) | `datasheet_checks.py:315` |
| sheet against itself (DS-C1..C5) | `datasheet_checks.py:360` |
| checklist: allowed list, percent of, constant, compare, above-by | `datasheet_checks.py:751, 762, 781, 828, 831` |
| checklist: sizing calculation below the formula | `datasheet_checks.py:1150` |

## Every gate that holds, downgrades or never reaches a Fail

| gate | effect on a Fail | where | seen in the data |
|---|---|---|---|
| low-trust value (OCR fallback, model-read without a proved quote) | NON_COMPLIANT and COMPLIANT become NEEDS_ENGINEER_REVIEW | `comparison.py:584-616`, called from `compare` `:680` and `:2736` | 0 rows |
| model, field-name and asked-value pairings | verdict held for the engineer | `comparison.py:~2770-2830` | all 150 model/field-name pairings ended as questions |
| quantity kind unsure | held | `comparison.py:619` `_hold_unsure_kind` | 5 of the 40 rows that had a value |
| condition not established / not read | NEEDS_ENGINEER_REVIEW before any arithmetic | `comparison.py:938, 980` | not separately counted |
| table row, relative limit (not a limit) | NEEDS_ENGINEER_REVIEW | `comparison.py:835, 856` | 1 row |
| requirement names another document | NOT_IN_DOCUMENT_SCOPE | `comparison.py:~793-818` and the no-field branch `:881` | 2,161 of 4,964 rows on the specification run, 45 of 186 on the PSV sheet |
| rule_trust, UNPROVEN rule (`rule_auto_use_enabled`) | NON_COMPLIANT and COMPLIANT become NEEDS_ENGINEER_REVIEW, the rule's own word kept in `rule_said` | `rule_trust.py:320-345`; applied to every datasheet check at `comparison.py:3000` and to standard rows at `:2920` | 47 rows, all of them `rule_said` COMPLIANT |
| tested cards decide (`tested_cards_decide_enabled`) | a tested relief-valve card decides, every other check stays UNPROVEN | `rule_trust.py:328`, `card_trust.py` | 28 decided on the PSV sheet |
| `requirement_split` | a report of the groups; it holds nothing | `comparison.py:3018` | n/a |
| MISSING_INFORMATION | blank / absent value is never a failure | `comparison.py:~875-905`, `datasheet_checks.py:~700` | by design |

With the live trust switches ON the following Fails are held as questions by design (planted-defect tests pin it, `rule_said` keeps the word): checklist rules that are not tested cards (PSV-16, PSV-18, PSV-25, PSV-S02), every sheet self-check (DS-C1..C5) and DS-U2, because `rule_trust.check_label` labels a non-checklist result UNPROVEN. That is an owner policy, not a defect; whether the arithmetic self-checks should decide is the owner's call and is not changed here.

## Funnel on the five bench runs (stored findings, then replay)

| run | requirement rows stored | with a value | COMPLIANT / NON_COMPLIANT | replay `_compare` calls | with a value | reached numeric |
|---|---|---|---|---|---|---|
| Datasheet 1 PSV datasheet | 69 | 1 | 0 / 0 | 0 (rows made on other branches, not traced further) | 0 | 0 |
| HAZOP procedure PDF | 291 | 2 | 0 / 0 | 238 | 2 | 0 |
| HAZOP procedure Word | 270 | 0 | 0 / 0 | 230 | 0 | 0 |
| Datasheet 2 pump datasheet | 302 | 12 | 0 / 0 | 16 | 1 | 0 |
| Specification 1 specification | 2,513 | 25 | 0 / 0 | 583 | 2 | 0 |

Of the rows that had a value, the stop reasons were: "states no numeric limit" (statement type) 12, AI-matcher or field-name pairing held 18, quantity kind unsure 5, table row 1, unit mismatch 1, pressure reference 1, named value 1, blank field 1 (40 rows). None reached `comparison.py:1165`.

Checklist side (stored, per run): Datasheet 1 28 decided of 172 (all COMPLIANT), Datasheet 2 3 of 20 (all COMPLIANT), the three others 0. With the live switches off the same replay decides 75 of 172 on Datasheet 1, still 0 NON_COMPLIANT.

## Where the Pass on "By Contractor" is produced (owner decision D2)

Datasheet 1 has 6 COMPLIANT checklist rows (set pressure 4, viscosity at relieving temperature 2; all tested cards) on values the sheet prints beside "By Contractor".

* The reader keeps a figure printed with a deferral phrase as a value and puts the phrase in `value_note` (`datasheets.py:2174`, #725 F3).
* `blank_markers.fact_is_placeholder(fact, figure_wins=True)` then says it is not a placeholder (`datasheet_checks.py:731`), and the check judges the figure: "is stated" or the arithmetic (`:746-831`), printing the note in its sentence (`:738`).
* The standards comparison does the same: it compares the figure and only appends the note (`comparison.py:1185`).

Fix, behind `deferred_value_is_query_enabled` (OFF by default, env `DEFERRED_VALUE_IS_QUERY_ENABLED`): a deferred value is NEEDS_ENGINEER_REVIEW in both places, whether the numbers read pass or breach, and also when the deferred value is the right-hand side of a check or one side of a self-check pair. A sizing calculation (`evaluate_calc`, which can return COMPLIANT or NON_COMPLIANT) rests on its input facts, so a deferred input among the roles it reads (`deferred_value.CALC_INPUT_ROLES`) makes its result a query too.

## Bench, before and after the switch (counts)

| line | switch off | switch on |
|---|---|---|
| wrong verdicts | 0 | 0 |
| Pass on By Contractor/TBA, Datasheet 1 | 6 | 0 |
| checklist decided, Datasheet 1 | 28 | 22 (the same 6 rows, now questions) |
| Fail rows, all five runs | 0 | 0 |
| every other line | unchanged | unchanged |

Default switches (`RULE_AUTO_USE_ENABLED=false`, `TESTED_CARDS_DECIDE_ENABLED=false`, which is what a worktree without `backend/.env` runs): Datasheet 1 decides 75 of 172 with 17 Pass on By Contractor; with the D2 switch on, 58 decided and 0 such Pass (0 wrong verdicts). The difference between 75 and 28 is `rule_auto_use_enabled`: with it ON every checklist item that is not a tested relief-valve card is held as UNPROVEN (`rule_trust.py:357`, `check_label` `:320`), 47 held rows on Datasheet 1, all of them would-be passes. `tested_cards_decide_enabled` then lets the tested relief-valve cards decide (the 28).

On the owner's switches the bench gate prints "checklist_decided 28 -> 22" for the switch-on run: those are the 6 deferred passes that became questions, the intended effect. With the switch off the bench gate is GREEN (unchanged code).

## Not proven

* That the real sheets contain no breach: only that no stored run shows one and that the code fails the planted ones. A reader that misses a value gives no verdict either way.
* Procedure planted defects wait for #1476.
* The planted sets are unit-level (no reader, no ingest): they prove the decide step and its gates, not that a real sheet's value is read into the right field.
