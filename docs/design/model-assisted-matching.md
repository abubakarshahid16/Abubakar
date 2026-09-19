# Model-assisted requirement-to-fact matching (master plan §14, second tier)

Status: DESIGN. Written by Cowork 2026-09-19 against `comparison.py` as it
stood mid-containment task; line numbers are approximate and several have since
moved. Sections 7 and 8 describe work that is now BUILT and say so inline -
everything else remains unimplemented at the time of writing.

## 0. The one-sentence rule

The model may CHOOSE a fact from a list Python built. It may never NAME one.

## 1. Where it sits

`comparison.run_comparison()` (~L601-731) iterates requirements, calls
`match_by_containment()` (~L743-814), then `compare()`. The model tier slots in
between `fact = match["fact"]` and `verdict = compare(...)` (~L652-653), and
only when ALL of these hold:

- containment returned no match AND reason is not `AMBIGUOUS_MATCH`
  (a tie is a human question, not a model question)
- requirement.type == numeric_limit AND requirement.value is not NULL
- at least one candidate survives the deterministic pre-filter in §2

Otherwise the loop behaves exactly as today. The model is never consulted for
statement requirements, categorical facts, or ties.

## 2. Candidate list (Python, deterministic, before any model call)

For the requirement, candidates = facts where:

- fact.value is numeric (categorical yes/no/None/N/A excluded)
- `claims.unit_dimension(fact.unit) == claims.unit_dimension(requirement.unit)`
  (NOT `same_unit`, which compares spellings and rejects bar vs kPa)
- the pair is not in `review_pair_rejections` (§7)

**A fact may pair with many requirements; a requirement pairs with at most one
fact.** An earlier draft of this section excluded facts "already paired to
another requirement in this run", which is wrong in the common case: several
clauses in several standards legitimately govern one datasheet field - a design
pressure is constrained by the vessel code, the piping standard and the
material specification at once. Excluding it after the first pairing would make
the result depend on the order requirements happened to be iterated in, and
would silently drop every later requirement about the same field.

Cap at 12 candidates, longest field_name first. Zero candidates: no call,
MISSING_INFORMATION as today. Exactly one candidate: STILL call the model with
the "none" option available. One same-dimension fact is not evidence it is the
right one (design pressure vs operating pressure are both bar).

## 3. What the model sees, and what it must not see

Sees:
- requirement subject (cleaned noun phrase) and the clause text, ≤ 400 chars
- standard document number and clause id
- numbered candidate field_names, each with its section heading if non-NULL

Must NOT see:
- any fact value, unit or page
- the requirement's operator or value
- any other requirement

Reason: a model that sees the numbers can be pulled toward the pairing that
makes the comparison "work". Pairing must be decided on wording alone. A test
asserts the rendered prompt contains none of the candidate values.

## 4. Call contract

Transport: `model_transport.post_json("/api/generate", body, timeout=settings.match_timeout_seconds)`.
Loopback gate already enforced by `endpoint()`. Nothing leaves the machine.

Body:
```
{
  "model": settings.answer_model,          # qwen3.5:4b today
  "prompt": <template in §5>,
  "stream": false,
  "format": "json",                         # NEW to this codebase
  "options": {
    "temperature": 0,
    "seed": settings.match_seed,            # NEW setting, default 0
    "num_ctx": settings.num_ctx,
    "num_predict": 120,
    "num_thread": settings.num_thread
  }
}
```

New settings in config.py: `match_timeout_seconds` (default 30),
`match_seed` (default 0), `match_enabled` (default True; False = tier skipped,
findings say so in rationale).

Response schema, Pydantic, strict:
```
class PairChoice(BaseModel):
    choice: int | None          # index into the candidate list, or null
    reason: str = Field(max_length=200)
```

Validation, in order. Any failure = no match, identical shape to containment's
"none" dict, with `reason` recorded:
1. HTTP / timeout / `ModelHostRefused` -> `model_unavailable`
2. body not JSON, or not a PairChoice -> `model_malformed`
3. choice not None and not `0 <= choice < len(candidates)` -> `model_out_of_range`
4. reason contains a field_name that is not the chosen candidate -> `model_named_other`
5. Determinism check: call twice (same seed). If the two choices differ -> `model_unstable`, no match. Cache the agreed result by hash(requirement_id, sorted candidate ids) for the run.

The model's `reason` is stored in `ai_rationale`, prefixed
"Paired by model; engineer must confirm. Model reason: ...".

## 5. Prompt template

```
You are matching an engineering standard clause to a datasheet field.
Choose the ONE candidate whose field is the quantity this clause governs.
If none is clearly the same quantity, answer null. Do not guess.

Standard: {doc_number} clause {clause}
Clause text: {subject_or_text}

Candidates:
{i}. {field_name}   (section: {section or "-"})
...

Answer as JSON only: {"choice": <index or null>, "reason": "<one short sentence>"}
```

No values, no units, no pages. The word "null" is offered explicitly so the
model has a sanctioned way to decline.

## 6. What the finding records

- `match_method = METHOD_MODEL_CHOICE` (new constant beside `METHOD_CONTAINMENT`,
  which was written expecting a second one)
- `matched_phrase` = the chosen field_name verbatim
- `confidence = CONFIDENCE_MODEL_ASSISTED` (0.5 -> label "medium", never "high")
- `ai_rationale` as in §4
- status still set by `compare()` and `_reconcile()`. Deterministic wins.
  The model never sets a status.

The Review UI must render model-paired findings visibly differently from
containment-paired ones (badge "paired by model"). Rule/model/human must not
read alike (precedent: `review_applicable_standards.selection_method`).

## 7. Engineer governance - CLOSED in c9f7fbe, before this tier

Both gaps were prerequisites and both are now implemented. Recorded here as
built, not as proposed, because the pre-filter in §2 depends on the second.

1. `review_findings` carries `confirmed_by` / `confirmed_at`, and
   `run_comparison(replace=True)` deletes only `WHERE confirmed_by IS NULL` -
   the same rule requirements and facts already followed.
2. `review_pair_rejections` remembers refused pairings.

**KEYED ON sha256 IDENTITY, NOT ON ROW IDS**, and that differs from this
document's original proposal. `standard_requirements.id` and
`submittal_facts.id` are uuid4, regenerated by every `replace=True`
extraction - and re-extraction is how every fix to the extractors reaches the
corpus. A rejection keyed on those ids would have matched nothing after the
next re-run: it would have stopped applying SILENTLY, the same pairing would
have been re-proposed, and the engineer could not have told a forgotten
correction from an ignored one.

As built:

```
requirement_key = sha256(standard_document_id | clause | normalised requirement text)
fact_key        = sha256(submittal_document_id | normalised field_name)
```

`requirement_id` and `fact_id` remain as columns but are INFORMATIONAL ONLY -
useful for tracing a rejection back to the run that recorded it, never read to
decide whether a rejection applies. The fact key deliberately excludes the
VALUE: "this requirement is not about this field" stays true when the
contractor revises the number.

Engineer-confirmed pairings are NOT yet reused as a `METHOD_HUMAN` shortcut.
Confirmation currently protects a finding from deletion; it does not re-assert
the pairing on the next run. Named here so nobody assumes it is covered.

## 8. Related loop-level fix (independent of the model)

`run_comparison` ~L672-692 applies `same_unit` on raw spellings and downgrades
to NEEDS_ENGINEER_REVIEW when they differ, even though `_compatible()` would
normalise kPa and bar to MPa and compare. Replace with a dimension check; keep
`same_unit` only for units that do not normalise (dB(A)). Otherwise every
cross-unit pairing, containment or model, is thrown to the engineer for no
reason.

## 9. Out of scope, named so nobody assumes it is covered

- Table-type requirements (SAES-D-001 §6.2.2 MOP -> design pressure table).
  The matcher can pair them; `compare()` cannot evaluate a table. They stay
  NEEDS_ENGINEER_REVIEW until a table evaluator exists. Separate design.
- Statement requirements. No numeric comparison exists for them.
- Cross-document fact lookup (a value on a drawing, not the datasheet).

## 10. Evaluation protocol, before and after

Ground truth from the containment task on the drum datasheet:
- positives: the engineer-judged genuine pairs (2 today)
- negatives: every word-overlap pair judged a false friend (SAES-W-010 §13
  insulation is the canonical one)

Hard gate: zero false pairings on the known negatives. A single wrong pairing
produces a wrong COMPLIANT / NON_COMPLIANT, which is the worst outcome this
system can have. Recall on positives is reported, not gated.

Holdout: after the tier passes on datasheet 1, datasheet 2 is loaded cold.
Measure before any fix. Datasheet 3 stays sealed until Phase 6.

Budget: report calls made, mean and max latency, tokens per call. On
qwen3.5:4b with ≤ 12 candidates and ≤ 600 prompt tokens, expect tens of calls
per review, not hundreds. If a review exceeds 100 calls, that is a pre-filter
defect, not a model cost.

## 11. Tests that must exist, each mutation-proven

- prompt never contains any candidate value, unit or page
- index out of range -> no match
- choice null -> no match, MISSING_INFORMATION
- reason names a non-chosen field -> no match
- two runs disagree -> no match, reason model_unstable
- model host refused / timeout -> no match, rationale says model_unavailable
- categorical facts never enter the candidate list
- dimension mismatch never enters the candidate list
- rejected pair never re-proposed
- confirmed finding survives replace=True
- METHOD_MODEL_CHOICE finding gets confidence 0.5 and label "medium"
- containment match takes precedence; model not called when containment hits
- ties (AMBIGUOUS_MATCH) never reach the model
