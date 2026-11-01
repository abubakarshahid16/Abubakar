"""Settings kept out of `config.py` (it may only shrink): a base of `config.Settings`.

Clause review (#1477) and nothing-read (#1495) fields. They are read from the
environment exactly like every other setting (`Settings` inherits them).
"""

from pydantic import BaseModel, Field


class SettingsExt(BaseModel):
    #: AI clause review of a PROCEDURE or SPECIFICATION submittal (`clause_review.py`):
    #: one requirement at a time against the 4 most relevant small passages of the
    #: submittal, the LOCAL model only (owner decision D1: no Claude here), every
    #: quote verified by code on the stored page text, never a verdict. OFF: nothing
    #: changes. Env: CLAUSE_REVIEW_ENABLED.
    clause_review_enabled: bool = False
    #: The time allowed per page of the document; the run stops cleanly when
    #: pages x this is spent and names the requirements not reviewed. Measured
    #: minutes per page is recorded on the run. Env: CLAUSE_REVIEW_SECONDS_PER_PAGE.
    clause_review_seconds_per_page: float = Field(90.0, gt=0)
    #: At most this many requirements per run (the rest are named as not reviewed).
    #: Env: CLAUSE_REVIEW_MAX_REQUIREMENTS.
    clause_review_max_requirements: int = Field(60, ge=1)
    #: Seconds one local call may take, and its output cap (thinking is on, and
    #: its tokens count). Env: CLAUSE_REVIEW_CALL_TIMEOUT_S, CLAUSE_REVIEW_NUM_PREDICT.
    clause_review_call_timeout_s: float = Field(600.0, gt=0)
    clause_review_num_predict: int = Field(6000, ge=512)
    #: #1495 (kept here so `config.py` does not grow): a review whose submittal has
    #: no current fact AND no page text or reading ends failed "nothing read", never
    #: completed. Pages read with no datasheet field are NOT failed. OFF: nothing
    #: changes. Env: NOTHING_READ_FAILS_ENABLED.
    nothing_read_fails_enabled: bool = False

    #: #1474: the document KIND (router table `document_kinds`) chooses the rule set: a
    #: document whose kind is anything but datasheet gets no equipment datasheet checklist and
    #: no equipment-type standards, and its equipment type drives no review step (`kind_rules.py`).
    #: unknown / undecided keeps today's behaviour, marked. OFF: nothing changes.
    #: Env: KIND_CHOOSES_RULES_ENABLED.
    kind_chooses_rules_enabled: bool = False
    #: #1478 pump kit PREPARATION: append the DRAFT pump cards of `reference/pump_kit_draft.json`
    #: (a held standard requires the value, not already in the checklist) to the Centrifugal Pump
    #: checklist. Draft only, never decides, local only. OFF: nothing changes. Env: PUMP_KIT_DRAFT_ENABLED.
    pump_kit_draft_enabled: bool = False
    #: #1503 CRS EXPORT QUALITY (`crs_export_quality.py`): one row per section + clause, no
    #: empty rows, a page or "page not found (reason)" on every row, comments at most 350
    #: characters, Reasoning and Rule trust on an Internal sheet the contractor copy lacks,
    #: the standards sheet without "Considered, not applied", "not in your library" by kind,
    #: Priority from the fixed list. EXPORT ONLY: no verdict, status or finding changes.
    #: OFF: nothing changes. Env: CRS_EXPORT_QUALITY_ENABLED.
    crs_export_quality_enabled: bool = False
