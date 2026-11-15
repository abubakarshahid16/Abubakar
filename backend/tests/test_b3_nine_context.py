"""B3 role 2: the project context. Invented data only; no model (a fake `ask`)."""

from app import nine_context as nc

PG = "The vessel shall be designed for a corrosion allowance of three millimetres on all wetted parts."
STD = "Welding shall follow API 610 for all pressure parts."


def paper(did, kind, shown=True, accessible=True, register=False, pages=None):
    return nc.ProjectPaper(
        did,
        kind,
        pages if pages is not None else {1: STD, 2: PG},
        shown,
        accessible,
        register,
    )


def go(
    papers,
    ask,
    engine="claude",
    rows=(),
    paper_row=None,
    points=None,
    values=None,
    library=(),
):
    return nc.run(
        "r1",
        project="P1",
        papers=papers,
        paper_row=paper_row or {"document_id": "d0"},
        rows=rows,
        earlier_points=points,
        new_values=values or {},
        library=list(library),
        engine=engine,
        ask=ask,
    )


def test_nothing_held_gives_five_lines_and_no_call():
    calls = []
    note, tally = go([], lambda *a: calls.append(a))
    assert calls == [] and tally.windows == 0
    assert [n.what for n in note.not_available] == list(nc.WHATS)
    assert note.documents_read == ()


def test_unfound_quote_is_dropped_and_found_quote_kept():
    def ask(paper, pages):
        return {
            "standards": [
                {
                    "name": "API 610",
                    "page": 1,
                    "quote": "Welding shall follow API 610",
                },
                {
                    "name": "QQ-9",
                    "page": 1,
                    "quote": "Painting shall follow QQ-9 in all cases",
                },
            ],
            "overrides": [
                {
                    "subject": "corrosion allowance",
                    "page": 2,
                    "quote": "corrosion allowance of three millimetres",
                },
                {
                    "subject": "wall",
                    "page": 1,
                    "quote": "corrosion allowance of three millimetres",
                },
            ],
        }

    note, tally = go(
        [paper("d1", nc.KIND_SPEC)],
        ask,
        library=[{"id": "b1", "document_number": "API 610"}],
    )
    assert [s.name for s in note.standards] == ["API 610"]
    assert (
        note.standards[0].held
        and note.standards[0].book_id == "b1"
        and note.standards[0].source.verified
    )
    assert [o.subject for o in note.overrides] == ["corrosion allowance"]
    assert tally.standards_dropped == 1 and tally.overrides_dropped == 1


def test_contract_not_read_under_automatic_but_under_claude():
    c = paper("c1", nc.KIND_CONTRACT)
    note, _ = go([c], lambda *a: {}, engine="automatic")
    assert "c1" not in note.documents_read
    assert (
        next(n for n in note.not_available if n.what == "contract").why
        == nc.WHY_AUTOMATIC
    )
    note, _ = go([c], lambda *a: {}, engine="claude")
    assert "c1" in note.documents_read


def test_register_never_listed_and_gates_counted_not_named():
    adm = nc.admit(
        [
            paper("g1", nc.KIND_SPEC, register=True),
            paper("g2", nc.KIND_SPEC, shown=False),
            paper("g3", nc.KIND_RELATED, accessible=False),
        ],
        engine="claude",
    )
    assert adm.readable == ()
    text = repr(adm)
    assert "g1" not in text and "g2" not in text and "g3" not in text
    assert adm.counts[nc.WHY_NOT_SHOWN] == 1 and adm.counts[nc.WHY_NO_ACCESS] == 1


def test_failed_window_keeps_code_result_and_is_counted():
    def boom(*a):
        raise RuntimeError("x")

    note, tally = go([paper("d1", nc.KIND_SPEC)], boom)
    assert note.standards == () and tally.failed_windows == tally.windows == 1


def test_earlier_revision_and_follow_up_by_code():
    rows = [
        {"document_id": "old", "superseded_by": "d0", "revision": "A", "run_id": "r0"}
    ]
    pts = lambda d: [  # noqa: E731
        {
            "point_id": "p1",
            "field": "design pressure",
            "value": "10 bar",
            "status_word": "Fail",
            "engineer_decision": "keep",
        },
        {"point_id": "p2", "field": "tag", "value": "T-1", "status_word": "Fail"},
        {"point_id": "p3", "field": "weight", "value": "5 kg", "status_word": "Fail"},
    ]
    note, _ = go(
        [],
        None,
        rows=rows,
        points=pts,
        values={"design pressure": " 10  BAR", "tag": "T-2"},
    )
    assert note.earlier.document_id == "old"
    assert [c.still_open for c in note.earlier.comments] == [True, False, None]
    assert (
        note.earlier.comments[0].engineer_decision == "keep"
        and note.earlier.comments[0].status_word == "Fail"
    )
    assert [n.what for n in note.not_available] == [
        "contract",
        "project specification",
        "related papers",
    ]


def test_two_equal_earlier_candidates_means_none():
    rows = [
        {"document_id": "a", "superseded_by": "d0"},
        {"document_id": "b", "superseded_by": "d0"},
    ]
    assert nc.earlier_revision({"document_id": "d0"}, rows) is None


def test_no_client_words_in_source():
    import pathlib

    src = pathlib.Path(nc.__file__).read_text().lower()
    for w in ("saes", "api 6"):
        assert w not in src


def test_a_name_not_in_its_quote_and_a_subject_not_in_its_quote_are_dropped():
    def ask(paper, pages):
        return {
            "standards": [
                # the reviewer's probe: a name the paper never mentions, with an unrelated TRUE sentence from the page
                {
                    "name": "WX-777",
                    "page": 1,
                    "quote": "Welding shall follow API 610 for all pressure parts.",
                },
            ],
            "overrides": [
                {
                    "subject": "paint colour",
                    "page": 2,
                    "quote": "corrosion allowance of three millimetres",
                },
            ],
        }

    note, tally = go([paper("d1", nc.KIND_SPEC)], ask)
    assert note.standards == () and note.overrides == ()
    assert tally.standards_dropped == 1 and tally.overrides_dropped == 1


def test_the_register_is_found_by_checksum_and_an_unreadable_block_list_blocks(
    monkeypatch,
):
    from app import claude_approved

    monkeypatch.setattr(claude_approved, "blocked_by_name", lambda n: False)
    monkeypatch.setattr(
        claude_approved, "blocked_hashes", lambda: frozenset({"ab" * 32})
    )
    assert nc.is_register("Renamed copy.pdf", "AB" * 32)
    assert not nc.is_register("Renamed copy.pdf", "cd" * 32)

    def boom():
        raise claude_approved.BlockListUnreadable("x")

    monkeypatch.setattr(claude_approved, "blocked_hashes", boom)
    assert nc.is_register("Any.pdf", "cd" * 32)


def test_an_unscored_related_paper_is_not_read_under_automatic_but_under_claude():
    p = nc.ProjectPaper("r1", nc.KIND_RELATED, {1: STD}, True, True, False, False)
    assert nc.admit([p], engine="automatic").readable == ()
    assert nc.admit([p], engine="claude").readable == (p,)


def _kept(name, quote, subject=None, ref=None):
    pages = {1: quote}
    p = nc.ProjectPaper("d1", nc.KIND_SPEC, pages, True, True)
    raw = {"standards": [{"name": name, "page": 1, "quote": quote}]}
    if subject:
        raw = {
            "overrides": [
                {"subject": subject, "page": 1, "quote": quote, "general_ref": ref}
            ]
        }
    standards, overrides, _t = nc.read_papers([p], lambda *a: raw, [], engine="claude")
    return standards or overrides


def test_a_standard_is_kept_only_when_its_quote_cites_it_by_whole_tokens():
    assert not _kept(
        "API", "A rapid test of the flow was run on site"
    )  # "api" inside "rapid"
    assert not _kept(
        "ISO", "The isolation valve is closed during work"
    )  # "iso" inside "isolation"
    assert not _kept(
        "610", "The pressure shall be 1610 kPa at the inlet"
    )  # "610" inside "1610"
    assert not _kept(
        "API 610", "The rapid 610 mm flow is measured daily"
    )  # the two parts apart
    assert _kept(
        "API 610", "The pump shall follow API 610 for its design"
    )  # a true citation
    assert _kept(
        "API Std 610", "The pump shall follow API 610 for its design"
    )  # another spelling, same standard


def test_an_override_needs_whole_words_and_an_anchor_that_common_words_cannot_give():
    common = "The vessel shall be painted with the approved colour on all outer parts"
    assert not _kept(
        "", common, subject="painted colour outer parts"
    )  # whole words but no anchor
    assert not _kept(
        "", "The design pressure is shown elsewhere", subject="pressure designs"
    )  # not a whole word
    assert _kept(
        "",
        "The design pressure shall be 12 bar at the inlet",
        subject="design pressure",
    )  # a field name of the app
    assert not _kept(
        "",
        "Clause 4.2.1 requires the outer parts to be painted",
        subject="painted parts",
    )  # a clause number alone
    assert not _kept(
        "", "Per API 610 the outer parts shall be painted", subject="painted parts"
    )  # a citation that is not the one overridden
    assert _kept(
        "",
        "Per API 610 the outer parts shall be painted",
        subject="painted parts",
        ref="API Std 610",
    )  # the citation is the standard the override says it overrides


def test_a_clause_number_alone_is_not_an_anchor_for_an_override():
    quote = "The pump design is described in the data book, see 3.2 for loads"
    assert not _kept("", quote, subject="pump design")
    assert _kept(
        "", "The design pressure shall be 12 bar, see 3.2", subject="design pressure"
    )  # field name in both


def test_a_standard_of_an_unknown_family_is_counted_apart_from_a_dropped_name():
    quote = "Fabrication shall follow ZX-100 for all parts"
    p = nc.ProjectPaper("d1", nc.KIND_SPEC, {1: quote}, True, True)
    raw = {
        "standards": [
            {"name": "ZX-100", "page": 1, "quote": quote},
            {"name": "QQ-9", "page": 1, "quote": quote},
        ]
    }
    standards, _o, tally = nc.read_papers([p], lambda *a: raw, [], engine="claude")
    assert (
        standards == ()
        and tally.standards_unrecognised == 1
        and tally.standards_dropped == 1
    )
    lines = nc.count_lines(tally)
    assert "1 named standards not recognised by the app's reader" in lines
    assert (
        nc.produced(
            nc.build_note(
                "r",
                project=None,
                admission=nc.admit([], engine="claude"),
                standards=(),
                overrides=(),
                earlier=None,
                earlier_held=False,
            ),
            tally,
        )["standards_unrecognised"]
        == 1
    )


def test_the_standard_is_named_by_the_citation_as_printed():
    quote = "Pumps shall conform to API Std 610 in full"
    p = nc.ProjectPaper("d1", nc.KIND_SPEC, {1: quote}, True, True)
    raw = {"standards": [{"name": "API 610", "page": 1, "quote": quote}]}
    standards, _o, _t = nc.read_papers([p], lambda *a: raw, [], engine="claude")
    assert [s.name for s in standards] == ["API Std 610"]
