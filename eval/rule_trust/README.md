# Answer-key seed for the trusted-rule proof (#947 step 4)

`psv_invented_seed.json`: 75 cases for `rule_trust.prove_family` (`{rule_id, values, expected}`), on 6 rules read from the INVENTED PSV standard of the PF1 set (`pf1-07-psv`: three numeric limits and three two-field rules, e.g. "the cold differential test pressure shall not exceed the set pressure").

- **Truth is arithmetic, not the engine:** for each limit, values inside / outside / exactly at it (1, 5, 10, 20, 50 %), and the same limit in another unit of the same quantity; for each two-field rule, an output below / at / above `factor x reference + offset` for two reference values. The expected answer is computed from the numbers; the engine is only compared with it afterwards (`backend/tests/test_psv_answer_key_seed.py`: 75 of 75 agree).
- **What it is NOT:** not engineer-confirmed, not the client's standard, not a family proof. 75 cases of 6 rules cannot reach the >=300 cases of a real PSV family; **the engineer adds the rest and reviews every case** (NEEDS OWNER: nominate the engineer, #947).
- One standard of the invented set had a seventh rule whose unit the generator could not infer; it is left out (and counted in the generator's output), never guessed.

## Before/after of the wiring (#947, switch `rule_auto_use_enabled`)

`scripts/rule_trust_before_after.py --db <a COPY of a PF1 database> [--run <id>]`
re-runs each completed, undecided review run twice - switch OFF, then ON - with
every model tier off (counts only, no lock, both arms on the same facts) and
prints the findings by status and the rule-trust counts per run: labels,
verdicts held because the rule is unproven, safety ticks, fields no rule
checked. The OFF arm must equal the run's stored counts. It refuses the live
database and writes the copy (each arm replaces the run's unconfirmed
findings): delete the copy when done. Ids and counts only, never a value.
