# #193 — why datasheet facts do not pair with requirements (trace, 2026-09-26)

Measured on a scratch database outside git: the owner's 3 real datasheets (a
centrifugal-pump enquiry sheet, a relief-valve sheet, a pressure-vessel sheet)
and the 9 real standards available in the cloud session. Aggregate numbers
only; no document text, filename or standard number appears here. Every
candidate was judged by reading both sides (AI-judged, not engineer-verified).

## Method

For each datasheet x each extracted requirement, record (1) the requirement's
class, (2) what the production matcher decided and why, and (3) an OVER-
GENEROUS oracle: every numeric fact of the same physical dimension that
shares any content word with the requirement. The oracle exists only to find
pairs the matcher might be missing; each oracle candidate was then judged.

## What was measured

| | pump | valve | vessel |
|---|---|---|---|
| facts | 177 | 64 | 174 |
| facts with a number | 6 | 40 | 45 |
| blank facts (vendor fields left empty on an enquiry sheet) | 132 | 24 | 2 |
| requirements (9 standards) | 1355 | 1355 | 1355 |
| statement requirements (no value to compare) | 1220 | 1220 | 1220 |
| table values (not a matchable type) | 42 | 42 | 42 |
| matchable requirements | 93 | 93 | 93 |
| paired by the matcher | 0 | 0 (1 refused as ambiguous) | 0 |
| requirements with >= 1 oracle candidate | 7 | 23 | 24 |
| oracle candidates judged a TRUE pair | **0** | **0** | **0** |

Every oracle candidate was a coincidental word: a fire-water flow rate against
a pump's capacity, a reboiler temperature against a valve's operating
temperature, a concrete compressive strength against a vessel's bearing
stress. **On this corpus 0 pairings is the correct answer and the matcher made
0 false pairs.**

## Failure causes, counted (per datasheet, 1355 requirements)

| Cause | Count | Kind |
|---|---|---|
| Requirement is a statement with no value | 1220 | non-comparable by design |
| Requirement is a table value (lookup data, not a limit) | 42 | non-comparable by design |
| Requirement governs something the datasheet does not describe (fire water, spacing, structures, process plant) | 93 of 93 matchable | **requirement belongs to another scope** - applicability, not pairing |
| Vendor field left blank on the enquiry sheet (pump) | 132 of 177 facts | correct MISSING_INFORMATION, not a defect |
| Requirement's printed unit thrown away | 20 of 93 matchable (4 more are correctly unitless) | **requirement extraction defect** - fixed below |
| Requirement subject is a fragment ("but", "systems", empty) | 14 of 93 | requirement extraction defect - recorded, not fixed here |

## Root cause, as far as this corpus can show it

None of the 50 standards the three datasheets cite is among the 9 available
here, so the matchable requirements are about other equipment and site
systems. The pairing matcher is not the cause on this corpus: it correctly
pairs nothing. #193's live figures (290 facts, 2 pairings) were measured with
the owner's full library; the same question - are the selected standards the
ones that govern the datasheet's values? - must be answered there. That needs
the governing standards, which only the owner holds.

## What was fixed (general, not document-specific)

Requirement unit grammar (`claims` unit table, `requirements_3b.unit_token`):
flow and application-rate units (`L/s`, `L/min`, `L/m2s`, `L/(m2s)`), absolute
and gauge pressures (`psia`, `kPag`, `kPaa`, `bara` - recognised, never
converted, so an absolute value never compares with a gauge one), `kN/m3`,
`lux`, and a unit glued to its own conversion ("1,800 m2(20,000 ft2)").

| | before | after |
|---|---|---|
| matchable requirements with a unit | 69 / 93 | 87 / 93 |
| other requirement units changed | - | 0 |
| requirements added / removed | - | 0 / 0 |
| pairings (true / false) | 0 / 0 | 0 / 0 |

Tests `test_193_requirement_units.py`; mutations M865-M869.

## What is NOT claimed

Pairings did not increase, and on this corpus they must not: there is nothing
true to pair. The semantic pairing architecture the acceptance gate asks for
(canonical parameters, equipment scope, semantic candidates, bounded model
choice) cannot be validated - or its false-pair rate measured - without
standards that actually govern these datasheets. Building it against this
corpus could only add false pairs. **Owner action:** provide (or run on the
laptop against) the standards each datasheet cites; the trace harness is ready
to re-run on them.
