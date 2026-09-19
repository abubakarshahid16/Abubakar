"""The model tier of the matcher: it may CHOOSE, it may never NAME.

THE WHOLE SAFETY ARGUMENT IS IN THE PRE-FILTER, NOT IN THE PROMPT. Python
builds a shortlist of facts that are numeric, unit-comparable and not already
refused by an engineer; the model answers with an INDEX into that list, so the
worst it can do is pick the wrong entry. It never sees a value, a unit or a
page - so it cannot be pulled toward whichever pairing makes the arithmetic
come out cleanly - and it never sets a status, so a wrong pairing produces a
wrong QUESTION rather than a wrong verdict.

Every model call here is stubbed. The suite must answer the same whether or
not a model server happens to be running on the machine, and `conftest.py`
pins `match_enabled` off for everything that is not in this file.

No string in this file comes from the one real submittal in the corpus. The
holdout rule binds: a fixture written against that sheet's coordinates proves
the tier works on that sheet and nothing else.

Mutations: M135-M148, `python scripts/mutation_check.py --phase 11`.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app import (access, comparison, datasheets, db, model_transport,
                 requirements_3b, standards, submittal_review)
from app.config import settings
from app.main import app

NOW = "2026-09-19T00:00:00Z"


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "model.sqlite")
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    # THE TIER IS ON IN THIS FILE AND OFF EVERYWHERE ELSE. Turned on here
    # deliberately, against a stub, which is the claim these tests make.
    monkeypatch.setattr(settings, "match_enabled", True)
    monkeypatch.setattr(settings, "match_max_calls_per_run", 200)
    db.reset_connection(); db.init_db(); submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    yield
    access.set_user_resolver(None)
    db.reset_connection()


# --------------------------------------------------------------- the stub

class Stub:
    """A model that answers from a script and counts how often it was asked.

    `answers` is consumed in order; when it runs out the last one repeats, so
    a test that wants the same answer twice - which every stable pairing needs,
    because the tier asks twice - writes it once.
    """

    def __init__(self, *answers, raises: Exception | None = None,
                 raw: str | None = None):
        self.answers = list(answers)
        self.raises = raises
        self.raw = raw
        self.calls = 0
        self.prompts: list[str] = []
        self.bodies: list[dict] = []
        self.paths: list[str] = []
        self.timeouts: list[float | None] = []

    def __call__(self, path, body, timeout=None):
        self.calls += 1
        self.prompts.append(body["prompt"])
        self.bodies.append(body)
        self.paths.append(path)
        self.timeouts.append(timeout)
        if self.raises is not None:
            raise self.raises
        if self.raw is not None:
            return {"response": self.raw}
        answer = self.answers[min(self.calls - 1, len(self.answers) - 1)]
        choice, reason = answer
        choice_text = "null" if choice is None else str(choice)
        return {"response": '{"choice": %s, "reason": "%s"}' % (choice_text, reason)}


@pytest.fixture
def stub(monkeypatch):
    def install(*answers, **over):
        made = Stub(*answers, **over)
        monkeypatch.setattr(model_transport, "post_json", made)
        return made
    return install


# ------------------------------------------------------------- the fixtures
#
# SYNTHETIC THROUGHOUT. A clause about a quantity, and two datasheet fields in
# the same unit whose names are NOT contained in the clause subject - so
# containment misses and the model tier is the only thing that can pair them.

def requirement(**over):
    base = {"id": "req-1", "standard_document_id": "STD-001",
            "clause": "6.4.1", "requirement_type": "numeric_limit",
            "subject": "the maximum allowable working pressure of the vessel",
            "requirement_text":
                "The maximum allowable working pressure shall be 10 bar.",
            "operator": "<=", "raw_value": "10", "raw_unit": "bar"}
    return {**base, **over}


def fact(field_name, **over):
    base = {"id": f"fact-{field_name}", "submittal_document_id": "sub",
            "field_name": field_name, "raw_value": "8.5", "raw_unit": "bar",
            "unit": "bar", "section": "Design data", "page": 3}
    return {**base, **over}


CANDIDATES = [fact("shell design pressure"), fact("hydrotest pressure")]


# ================================================= what the model may see

def test_the_prompt_carries_no_value_no_unit_and_no_page():
    """§3. A MODEL THAT SEES THE NUMBERS CAN BE PULLED BY THEM.

    Shown a limit of 10 bar and a field reading 8.5 bar, a model has a reason
    to pair them that has nothing to do with whether they are the same
    quantity. Pairing is decided on wording alone, so the arithmetic does not
    cross.
    """
    rendered = comparison.build_prompt(
        requirement(), [fact("shell design pressure", raw_value="8.5",
                             raw_unit="bar", page=3)])

    assert "8.5" not in rendered, "a candidate value reached the model"
    assert "bar" not in rendered, "a unit reached the model"
    assert "page" not in rendered.lower(), "a page reference reached the model"
    assert "10" not in rendered, "the requirement's own limit reached the model"
    assert "<=" not in rendered, "the requirement's operator reached the model"
    # AND THE THINGS THAT MUST CROSS DID, so this cannot pass against a
    # prompt builder that returned an empty string.
    assert "shell design pressure" in rendered
    assert "STD-001" in rendered and "6.4.1" in rendered
    assert "Design data" in rendered


def test_the_clause_text_is_capped_at_four_hundred_characters():
    """A whole clause is context; a whole page is a budget defect."""
    rendered = comparison.build_prompt(
        requirement(subject="pressure " * 200), [fact("shell design pressure")])

    assert rendered.count("pressure ") < 200


def test_the_call_turns_thinking_off_as_the_answer_path_does(stub):
    """THE DEFECT THIS TEST EXISTS FOR, FOUND IN PREFLIGHT AND NOT IN A TEST.

    `settings.answer_model` is a thinking model. Asked with `format: "json"`
    and no `think` key, Ollama returns the JSON in a `thinking` field and
    leaves `response` an EMPTY STRING - so every call read as
    `model_malformed`, the tier paired nothing on any machine, and the review
    looked exactly like one where the model had simply declined every time.

    `answer.py:_call_model` had already set `think: False`. The tier is the
    second home of the same claim (CLAUDE.md rule 8).
    """
    asked = stub((0, "same quantity"))

    comparison.match_by_model(requirement(), CANDIDATES)

    body = asked.bodies[0]
    assert body["think"] is False, "a thinking model answers into `thinking`"
    assert body["format"] == "json"
    assert body["stream"] is False
    assert body["model"] == settings.answer_model
    assert body["options"]["temperature"] == 0
    assert body["options"]["seed"] == settings.match_seed
    assert asked.paths[0] == "/api/generate"
    assert asked.timeouts[0] == settings.match_timeout_seconds


# ==================================================== the candidate list

def test_a_categorical_fact_never_enters_the_candidate_list():
    """THE FALSE FRIEND IS EXCLUDED IN PYTHON, NOT ARGUED WITH IN THE PROMPT.

    A field answered "yes" has no quantity to compare, so there is nothing for
    a pressure limit to be about - whatever words the two happen to share.
    """
    candidates = comparison.candidate_facts(
        requirement(),
        [fact("pressure relieving device fitted", raw_value=None,
              raw_unit=None, unit=None),
         fact("shell design pressure")])

    assert [c["field_name"] for c in candidates] == ["shell design pressure"]


def test_a_blank_fact_never_enters_the_candidate_list():
    """A blank is a question for the vendor, never a value to be paired."""
    candidates = comparison.candidate_facts(
        requirement(),
        [fact("shell design pressure", raw_value=None, is_blank=1)])

    assert candidates == []


def test_a_fact_in_another_dimension_never_enters_the_candidate_list():
    """A length is not a pressure. Offering one is offering a wrong answer."""
    candidates = comparison.candidate_facts(
        requirement(),
        [fact("shell thickness", raw_value="12", raw_unit="mm", unit="mm"),
         fact("shell design pressure")])

    assert [c["field_name"] for c in candidates] == ["shell design pressure"]


def test_the_same_dimension_in_another_spelling_is_still_a_candidate():
    """THE GUARD ON THE RULE ABOVE. kPa and bar are the same quantity and
    `claims` converts between them exactly; a spelling test would drop the
    pairing the engine could actually evaluate, and the dimension test above
    would still pass."""
    candidates = comparison.candidate_facts(
        requirement(),
        [fact("shell design pressure", raw_value="850", raw_unit="kPa",
              unit="kPa")])

    assert [c["field_name"] for c in candidates] == ["shell design pressure"]


def test_a_unit_with_no_dimension_is_matched_on_its_spelling():
    """dB(A) HAS NO DIMENSION AT ALL, and neither does dB.

    A bare `unit_dimension` test would have made every unconvertible unit
    permanently ineligible for this tier while looking like the stricter rule -
    and those are the units this product's own worked example is written in.
    """
    noise = requirement(raw_unit="dB(A)", raw_value="85",
                        subject="the sound emitted by the equipment")

    assert [c["field_name"] for c in comparison.candidate_facts(
        noise, [fact("measured noise emission", raw_unit="dB(A)", unit=None)])
    ] == ["measured noise emission"]
    # And a different unconvertible unit is still refused.
    assert comparison.candidate_facts(
        noise, [fact("measured noise emission", raw_unit="dB", unit=None)]) == []


def test_a_rejected_pair_never_enters_the_candidate_list():
    """The engineer's correction reaches the model tier too.

    The POSITIVE is asserted first, so the test stands where the rejection can
    fail it rather than beside a shortlist that was empty anyway.
    """
    req = requirement()
    facts = [fact("shell design pressure")]
    assert comparison.candidate_facts(req, facts)

    comparison.reject_pair(req, facts[0], rejected_by=None,
                           reason="different vessel")

    assert comparison.candidate_facts(req, facts) == []


def test_the_shortlist_is_capped_at_twelve_longest_name_first():
    facts = [fact("p" * n) for n in range(1, 30)]

    candidates = comparison.candidate_facts(requirement(), facts)

    assert len(candidates) == comparison.MAX_CANDIDATES
    assert candidates[0]["field_name"] == "p" * 29


def test_one_candidate_is_still_asked_and_may_still_be_declined(stub):
    """§2. ONE SAME-DIMENSION FACT IS NOT EVIDENCE IT IS THE RIGHT ONE.

    A design pressure and an operating pressure are both bar. Auto-pairing
    whenever the shortlist has exactly one entry would turn "only one thing
    was even eligible" into a finding about the contractor.
    """
    asked = stub((None, "not the same quantity"))

    result = comparison.match_by_model(
        requirement(), [fact("shell design pressure")])

    assert asked.calls == 2, "a single candidate was paired without asking"
    assert result["fact"] is None, "a single candidate was paired anyway"


def test_no_candidates_means_no_call_at_all(stub):
    asked = stub((0, "same quantity"))

    result = comparison.match_by_model(requirement(), [])

    assert result["fact"] is None
    assert asked.calls == 0, "the model was asked about an empty shortlist"


# ================================================== the validation chain

def test_a_chosen_index_pairs_the_fact_it_points_at(stub):
    """THE POSITIVE. Without it every refusal test below would pass against a
    tier that never paired anything."""
    stub((0, "both describe the vessel design pressure"))

    result = comparison.match_by_model(requirement(), CANDIDATES)

    assert result["fact"]["field_name"] == "shell design pressure"
    assert result["matched_phrase"] == "shell design pressure"
    assert result["method"] == comparison.METHOD_MODEL_CHOICE
    assert result["reason"] == "both describe the vessel design pressure"


def test_an_index_out_of_range_is_no_match(stub):
    """The one thing an index cannot do is name a field that was not offered -
    unless nobody checks the range."""
    stub((7, "the seventh one"))

    result = comparison.match_by_model(requirement(), CANDIDATES)

    assert result["fact"] is None
    assert result["reason"] == comparison.MODEL_OUT_OF_RANGE


def test_a_negative_index_is_no_match(stub):
    """Python would accept -1 as a list index and pair the LAST candidate."""
    stub((-1, "not this one"))

    result = comparison.match_by_model(requirement(), CANDIDATES)

    assert result["fact"] is None
    assert result["reason"] == comparison.MODEL_OUT_OF_RANGE


def test_a_null_choice_is_no_match(stub):
    """THE SANCTIONED WAY TO DECLINE. If declining were not honoured the
    prompt would be inviting an answer it then ignored."""
    stub((None, "none of these is that quantity"))

    result = comparison.match_by_model(requirement(), CANDIDATES)

    assert result["fact"] is None
    assert result["reason"] == comparison.MODEL_DECLINED


def test_a_reason_naming_a_different_candidate_is_no_match(stub):
    """THE ONE-SENTENCE RULE, ENFORCED. It may CHOOSE, never NAME.

    When the index says one field and the sentence says another, the model has
    contradicted itself and there is no way to tell which it meant. Trusting
    the index would file a number against whichever of the two the reader was
    not shown.
    """
    stub((0, "hydrotest pressure is the matching field"))

    result = comparison.match_by_model(requirement(), CANDIDATES)

    assert result["fact"] is None
    assert result["reason"] == comparison.MODEL_NAMED_OTHER


def test_a_reason_naming_the_chosen_candidate_is_fine(stub):
    """The guard on the rule above: naming what it picked is not a
    contradiction, and a check that refused it would refuse every honest
    answer."""
    stub((0, "shell design pressure is the same quantity"))

    assert comparison.match_by_model(
        requirement(), CANDIDATES)["fact"] is not None


def test_a_body_that_is_not_json_is_no_match(stub):
    stub(raw="I think it is probably the first one.")

    result = comparison.match_by_model(requirement(), CANDIDATES)

    assert result["fact"] is None
    assert result["reason"] == comparison.MODEL_MALFORMED


def test_a_body_that_is_json_but_not_this_shape_is_no_match(stub):
    """`extra="forbid"`: a model that answered a DIFFERENT question has not
    answered this one."""
    stub(raw='{"answer": 0, "confidence": "high"}')

    result = comparison.match_by_model(requirement(), CANDIDATES)

    assert result["fact"] is None
    assert result["reason"] == comparison.MODEL_MALFORMED


def test_a_refused_or_timed_out_host_is_no_match(stub):
    """No model, no pairing, and the finding says which. Never an exception
    escaping into a review, and never a silent skip."""
    stub(raises=RuntimeError("connection refused"))

    result = comparison.match_by_model(requirement(), CANDIDATES)

    assert result["fact"] is None
    assert result["reason"] == comparison.MODEL_UNAVAILABLE


def test_two_calls_that_disagree_make_no_pairing(stub):
    """A MODEL THAT ANSWERS DIFFERENTLY HAS NOT DECIDED ANYTHING.

    Same prompt, same seed, temperature zero. Two different answers mean the
    pairing was a coin toss, and a coin toss must not become a finding.
    """
    asked = stub((0, "shell is the one"), (1, "hydrotest is the one"))

    result = comparison.match_by_model(requirement(), CANDIDATES)

    assert result["fact"] is None
    assert result["reason"] == comparison.MODEL_UNSTABLE
    assert asked.calls == 2, "the determinism check did not ask twice"


def test_the_agreed_answer_is_cached_for_the_run(stub):
    """The same question twice costs one pair of calls, not two."""
    asked = stub((0, "same quantity"))
    cache: dict = {}

    first = comparison.match_by_model(requirement(), CANDIDATES, cache=cache)
    second = comparison.match_by_model(requirement(), CANDIDATES, cache=cache)

    assert first["fact"]["id"] == second["fact"]["id"]
    assert asked.calls == 2, "the cache did not hold"


def test_the_budget_stops_the_tier_and_says_so(stub):
    """A PRE-FILTER DEFECT MUST NOT BECOME AN UNBOUNDED BILL.

    Past the budget the tier stops asking and every remaining requirement
    records `model_budget` - it does not fall silent, because "no pairing" and
    "we stopped looking" are different things to an engineer.
    """
    asked = stub((0, "same quantity"))
    budget = comparison._Budget(2)

    first = comparison.match_by_model(requirement(), CANDIDATES, budget=budget)
    second = comparison.match_by_model(
        requirement(clause="6.4.2"), CANDIDATES, budget=budget)

    assert first["fact"] is not None
    assert second["fact"] is None
    assert second["reason"] == comparison.MODEL_BUDGET
    assert asked.calls == 2


# =========================================== the tier inside a whole run

def _world(monkeypatch, *, subject: str, field_label: str,
           raw_value: str = "8.5 bar") -> tuple[str, str, str, frozenset]:
    """A standard, a submittal, one requirement, one fact, one run."""
    std, sub = "std-1", "sub-1"
    for doc_id, role in ((std, "COMPANY_STANDARD"), (sub, "CONTRACTOR_SUBMITTAL")):
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO documents (id,filename,sha256,size_bytes,"
                "stored_path,status,page_count,uploaded_at)"
                " VALUES (?,?,?,1,?,'ready',1,?)",
                (doc_id, f"{doc_id}.pdf", f"sha-{doc_id}", f"{doc_id}.pdf", NOW))
            conn.execute(
                "INSERT INTO document_classification"
                " (document_id,suggested_by,document_role) VALUES (?,?,?)",
                (doc_id, "test", role))
    chunks = {}
    for chunk_id, doc_id in (("sc", std), ("fc", sub)):
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO chunks (id,document_id,filename,ordinal,"
                "page_start,page_end,section,kind,text,token_count,"
                "content_hash,retrievable) VALUES (?,?,?,0,1,1,NULL,'prose',"
                "'x',1,?,1)", (chunk_id, doc_id, "f.pdf", f"h-{chunk_id}"))
        chunks[doc_id] = chunk_id
    standards.create_requirement(
        standard_document_id=std, chunk_id="sc",
        requirement_text="The maximum allowable working pressure shall be 10 bar.",
        source_text="The maximum allowable working pressure shall be 10 bar.",
        clause="6.4.1", page=1,
        structured={"subject": subject, "operator": "<=", "raw_value": "10",
                    "raw_unit": "bar", "requirement_type": "numeric_limit"})
    datasheets.create_fact(
        submittal_document_id=sub, chunk_id="fc", field_label=field_label,
        raw_value=raw_value, page=1)
    run_id = str(uuid.uuid4())
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO review_runs (id,submittal_document_id,status,"
            "created_at,updated_at) VALUES (?,?,'pending',?,?)",
            (run_id, sub, NOW, NOW))
        conn.execute(
            "INSERT INTO review_applicable_standards (id,review_run_id,"
            "standard_document_id,selection_reason,selection_method,included,"
            "created_at) VALUES (?,?,?,'cited','referenced',1,?)",
            (str(uuid.uuid4()), run_id, std, NOW))
    return std, sub, run_id, frozenset({std, sub})


def test_a_model_paired_finding_is_labelled_medium_and_says_who_paired_it(
        stub, monkeypatch):
    """§6. RULE, MODEL AND HUMAN MUST NOT READ ALIKE.

    An engineer reading a finding has to be able to tell that the pairing
    under it was a guess nobody has confirmed.
    """
    stub((0, "both describe the vessel working pressure"))
    _std, _sub, run, scope = _world(
        monkeypatch, subject="the maximum allowable working pressure",
        field_label="Shell design pressure")

    result = comparison.run_comparison(run, allowed_document_ids=scope)

    assert result["model_matches"] == 1
    found = result["findings"][0]
    assert found["match_method"] == comparison.METHOD_MODEL_CHOICE
    assert found["matched_phrase"] == "shell design pressure"
    assert found["confidence"] == "medium"
    assert found["ai_rationale"].startswith(comparison.MODEL_PAIR_PREFIX)
    assert "both describe the vessel working pressure" in found["ai_rationale"]
    # THE MODEL DID NOT SET THE STATUS. 8.5 <= 10 is arithmetic.
    assert found["compliance_status"] == comparison.COMPLIANT


def test_containment_takes_precedence_and_the_model_is_not_asked(
        stub, monkeypatch):
    """THE ORDER IS THE POINT. A deterministic pairing is better evidence than
    a model's, so the model is never consulted where containment already
    decided."""
    asked = stub((0, "should never be asked"))
    _std, _sub, run, scope = _world(
        monkeypatch, subject="the shell design pressure shall not exceed",
        field_label="Shell design pressure")

    result = comparison.run_comparison(run, allowed_document_ids=scope)

    assert asked.calls == 0, "the model was asked about a pairing already made"
    assert result["findings"][0]["match_method"] == comparison.METHOD_CONTAINMENT


def test_a_tie_never_reaches_the_model(stub, monkeypatch):
    """AMBIGUOUS_MATCH IS A HUMAN QUESTION.

    Two equally specific fields are named inside one requirement. Handing that
    to a model replaces "we could not tell" with an answer nobody checked, and
    the finding would read like any other.
    """
    asked = stub((0, "should never be asked"))
    _std, sub, run, scope = _world(
        monkeypatch,
        subject="the shell design pressure and the crown design pressure",
        field_label="Shell design pressure")
    datasheets.create_fact(
        submittal_document_id=sub, chunk_id="fc",
        field_label="Crown design pressure", raw_value="8.4 bar", page=1)

    result = comparison.run_comparison(run, allowed_document_ids=scope)

    assert asked.calls == 0, "a tie was handed to the model"
    assert result["findings"][0]["compliance_status"] == \
        comparison.NEEDS_ENGINEER_REVIEW


def test_a_declined_pairing_leaves_missing_information_and_says_why(
        stub, monkeypatch):
    stub((None, "no candidate is that quantity"))
    _std, _sub, run, scope = _world(
        monkeypatch, subject="the maximum allowable working pressure",
        field_label="Shell design pressure")

    result = comparison.run_comparison(run, allowed_document_ids=scope)

    found = result["findings"][0]
    assert found["compliance_status"] == comparison.MISSING_INFORMATION
    assert found["match_method"] is None
    assert comparison.MODEL_DECLINED in found["ai_rationale"]


def test_an_unavailable_model_says_so_on_the_finding(stub, monkeypatch):
    """"the model was never asked" and "the model was asked and could not
    answer" must not read alike."""
    stub(raises=RuntimeError("connection refused"))
    _std, _sub, run, scope = _world(
        monkeypatch, subject="the maximum allowable working pressure",
        field_label="Shell design pressure")

    result = comparison.run_comparison(run, allowed_document_ids=scope)

    found = result["findings"][0]
    assert found["compliance_status"] == comparison.MISSING_INFORMATION
    assert comparison.MODEL_UNAVAILABLE in found["ai_rationale"]


def test_the_tier_can_be_turned_off_and_the_finding_says_it_was(
        stub, monkeypatch):
    """`match_enabled=False` is an OFF SWITCH, not a silence.

    A review run with the tier off must not read like a review where the model
    looked and found nothing.
    """
    asked = stub((0, "should never be asked"))
    monkeypatch.setattr(settings, "match_enabled", False)
    _std, _sub, run, scope = _world(
        monkeypatch, subject="the maximum allowable working pressure",
        field_label="Shell design pressure")

    result = comparison.run_comparison(run, allowed_document_ids=scope)

    assert asked.calls == 0
    assert comparison.MODEL_DISABLED in result["findings"][0]["ai_rationale"]
    # AND THE SAME FIXTURE PAIRS WITH THE TIER ON, so this is not passing
    # because the requirement was never eligible.
    monkeypatch.setattr(settings, "match_enabled", True)
    again = comparison.run_comparison(run, allowed_document_ids=scope)
    assert again["model_matches"] == 1


def test_the_budget_stops_a_whole_run_and_marks_the_rest(stub, monkeypatch):
    asked = stub((0, "same quantity"))
    monkeypatch.setattr(settings, "match_max_calls_per_run", 0)
    _std, _sub, run, scope = _world(
        monkeypatch, subject="the maximum allowable working pressure",
        field_label="Shell design pressure")

    result = comparison.run_comparison(run, allowed_document_ids=scope)

    assert asked.calls == 0
    assert result["model_reasons"].get(comparison.MODEL_BUDGET) == 1
    assert comparison.MODEL_BUDGET in result["findings"][0]["ai_rationale"]


def test_a_model_paired_table_row_is_still_refused_and_quoted(
        stub, monkeypatch):
    """§9. THE MATCHER MAY PAIR A TABLE ROW; `compare` STILL CANNOT EVALUATE ONE.

    Pairing tells the engineer WHICH submitted value the row bears on. It does
    not turn a lookup boundary into a limit, and the unit guard must not
    overwrite the real reason with a unit complaint.
    """
    stub((0, "the row is about this field"))
    _std, _sub, run, scope = _world(
        monkeypatch, subject="the maximum allowable working pressure",
        field_label="Shell design pressure")
    with db.connect() as conn:
        conn.execute("UPDATE standard_requirements SET requirement_type = ?",
                     (requirements_3b.TABLE_ROW,))

    result = comparison.run_comparison(run, allowed_document_ids=scope)

    found = result["findings"][0]
    assert found["match_method"] == comparison.METHOD_MODEL_CHOICE
    assert found["compliance_status"] == comparison.NEEDS_ENGINEER_REVIEW
    assert comparison.TABLE_ROW_REASON in found["ai_rationale"]


# ================================================= the engineer's actions

def _signed_in(monkeypatch, documents, user_id: str = "eng-1") -> str:
    """An engineer with a NAME and the grants to see these documents.

    `confirmed_by` references `users(id)`: the schema itself refuses an
    invented confirmer, so a confirmation is only possible where there is a
    real identity to attribute it to. Under `disabled` there is none, which is
    why this fixture turns authentication ON rather than confirming anonymously.
    """
    with db.connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (id,email,display_name,password_hash,"
            "created_at) VALUES (?,?,?,'h',?)",
            (user_id, f"{user_id}@e.test", "Engineer", NOW))
        role = f"role_{user_id}"
        conn.execute("INSERT OR IGNORE INTO roles (id,name,description,"
                     "created_at) VALUES (?,?,?,?)", (role, role, role, NOW))
        conn.execute("INSERT OR IGNORE INTO user_roles (user_id,role_id,"
                     "granted_at) VALUES (?,?,?)", (user_id, role, NOW))
        for document_id in documents:
            conn.execute(
                "INSERT OR IGNORE INTO document_role_access (document_id,"
                "role_id,permission,granted_at) VALUES (?,?,'read',?)",
                (document_id, role, NOW))
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_REQUIRED)
    access.set_user_resolver(lambda request: user_id)
    return user_id



def test_confirming_through_the_patch_route_names_the_caller_not_the_body(
        stub, monkeypatch):
    """CONFIRMATION THAT CAN NAME SOMEONE ELSE IS WORTH NOTHING.

    `confirmed_by` comes from the authenticated scope. The body carries a
    flag, never a name, and a name sent anyway must not reach the column.
    """
    stub((0, "both describe the vessel working pressure"))
    _std, _sub, run, scope = _world(
        monkeypatch, subject="the maximum allowable working pressure",
        field_label="Shell design pressure")
    finding_id = comparison.run_comparison(
        run, allowed_document_ids=scope)["findings"][0]["id"]

    engineer = _signed_in(monkeypatch, scope)
    body = TestClient(app).patch(
        f"/api/reviews/findings/{finding_id}",
        json={"confirmed": True, "confirmed_by": "somebody"})

    assert body.status_code == 200, body.text
    row = db.connect().execute(
        "SELECT confirmed_by, confirmed_at FROM review_findings WHERE id = ?",
        (finding_id,)).fetchone()
    assert row["confirmed_by"] == engineer, "the body set the confirmer"
    assert row["confirmed_at"], "a confirmation with no time is not a record"


def test_a_body_naming_a_confirmer_cannot_set_one(stub, monkeypatch):
    """THE PROTECTION IS THE SCHEMA, NOT THE ROUTE.

    `ReviewFindingUpdate` has no `confirmed_by` field, so a client naming a
    confirmer is naming a field that does not exist and nothing reaches the
    column - whether or not the same request also asks to confirm. Add the
    field and the body can sign a pairing in another engineer's name, which is
    the one thing a confirmation must never allow.
    """
    stub((0, "both describe the vessel working pressure"))
    _std, _sub, run, scope = _world(
        monkeypatch, subject="the maximum allowable working pressure",
        field_label="Shell design pressure")
    finding_id = comparison.run_comparison(
        run, allowed_document_ids=scope)["findings"][0]["id"]

    answered = TestClient(app).patch(f"/api/reviews/findings/{finding_id}",
                                     json={"confirmed_by": "somebody"})

    assert answered.status_code == 200, answered.text
    assert db.connect().execute(
        "SELECT confirmed_by FROM review_findings WHERE id = ?",
        (finding_id,)).fetchone()["confirmed_by"] is None, \
        "a request body set the confirmer"


def test_a_confirmation_with_no_identity_is_refused(stub, monkeypatch):
    """SILENTLY DOING NOTHING WOULD BE WORSE THAN REFUSING.

    `confirmed_by` references `users(id)` and `review.update` drops a None, so
    an anonymous confirmation would answer 200 having recorded nothing - and
    the engineer would believe the pairing was signed for and protected from
    the next re-run.
    """
    stub((0, "both describe the vessel working pressure"))
    _std, _sub, run, scope = _world(
        monkeypatch, subject="the maximum allowable working pressure",
        field_label="Shell design pressure")
    finding_id = comparison.run_comparison(
        run, allowed_document_ids=scope)["findings"][0]["id"]

    refused = TestClient(app).patch(f"/api/reviews/findings/{finding_id}",
                                    json={"confirmed": True})

    assert refused.status_code == 401
    assert db.connect().execute(
        "SELECT confirmed_by FROM review_findings WHERE id = ?",
        (finding_id,)).fetchone()["confirmed_by"] is None
    # AND AN ORDINARY EDIT STILL WORKS ANONYMOUSLY, so this is not passing
    # because the route stopped accepting anything.
    assert TestClient(app).patch(f"/api/reviews/findings/{finding_id}",
                                 json={"severity": "minor"}).status_code == 200


def test_a_confirmed_model_pairing_survives_a_re_run(stub, monkeypatch):
    """THROUGH `run_comparison`, WHICH IS WHERE `replace` ACTUALLY DELETES."""
    stub((0, "both describe the vessel working pressure"))
    _std, _sub, run, scope = _world(
        monkeypatch, subject="the maximum allowable working pressure",
        field_label="Shell design pressure")
    kept = comparison.run_comparison(
        run, allowed_document_ids=scope)["findings"][0]["id"]
    _signed_in(monkeypatch, scope)
    assert TestClient(app).patch(
        f"/api/reviews/findings/{kept}",
        json={"confirmed": True}).status_code == 200

    comparison.run_comparison(run, allowed_document_ids=scope, replace=True)

    rows = db.connect().execute(
        "SELECT id, confirmed_by FROM review_findings WHERE review_run_id = ?",
        (run,)).fetchall()
    assert kept in {r["id"] for r in rows}, \
        "a re-run destroyed a confirmed pairing"


def test_rejecting_a_pair_through_the_route_stops_it_being_proposed_again(
        stub, monkeypatch):
    """THE CORRECTION LOOP, END TO END.

    The pairing is made, an engineer refuses it, and the next run does not
    make it again. The first run's pairing is asserted, so the test stands
    where the rejection can fail it.
    """
    stub((0, "both describe the vessel working pressure"))
    _std, _sub, run, scope = _world(
        monkeypatch, subject="the maximum allowable working pressure",
        field_label="Shell design pressure")
    first = comparison.run_comparison(run, allowed_document_ids=scope)
    assert first["model_matches"] == 1

    response = TestClient(app).post(
        "/api/reviews/pairs/reject",
        json={"finding_id": first["findings"][0]["id"],
              "reason": "a different vessel"})

    assert response.status_code == 200, response.text
    again = comparison.run_comparison(run, allowed_document_ids=scope)
    assert again["model_matches"] == 0
    assert again["findings"][0]["match_method"] is None


def test_rejecting_a_finding_with_no_pairing_is_refused(stub, monkeypatch):
    """A rejection against nothing would sit in the table forever matching no
    pair, and the engineer would believe a correction had been recorded."""
    stub((None, "no candidate is that quantity"))
    _std, _sub, run, scope = _world(
        monkeypatch, subject="the maximum allowable working pressure",
        field_label="Shell design pressure")
    unpaired = comparison.run_comparison(
        run, allowed_document_ids=scope)["findings"][0]

    assert unpaired["fact_id"] is None
    response = TestClient(app).post("/api/reviews/pairs/reject",
                                    json={"finding_id": unpaired["id"]})

    assert response.status_code == 422


def test_an_out_of_scope_caller_gets_the_same_answer_as_a_missing_finding(
        stub, monkeypatch):
    """CLAUDE.md RULE 5. A caller who may not read a finding must not be able
    to learn it exists by being told they may not touch it."""
    stub((0, "both describe the vessel working pressure"))
    _std, _sub, run, scope = _world(
        monkeypatch, subject="the maximum allowable working pressure",
        field_label="Shell design pressure")
    finding_id = comparison.run_comparison(
        run, allowed_document_ids=scope)["findings"][0]["id"]

    refused = comparison.reject_pair_for_finding(
        finding_id, rejected_by=None, reason=None,
        allowed_document_ids=frozenset())
    absent = comparison.reject_pair_for_finding(
        str(uuid.uuid4()), rejected_by=None, reason=None,
        allowed_document_ids=scope)

    assert refused is None and absent is None, \
        "the two answers must be indistinguishable"
    # AND THE SAME CALL IN SCOPE SUCCEEDS, so this is not passing because
    # rejection stopped working altogether.
    assert comparison.reject_pair_for_finding(
        finding_id, rejected_by=None, reason=None,
        allowed_document_ids=scope) is not None


def test_an_unknown_field_in_the_rejection_body_is_refused():
    """`extra="forbid"`: a client sending `requirement_id` believes it decided
    which pair was rejected. It did not."""
    assert TestClient(app).post(
        "/api/reviews/pairs/reject",
        json={"finding_id": "x", "requirement_id": "y"}).status_code == 422
