# Flags: one decision per on/off setting (#736)

Every boolean setting in `backend/app/config.py` is listed here once.
`scripts/check_flag_expiry.py` fails a pull request's CI when one is missing or a default
differs, and the **nightly** run on main fails when a **rollout** flag is past its
**decide by** date (order 46: a PR never turns red because of a date).

- **permanent**: a gate or operator setting that is meant to stay a switch. The note says why.
- **rollout**: a switch that exists while a path is proven. The decide-by date is at most 14 days
  after **since**. By that date the owner either makes it the default and removes the switch,
  removes the path, or extends it: a new `since` and a note saying why (one more window at most).

The rollout rows below were recorded on 2026-10-17 by #736, when this register was created; most
of these flags are older. Turning an AI step off, or replacing it with a rules-only path, still
needs the owner's written approval on #692 (CLAUDE.md top rule): expiry forces a decision, it
does not make one.

| Flag | Default | Kind | Since | Decide by | Note |
|---|---|---|---|---|---|
| `allow_unauthenticated_network_bind` | `False` | permanent | | | Safety override: serving the network with nobody signing in |
| `api_docs_enabled` | `False` | permanent | | | Route docs off the developer machine only on purpose |
| `ocr_use_cls` | `True` | permanent | | | OCR tuning measured in ADR-0005 |
| `answer_model_allow_remote_host` | `False` | permanent | | | Egress gate for the local-model URL (rule 1) |
| `ai_applicability_enabled` | `False` | rollout | 2026-10-17 | 2026-10-31 | AI "does not apply" proposals per requirement |
| `ai_division_scope_enabled` | `True` | rollout | 2026-10-20 | 2026-11-03 | Scope of a standard's division read from its own scope sentence (#1182); off, nothing changes; a part the model did not read is held for the engineer |
| `scope_type_words_rule_enabled` | `False` | rollout | 2026-10-26 | 2026-11-09 | Draft (order 210 FIX 2): a part whose construction words are all in the sheet's equipment type or title applies without asking the model; OFF until the owner says yes |
| `ai_answer_reuse_enabled` | `True` | permanent | | | Reuse of a stored local AI answer to the exact same question (#1221, order 205). Off for the final test before anything goes to a client: every page is read fresh |
| `ai_clause_checks_enabled` | `True` | rollout | 2026-10-17 | 2026-10-31 | AI check proposals for undecided clauses (#645) |
| `rule_auto_use_enabled` | `False` | rollout | 2026-10-17 | 2026-10-31 | Proven rule families used without an engineer |
| `match_enabled` | `True` | rollout | 2026-10-17 | 2026-10-31 | AI matcher (#794) |
| `geometry_reader_enabled` | `False` | rollout | 2026-10-17 | 2026-10-31 | Geometry reader form path and vision reader |
| `answer_judge_enabled` | `False` | rollout | 2026-10-17 | 2026-10-31 | Chat answer judge |
| `applicability_reasoning_enabled` | `True` | rollout | 2026-10-17 | 2026-10-31 | Scope reasoning (#757) |
| `review_debug` | `False` | permanent | | | Operator debug switch |
| `review_debug_detail` | `False` | permanent | | | Operator debug switch |
| `crs_ai_wording_enabled` | `True` | rollout | 2026-10-17 | 2026-10-31 | AI CRS wording |
| `geometry_table_reader_enabled` | `True` | rollout | 2026-10-17 | 2026-10-31 | Geometry table reader |
| `aligned_text_tables_enabled` | `False` | permanent | | | Keep tables with no ruling when they read like a grid (order 271.4). Set only for a standards re-extraction; a datasheet ingested with it on gets those tables too |
| `datasheet_office_input` | `False` | rollout | 2026-10-17 | 2026-10-31 | Index workbooks and Word datasheets |
| `docx_input_enabled` | `True` | rollout | 2026-10-17 | 2026-10-31 | Word input |
| `startup_warmup` | `True` | permanent | | | Operator setting: model warm-up at start |
| `onnx_cpu_arena_rerank` | `True` | permanent | | | Machine-specific memory tuning |
| `onnx_cpu_arena_embed` | `False` | permanent | | | Machine-specific memory tuning |
| `market_live_enabled` | `False` | permanent | | | Egress gate for the market lane (rule 1) |
| `market_allow_public_egress` | `False` | permanent | | | Egress gate for the market lane (rule 1) |
| `standards_reader_enabled` | `False` | permanent | | | Egress gate for the Claude lane (rule 1) |
| `standards_reader_allow_public_egress` | `False` | permanent | | | Egress gate for the Claude lane (rule 1) |
| `claude_approved_list_enforced` | `True` | permanent | | | Stays on; the switch exists for the test suite (#806 S3) |
| `chat_web_enabled` | `False` | permanent | | | Egress gate: chat web search through the market lane |
| `review_ai_check_enabled` | `True` | rollout | 2026-10-17 | 2026-10-31 | AI engineering check (#799) |
| `review_web_standards_enabled` | `False` | permanent | | | Egress gate: standards web search through the market lane |
| `rule_parse_model_enabled` | `False` | rollout | 2026-10-17 | 2026-10-31 | Model rule parser |
| `smtp_enabled` | `False` | permanent | | | Egress gate for SMTP (rule 1) |
| `smtp_starttls` | `True` | permanent | | | TLS mode; exactly one is on (#440) |
| `smtp_ssl` | `False` | permanent | | | TLS mode; exactly one is on (#440) |
