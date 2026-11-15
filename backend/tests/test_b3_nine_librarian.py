"""The Librarian (role 3): which rule books and chapters are read. INVENTED books and rules; pure code, no database, no model."""

from __future__ import annotations

from app import nine_chapters as NC
from app import nine_librarian as L
from tests.test_b3_nine_chapters import _numbered, _pages, _para


def _cut(book_id="b1", tokens=1_500):
    return NC.cut(book_id, _numbered(), max_tokens=tokens)


def _books(**kw):
    return [
        L.BookInput("b1", _cut("b1"), why=("cited by the paper",), **kw),
        L.BookInput("b2", _cut("b2"), why=("governs the equipment type",)),
    ]


def _items(rl, book):
    return next(b for b in rl.books if b.book_id == book).items


def _plan(run_id, books, **kw):
    """plan_reading with every book on the shown list and inside the access, unless the test says otherwise (the default is deny)."""
    ids = {b.book_id for b in books}
    kw.setdefault("shown", ids)
    kw.setdefault("allowed", ids)
    return L.plan_reading(run_id, books, **kw)


def test_a_chapter_holding_a_chosen_rule_is_found_by_its_clause_or_by_its_page_and_ranked_first():
    books = _books()
    rules = [
        L.RuleRef("b1", "2.2", 2, 1),
        L.RuleRef("b1", "9.9", 3, 2),
    ]  # clause 9.9 is unknown: the page finds its chapter
    rl = _plan("r1", books, rules=rules, engine="claude")
    it = _items(rl, "b1")
    ids = [i.chapter.chapter_id for i in it]
    assert "2.2" in ids and all(i.chosen for i in it)
    first = it[0]
    assert (
        first.rank == 1
        and L.WHY_RULE in first.why
        and first.chapter.chapter_id == "2.2"
    )
    assert all(L.WHY_RULE in i.why for i in it)
    assert (
        _items(rl, "b2") == ()
    )  # no rule, no citation, no title match in b2: not a candidate


def test_why_each_chapter_is_chosen_cited_context_and_title_and_rule_chapters_rank_before_the_others():
    books = _books()
    rl = _plan(
        "r1", books, rules=[L.RuleRef("b1", "2.1", 2, 1)], cited=[L.ClauseRef("b1", "3.1")], context=[L.ClauseRef("b2", "4")],
        equipment_words=["testing"],
    )  # fmt: skip
    why = {(b.book_id, i.chapter.chapter_id): i.why for b in rl.books for i in b.items}
    assert L.WHY_RULE in why[("b1", "2.1")] and any(
        L.WHY_CITED in w or L.WHY_TITLE in w
        for w in why.get(("b1", "3 to 4"), ()) + why.get(("b1", "3"), ())
    )
    ranks = [i.rank for b in rl.books for i in sorted(b.items, key=lambda x: x.rank)]
    assert ranks == sorted(ranks) and len(set(ranks)) == len(ranks)
    top = min((i for b in rl.books for i in b.items), key=lambda i: i.rank)
    assert L.WHY_RULE in top.why


def test_a_book_not_on_the_shown_list_is_never_chosen_and_a_book_outside_the_access_is_only_counted():
    books = _books()
    rules = [L.RuleRef("b1", "2.1", 2, 1), L.RuleRef("b2", "2.1", 2, 2)]
    rl = L.plan_reading("r1", books, rules=rules, shown={"b1"}, allowed={"b1", "b2"})
    b2 = next(b for b in rl.books if b.book_id == "b2")
    assert (
        b2.on_shown_list is False and b2.items and not any(i.chosen for i in b2.items)
    )
    assert {i.not_read_why for i in b2.items} == {
        "not on the list shown before the start"
    }
    assert all(i.chosen for i in _items(rl, "b1"))
    rl2 = L.plan_reading("r1", books, rules=rules, shown={"b1"}, allowed={"b1"})
    assert [b.book_id for b in rl2.books] == [
        "b1"
    ] and rl2.books_wanted_not_listed == 1  # counted, never named
    rl3 = L.plan_reading(
        "r1", books, rules=rules
    )  # no shown list, no access: reads nothing
    assert rl3.books == () and rl3.books_wanted_not_listed == len(books)
    rl4 = L.plan_reading(
        "r1", books, rules=rules, allowed={"b1", "b2"}
    )  # access but no shown list
    assert not any(i.chosen for b in rl4.books for i in b.items)


def test_the_budget_ends_every_candidate_as_chosen_or_not_read_with_a_reason_never_silently(
    monkeypatch,
):
    books = _books()
    rules = [
        L.RuleRef("b1", c, p, n)
        for n, (c, p) in enumerate([("2.1", 2), ("2.2", 2), ("1", 2), ("3", 3)], 1)
    ]
    big = _plan("r1", books, rules=rules, engine="claude")
    assert all(i.chosen for b in big.books for i in b.items) and big.tokens_planned > 0
    monkeypatch.setattr(L, "CLAUDE_REVIEW_TOKENS", 1_500)
    small = _plan("r1", books, rules=rules, engine="claude")
    cut = [i for b in small.books for i in b.items if not i.chosen]
    assert cut and {i.not_read_why for i in cut} == {"over the reading budget"}
    assert small.tokens_planned <= small.tokens_limit == 1_500
    assert all(i.chosen or i.not_read_why for b in small.books for i in b.items)
    best = min((i for b in small.books for i in b.items), key=lambda i: i.rank)
    assert best.chosen  # the budget keeps the best-ranked first


def test_on_the_local_engine_a_chapter_over_the_review_budget_is_too_long_and_the_budget_is_smaller():
    books = [L.BookInput("b1", NC.cut("b1", _numbered(), max_tokens=5_000), why=())]
    rl = _plan("r1", books, rules=[L.RuleRef("b1", "2", 2, 1)], engine="local")
    assert rl.tokens_limit == NC.LOCAL_REVIEW_TOKENS < NC.CLAUDE_REVIEW_TOKENS


def test_a_partial_book_is_read_only_where_a_rule_or_a_title_names_its_governed_part():
    cut = NC.cut(
        "p1",
        _pages(
            f"1 Vessels and tanks\n{_para(40)}",
            f"2 Relief devices\n{_para(40)}",
            f"3 Welding\n{_para(40)}",
        ),
        max_tokens=1_500,
    )
    book = L.BookInput(
        "p1",
        cut,
        why=("governs the equipment type",),
        label="ASME BPVC Section VIII Division 1",
    )
    rl = _plan("r1", [book], equipment={"relief valve"})
    assert [i.chapter.chapter_id for i in _items(rl, "p1")] == [
        "2"
    ] and L.WHY_TITLE in _items(rl, "p1")[0].why  # plural matched, others not read


def test_the_model_can_add_a_chapter_it_was_shown_never_remove_one_and_an_id_code_did_not_supply_is_ignored():
    books = _books()
    rl = _plan("r1", books, rules=[L.RuleRef("b1", "2.1", 2, 1)])
    titles = L.titles_for_model(rl, books)
    assert titles and all(len(t) == 3 for t in titles)
    have = {(b.book_id, i.chapter.chapter_id) for b in rl.books for i in b.items}
    assert (
        not {(b, c) for b, c, _ in titles} & have
    )  # only chapters that are not candidates yet
    pick = (titles[0][0], titles[0][1])
    out = L.apply_model_choice(
        rl, books, titles, [pick, ("b1", "NOT-A-CHAPTER"), ("zz", "1"), ["b1"], 5]
    )
    added = [
        (b.book_id, i.chapter.chapter_id)
        for b in out.books
        for i in b.items
        if L.WHY_LIBRARIAN in i.why
    ]
    assert added == [pick]
    assert have <= {
        (b.book_id, i.chapter.chapter_id) for b in out.books for i in b.items
    }  # nothing removed
    assert [
        i.chosen
        for b in out.books
        for i in b.items
        if (b.book_id, i.chapter.chapter_id) in have
    ] == [i.chosen for b in rl.books for i in b.items]
    assert L.apply_model_choice(rl, books, titles, [("b1", "NOT-A-CHAPTER")]) is rl


def test_a_failed_model_call_leaves_the_code_only_list_and_no_call_without_titles():
    books = _books()
    rl = _plan("r1", books, rules=[L.RuleRef("b1", "2.1", 2, 1)])

    def boom(_titles):
        raise RuntimeError("down")

    assert (
        L.extend_with_model(rl, books, boom) is rl
        and L.extend_with_model(rl, books, lambda t: None) is rl
    )
    assert L.extend_with_model(rl, books, None) is rl
    got = L.extend_with_model(rl, books, lambda t: [(t[0][0], t[0][1])])
    assert (
        got is not rl
        and sum(1 for b in got.books for i in b.items)
        == sum(1 for b in rl.books for i in b.items) + 1
    )
    assert (
        L.parse_choice('{"chapters": [["b1", "2"], ["x"]]}') == [("b1", "2")]
        and L.parse_choice("nonsense") == []
        and L.parse_choice(None) == []
    )


def test_the_reading_never_offers_a_book_not_on_the_shown_list_to_the_model():
    books = _books()
    rl = _plan("r1", books, shown={"b1"})
    assert {b for b, _c, _t in L.titles_for_model(rl, books)} == {"b1"}


def test_the_role_record_counts_are_ids_and_numbers_only():
    books = _books()
    rl = _plan(
        "r1", books, rules=[L.RuleRef("b1", "2.1", 2, 1)], shown={"b1"}, allowed={"b1"}
    )
    got = L.produced(rl)
    assert (
        got["books"] == 1
        and got["chapters_chosen"] >= 1
        and got["books_wanted_not_listed"] == 1
    )
    assert all(isinstance(v, (int, dict)) for v in got.values())


def test_no_book_or_layout_word_list_is_written_in_the_module():
    import pathlib

    src = pathlib.Path(L.__file__).read_text(encoding="utf-8")
    for name in (
        "ASME",
        "SAES",
        "API-",
        "NACE",
        "ISO-",
        "pressure vessel",
        "relief valve",
    ):
        assert name not in src
