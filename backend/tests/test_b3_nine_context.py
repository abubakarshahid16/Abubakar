"""B3 role 2: the project context. Invented data only; no model (a fake `ask`)."""

from app import nine_context as nc

PG = "The vessel shall be designed for a corrosion allowance of three millimetres on all wetted parts."
STD = "Welding shall follow standard ZX-100 for all pressure parts."


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
    def ask(doc, chunk):
        return {
            "standards": [
                {
                    "name": "ZX-100",
                    "page": 1,
                    "quote": "Welding shall follow standard ZX-100",
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
        library=[{"id": "b1", "document_number": "ZX-100"}],
    )
    assert [s.name for s in note.standards] == ["ZX-100"]
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
    def ask(doc, chunk):
        return {
            "standards": [
                # the reviewer's probe: a name the paper never mentions, with an unrelated TRUE sentence from the page
                {
                    "name": "WX-777",
                    "page": 1,
                    "quote": "Welding shall follow standard ZX-100 for all pressure parts.",
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
