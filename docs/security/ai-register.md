# S2. AI register (Q33, Q37, Q39)

Every AI service and AI agent is listed here **before** it is used. The second table lists every AI switch in `backend/app/config.py`, with its default. **CI fails if that table does not match the code** (`scripts/check_ai_register.py`). A new switch, a removed switch or a changed default cannot merge without updating this file.

## AI services and agents

| Name | Type | Owner | Job | Access granted | Data allowed | Approved | How to switch off |
|---|---|---|---|---|---|---|---|
| Claude API | External AI service | Owner (Usman) | Datasheet reading, matching, CRS wording, standards scope, AI engineering check, chat | Internet only via `reader_transport.py`. USD 5 per step, USD 20 total (`claude_spend`) | Public. Chat: only files explicitly selected by the user for that Claude request; prior document-bearing history is filtered to that selection. Other confidential workflows: owner-approved list (currently M-03, I-06, 216400C) | Owner, 25 Sep 2026; chat scope 16 Oct 2026 (#692) | Remove the API key from `backend/.env`; set `REASONING_PROVIDER=ollama` and `DATASHEET_AI_READER=ollama` or `off` |
| Ollama (local model, today qwen3.5:4b) | Internal AI on the local PC | Owner (Usman) | The same jobs, offline | Loopback only (`config.check_model_url`) | All internal classes except Restricted | Owner | Stop Ollama |
| s1 | AI agent (Claude Code, PC) | Owner (Usman) | Builder | `D:\project\Rag_chatbot` and its worktrees. Opens PRs; never merges | No Restricted data. Never `hidden-exam` | Owner, in chat | Close the session; revoke its token |
| s2 | AI agent (Claude Code, PC) | Owner (Usman) | Merger and inspector | The same folders. May merge; may back up the live DB | The same. May read `hidden-exam` only to score | Owner, in chat | Close the session; revoke its token |
| cloud | AI agent (Claude Code, GitHub) | Owner (Usman) | Builder | This GitHub repository only, through a limited token (S4) | Code and synthetic data only | Owner, 8 Oct 2026 (limited token not yet set) | Revoke the token |
| Planner | AI agent (Claude Cowork) | Owner (Usman) | Plans, audits, posts on GitHub | Reads the PC folders. GitHub posts only with the owner's OK per change | No Restricted data | Owner, in chat | End the session; remove the folder link |

## AI switches in `backend/app/config.py` (machine-checked)

**Defaults as they stand once #793, #794 and #799 are merged** (the #805 Stage A merge order puts #808 after them). Until #793 and #794 are on main, the check reports exactly their rows (`datasheet_ai_reader`, `match_enabled`, and `match_engine`, which #794 adds).

A switch is any `*_enabled` flag, or `*_provider` / `*_reader` / `*_engine` setting (the engine that answers), whose name names an AI step (`ai`, `reasoning`, `judge`, `match`, `model`, `reader`, `wording`, `vision`, `llm`). The default is the code's own default. An operator overrides it in `backend/.env`.

| Switch | Default | Uses | What it does | Off means |
|---|---|---|---|---|
| `reasoning_provider` | `ollama` | Claude API or local model | Which engine every reasoning step uses. `claude` only when both standards-reader egress flags and a key are also set. `per_task` (#501): Claude only for a step whose own engine setting says claude (the AI reader, the AI matcher); every other step local | The local model |
| `standards_reader_enabled` | `False` | Claude API | One of the two egress flags for the Claude lane | No document text can reach the Claude API |
| `datasheet_ai_reader` | `ollama` | Local model or Claude API | An AI reads each datasheet page; code proves every value's quote on the page. Local model by default since #793 | The code readers only (`off`) |
| `match_enabled` | `True` | Local model or Claude API | The AI proposes which rule fits which value; code applies the refusal rules. On by default since #794. Since #882 technique 2 it also asks the local model (`ai_task_model`) one small question per requirement still without a value (its words and a few page-tagged datasheet lines, never its limit), at most `match_ask_max_per_run` per review (**default 0 = off** until its PF1 ON before/after, order 51); code verifies the answer on the page and every verdict on it is held for the engineer | Code pairing only; no questions |
| `match_engine` | `ollama` | Local model or Claude API | Which engine answers the matcher: `ollama` (local) or `claude` (only with the Claude lane on; metered under the step `requirement-matcher`). Added by #794 | Not a switch-off: `match_enabled` turns the matcher off |
| `applicability_reasoning_enabled` | `True` | Local model or Claude API | Decides which standards apply, against each standard's verified scope record | The taxonomy path, or "scope not checked" |
| `ai_applicability_enabled` | `False` | Local model | Proposes "does not apply" per requirement with a quote; code confirms | Every requirement is checked |
| `ai_clause_checks_enabled` | `True` | Local model | Proposes a check (field, limit, unit, condition, quote) for each clause sentence the review could not decide; code verifies every part; kept as a draft for the engineer, never a verdict (#645) | Undecided clause sentences stay as they are, with no proposed check |
| `crs_ai_wording_enabled` | `True` | Local model or Claude API | Rewrites CRS comments; code keeps every number, unit, clause, page and standard; internal copy only. When the review's documents are not approved for the cloud model, it runs on the local model and says so (#838); a budget refusal is not replaced | Template wording |
| `crs_ai_wording_engine` | `ollama` | Local model or Claude API | Which engine words the CRS comments (#819, owner decision 12 Oct 2026: standards text may go to the cloud model under the approved-documents list). `claude` only under `REASONING_PROVIDER=per_task` or `claude`, with both egress flags and a key, and only for a review whose documents - its standards too - are ALL on the approved list; otherwise the local model | Not a switch-off: `crs_ai_wording_enabled` turns the wording off |
| `review_ai_check_enabled` | `True` | Local model or Claude API | The AI engineering check: concerns no rule covers, as drafts, never a verdict. On by default since #799. When the review's documents are not approved for the cloud model, it runs on the local model and says so (#838); a budget refusal is not replaced | No AI drafts |
| `review_ai_check_engine` | `ollama` | Claude API | The AI engineering check on the Claude API (#501, #819; owner decisions 12 Oct 2026). When every document of the review, its standards too, is on the approved list: the full check runs on Claude. Otherwise the check stays local and Claude gives a second, datasheet-only opinion. `claude` only under `REASONING_PROVIDER=per_task` or `claude`, with both egress flags and a key. Its packet carries the datasheet alone (no standard's text, no clause list) and declares only the submittal, so the approved-document list decides per datasheet | No second opinion; the check itself is unchanged |
| `answer_judge_enabled` | `False` | Local model or Claude API | Judges whether chat passages answer the question; may only downgrade | Structural checks only |
| `rule_parse_model_enabled` | `False` | Claude API | Turns a table or formula clause into a structured rule; every number must be on the page | Code parser only |
| `geometry_reader_enabled` | `False` | Claude API (vision) | The geometry reader's form path and the vision reader for pages no text reader can read | Text readers only |
| `vision_reader_engine` | `ollama` | Claude API (vision) | Which engine the page-image reader uses under `REASONING_PROVIDER=per_task` (#830). `claude`: page images of approved datasheets go to the Claude API (both egress flags and a key). `ollama` (default): none, since the local model reads no images; `geometry_reader_enabled` alone sends no image under `per_task` | No page image leaves under `per_task` |
| `geometry_table_reader_enabled` | `True` | No model (code) | The geometry reader's table path, cell by cell. Listed because it shares the reader family; it calls no AI | The rule readers alone |

**Done when:** this register is committed, the owner signs it once (a comment "approved" on #806), and the CI check passes.

