# Agent proof test: spec (Part of #805, issue #1690)

One page. No document or standard text anywhere in this repo. Skills are local only.

## Design (fixed)
A lead reviewer agent reads the WHOLE document, follows a skill for that document kind, calls tools, and decides.
Code only VERIFIES quotes and numbers. A second opinion comes from a DIFFERENT model. When unsure it asks the engineer.
Everything is behind `AGENT_REVIEW_ENABLED` (off by default). Nothing runs on the live database; proof runs use copies.

## Loop (`agent_loop.py`)
think -> ask for one tool -> code runs it -> look at the result -> repeat. Max 15 steps per item. Every step is saved to the
item's trace; a run resumes from the last saved step. A USD cap per item and per run; every Claude call goes through
`reader_transport.py` and `claude_spend.metered`, with prompt caching on the document and the skill. Model calls to the
local model go through `model_transport.py`. The lead first reads the document and builds a page-keyed document map, then
works item by item, answers all items on an open page in one look, records findings and drops raw text.

## Six tools (`agent_tools.py`, thin wrappers over existing code)
| Tool | Wraps | Returns |
|---|---|---|
| open_page(doc, page) | page reading in `page_ledger` | page text with page number |
| search(query, scope) | `search.py` dense + keyword, existing ranking | passages with document and page |
| get_clause(standard, clause) | standard text at the contract's edition | full clause with scope, conditions, exceptions |
| compare_number(clause_figure, doc_figure) | `figure_compare.py` (#1689) | decided / cannot decide, by code |
| record_finding(finding) | `ai_review_proposals.verify` (#1667) | accepted or refused, with the reason |
| ask_engineer(item, reason) | query row | YELLOW row for the engineer |

## Skills (`agent_skills.py` loader; content local only)
A skill is a playbook per document kind: for each item the expected position, the acceptable range, and what triggers
escalation. Skills live in `~/project/mirror/skills/` and are never committed. The repo holds the loader and one sample
skill with made-up content (`backend/tests/fixtures/sample_skill.md`). Skill 1 "equipment datasheet"; skill 2
"HAZOP / SIL study procedure". Skills cite clause numbers and never quote standard text.

## Findings
GREEN (complies), YELLOW (query / engineer), RED (does not comply). Each carries: document quote with page, clause quote,
the required action, priority (must / should / nice), written as a contractor-ready comment. Rules: GREEN needs a
verified document quote; "not mentioned" is never GREEN; confidence is never "high"; a number is decided only by code.
GREEN and RED get a second opinion from a different model; a disagreement becomes YELLOW. Anything code cannot verify
is dropped or becomes YELLOW. Wrong verdicts must be 0.

## Local files (never git, CI or chat)
`~/project/mirror/proof/agent-test/`: `LIVE.md` (rewritten after every piece and every 10 items), `live.log` (one line per
event, reason at most 20 words, no document or standard text), one trace file per item, `RESULTS.md`, 5 example comments.

## Done-gate
`answer_key_score.py` on the three approved test documents (two equipment datasheets and one study procedure) against the current answer keys, compared with the re-scored stored
system A files. Adopt only if wrong verdicts stay 0 and missed falls. Held-out public documents (local model only, no
key) are reported separately: rows, GREEN/YELLOW/RED, quote-verified rate, 5 comments for the owner.

## Build split (3 helpers, separate files)
1 loop: `agent_loop.py`, trace and resume, spend. 2 tools: `agent_tools.py`. 3 skills: `agent_skills.py`, sample skill,
local skills. `model_transport.py` changes (vllm-mlx) are danger-zone: own test, mutation entry, fresh review.
