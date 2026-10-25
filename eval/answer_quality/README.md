# Answer quality (order 189)

Scores for the answer text and a rule for keeping a prompt variant. Research
page: `docs/answer-quality-research.md`.

- `quality_scoring.py`: pure code, no model. Faithfulness, response relevancy,
  citation recall and precision, noise sensitivity, and `keep_variant` (same or
  better on EVERY measure, no new forbidden answer, no new figure the cited
  page lacks, a measure with no value blocks).
- `run_aq.py`: asks the invented P1 questions through the real chat with each
  variant of `backend/app/answer_prompts.py` and prints the table.
- `.github/workflows/answer-quality-cpu.yml`: runs it on GitHub's CPU machines
  (by hand only, invented text only, no secret). The Mac is not used.

Variants are off by default (`ANSWER_PROMPT_VARIANT=default`) and local lane
only. Real sheets are scored by s2 on the Mac later; nothing here changes a
default. The scores are word and figure checks, not a judge model, so they
compare variants with each other and not with published numbers.
