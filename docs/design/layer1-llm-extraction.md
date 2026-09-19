# Layer 1: the LLM reads datasheets, Python verifies every claim

Status: DESIGN + pre-built core, on branch cowork/layer1-llm-extraction.
Decision record: rules proved brittle on forms (three sheets, three
breakages); the reading of FORMS moves to the model, the judging never does.

## The contract that makes hallucination unable to pass

Every fact the model extracts must carry `quote` - the exact row text it
read the value from. accept() keeps a fact only when:
1. the quote genuinely appears on the page (whitespace-folded), and
2. the value appears inside its own quote.
An imagined fact has no true quote to give. Rejections keep their reason,
so the report can say "the model imagined N rows" with names.

Determinism: the page is read twice; a fact only one run produced drops as
model_unstable. Same rule the matcher tier used.

## What is pre-built and pre-tested (8 tests, green)

- backend/app/extraction_llm.py - prompt, strict parser, the accept() gate,
  extract_page() with the two-run agreement rule. The model is INJECTED as
  a callable, so everything tests with a fake model and no transport.
- backend/app/extraction_score.py - the competition judge: extracted vs
  hand-counted truth -> recall, precision, misses and inventions BY NAME.

## The experiment (the merge task runs it; Ollama required, machine idle)

1. Wire the real model call: model_transport.post_json("/api/generate"),
   format json, temperature 0, seed, per page, twice.
2. Ground truth: the drum sheet and the PSV sheet hand counts (in the
   repo's measurement history). M-03 stays sealed - Cowork holds its key
   and grades independently.
3. Run BOTH readers on both spent sheets. Score both. Report per sheet:
   recall, precision, inventions caught by the gate, wall clock.
4. Decision gate, agreed in advance:
   - LLM recall >= rules AND precision >= 0.95 after the gate -> LLM
     becomes primary reader, rules become fallback.
   - LLM materially worse -> keep rules primary; the misses list tells us
     whether Layer 2 (template memory) or a vision model is the next door.
5. Only after the decision: M-03 cold, as the unseen exam for whichever
   reader won.

## Layers 2 and 3, for the record

- Layer 2, template memory: first sheet of a new template is confirmed by
  a human once; every later sheet of that template reads instantly. This
  is where production accuracy reaches the high 90s, because contractors
  reuse their forms.
- Layer 3, today's rules: the silent fallback, plus everything unread is
  named. Never a guess - that property is the ceiling-holder and is not
  negotiable in any layer.
