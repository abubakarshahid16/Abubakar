
from app.chunker import (
    Block,
    build_chunks,
    chunk_id,
    count_tokens,
    detect_running_lines,
    looks_like_heading,
    segment_document,
    strip_running_lines,
)
from app.config import settings


def test_token_counts_come_from_the_real_e5_tokenizer():
    # a word-count approximation would give 5; the real tokenizer disagrees
    assert count_tokens("hello") >= 1
    assert count_tokens("antidisestablishmentarianism") > 1  # subword split
    assert count_tokens("") == 0


def test_no_chunk_ever_exceeds_the_ceiling():
    """e5-small silently truncates above 512, so the ceiling is an invariant."""
    long_para = " ".join(f"Sentence number {i} about pump maintenance." for i in range(400))
    blocks = [Block("prose", long_para, 1, 1, "5.1 Maintenance")]
    chunks = build_chunks(blocks)
    assert chunks
    assert all(c.tokens <= settings.chunk_max_tokens for c in chunks)
    # and it recomputes from the real text, not from a window length
    assert all(count_tokens(c.text) <= settings.chunk_max_tokens for c in chunks)


def test_chunks_do_not_split_mid_sentence():
    sents = [f"This is sentence {i} and it ends here." for i in range(80)]
    blocks = [Block("prose", " ".join(sents), 3, 3, "2.1 Scope")]
    chunks = build_chunks(blocks)
    assert len(chunks) > 1
    for c in chunks:
        assert c.text.rstrip().endswith((".", "?", "!", ":", ";"))


def test_running_headers_are_stripped_but_body_text_is_kept():
    header = "PROFESSIONAL PRACTICES IN IT"
    body = "The recurring phrase appears here in the body and must survive."
    pages = [
        (i, f"{header}\nPage {i}\n{body}\nUnique line {i}\n{header}\nPage {i}")
        for i in range(1, 21)
    ]
    running = detect_running_lines(pages)
    assert any("professional practices" in r for r in running)

    cleaned, removed = strip_running_lines(pages[5][1], running)
    assert removed > 0
    assert header not in cleaned.splitlines()[:1]
    # a phrase that recurs in the BODY is never removed
    assert body in cleaned


def test_running_line_detection_needs_enough_pages():
    """Two pages are not evidence of a running header."""
    pages = [(1, "Title\nbody one"), (2, "Title\nbody two")]
    assert detect_running_lines(pages) == set()


def test_headings_are_recognised_and_figure_labels_are_not():
    assert looks_like_heading("5.1 Introduction") == "5.1 Introduction"
    assert looks_like_heading("2.2.3 Location Tracking") == "2.2.3 Location Tracking"
    # a contents line ends in a page number
    assert looks_like_heading("9.3.2 Protecting Personal Data 475") is None
    # a figure annotation, not a section
    assert looks_like_heading("3 L/min") is None
    assert looks_like_heading("Just some ordinary sentence text here.") is None


def test_section_heading_is_inherited_across_page_boundaries():
    pages = [
        (10, "7.4 Vibration Limits\nThe limit shall not be exceeded."),
        (11, "Continued discussion of the same topic with no new heading."),
        (12, "Still the same section, three pages after the heading."),
    ]
    blocks, _ = segment_document(pages, running=set())
    assert blocks
    # every block, including those two pages later, carries the heading
    assert all(b.section == "7.4 Vibration Limits" for b in blocks)
    assert blocks[-1].page_start == 12


def test_contents_page_does_not_poison_section_state():
    """A wall of heading-like lines is a contents page, not real structure."""
    toc = "\n".join([
        "1.1 The Pace of Change", "1.2 Change and Unexpected Developments",
        "1.3 Themes", "1.4 Ethics", "1.5 Summary", "1.6 Exercises",
    ])
    pages = [(1, toc), (2, "Body text on the next page with no heading of its own.")]
    blocks, _ = segment_document(pages, running=set())
    body = [b for b in blocks if b.page_start == 2]
    assert body
    assert body[0].section is None  # not "1.6 Exercises"


def test_cross_page_chunk_keeps_a_page_range():
    pages = [
        (20, "4.1 Scope\n" + " ".join(f"Alpha sentence {i} here." for i in range(20))),
        (21, " ".join(f"Beta sentence {i} here." for i in range(20))),
    ]
    blocks, _ = segment_document(pages, running=set())
    chunks = build_chunks(blocks)
    spanning = [c for c in chunks if c.page_end > c.page_start]
    assert spanning, "expected at least one chunk to span pages 20-21"
    c = spanning[0]
    assert c.page_start == 20 and c.page_end == 21


def test_table_block_is_kept_whole():
    table = "TABLE 2.1\nxn\nyn\n2.00\n4.0000\n2.10\n4.1800\n2.20\n4.3768\n2.30\n4.5914"
    pages = [(5, f"9.9 Numerical Results\nSome prose before.\n{table}\n")]
    blocks, _ = segment_document(pages, running=set())
    tables = [b for b in blocks if b.kind == "table"]
    assert tables, "the table run was not detected"
    chunks = build_chunks(blocks)
    tchunks = [c for c in chunks if c.kind == "table"]
    if tchunks:  # small tables fall back to prose by design
        assert "4.3768" in tchunks[0].text and "TABLE 2.1" in tchunks[0].text


def test_equations_are_not_mistaken_for_tables():
    """An earlier version turned every short maths line into its own chunk."""
    eqns = "\n".join(["where", "k4 g(tn h, xn hm3, yn hk3)", "m4 f(tn h, xn hm3)",
                      "k3 g(tn 1", "2 h, xn 1", "and so forth"])
    pages = [(7, eqns)]
    blocks, _ = segment_document(pages, running=set())
    assert not [b for b in blocks if b.kind == "table"]


def test_chunk_id_is_deterministic_and_content_addressed():
    a = chunk_id("abc123def456ffff", 42, 7, "deadbeefcafebabe")
    b = chunk_id("abc123def456ffff", 42, 7, "deadbeefcafebabe")
    assert a == b == "abc123def456:p00042:c00007:deadbeef"
    # different content at the same position gives a different id
    assert chunk_id("abc123def456ffff", 42, 7, "0000000000000000") != a


# --------------------------------------------- front matter classification

from app.chunker import RETRIEVABLE_KINDS, classify_page  # noqa: E402


def test_contents_page_is_classified_toc_not_prose():
    """A contents chunk containing '5.3.1 Identity Theft 257' would otherwise
    outscore page 257, where the real answer is."""
    toc = "\n".join([
        "Contents",
        "5.1 Introduction 245",
        "5.2 What is Hacking? 247",
        "5.3 Some Specific Applications of Hacking 255",
        "5.3.1 Identity Theft 257",
        "5.3.2 Case Study: The Target Breach 261",
        "5.4 Whose Laws Rule the Web 270",
        "5.5 Exercises 281",
    ])
    assert classify_page(toc, page_no=9, total_pages=546) == "toc"
    assert "toc" not in RETRIEVABLE_KINDS


def test_copyright_page_is_classified_frontmatter():
    page = (
        "330 Hudson Street, NY, NY 10013\n"
        "Copyright © 2018 by Pearson Education, Inc. All rights reserved.\n"
        "Library of Congress Cataloging-in-Publication Data\n"
        "ISBN 13: 978-0-13-461527-1\n"
        "Editor in Chief: Julian Partridge\n"
    )
    assert classify_page(page, page_no=4, total_pages=546) == "frontmatter"
    assert "frontmatter" not in RETRIEVABLE_KINDS


def test_index_page_at_the_back_is_classified_index():
    page = "\n".join([
        "identity theft, 257, 261",
        "encryption, 88, 92, 100",
        "hacking, 245, 247, 255",
        "privacy, 63, 67, 71",
        "surveillance, 74, 80",
        "wiretapping, 82, 85",
        "zoning, 300",
    ])
    assert classify_page(page, page_no=600, total_pages=613) == "index"


def test_ordinary_body_page_stays_prose():
    page = (
        "Vibration limits per API 610 shall not exceed 3.0 mm/s RMS measured at "
        "the bearing housing. Readings shall be taken at operating speed with the "
        "pump at rated flow. Any exceedance shall be reported to the area engineer."
    )
    assert classify_page(page, page_no=147, total_pages=546) == "prose"
    assert "prose" in RETRIEVABLE_KINDS


def test_publisher_address_is_never_a_section_heading():
    """The exact defect: every chunk from page 4 on read
    section='330 Hudson Street, NY, NY 10013'."""
    assert looks_like_heading("330 Hudson Street, NY, NY 10013") is None


def test_equation_is_never_a_section_heading():
    assert looks_like_heading("0 K(s, t) f(t) dt") is None
    assert looks_like_heading("2 h, xn 1") is None


def test_allcaps_line_is_not_enough_to_be_a_heading():
    """ALL-CAPS matched addresses, credits and running heads. Null is better."""
    assert looks_like_heading("WAVE EQUATION") is None
    assert looks_like_heading("REVIEW MATERIAL") is None
    # a genuine numbered heading still works
    assert looks_like_heading("7.4 Vibration Limits") == "7.4 Vibration Limits"


def test_frontmatter_blocks_never_set_section_state():
    pages = [
        (4, "Copyright © 2018 Pearson. All rights reserved. ISBN 13: 978-0-13-461527-1"),
        (5, "Ordinary body prose that follows the copyright page."),
    ]
    kinds = {4: classify_page(pages[0][1], 4, 546), 5: "prose"}
    blocks, _ = segment_document(pages, running=set(), page_kinds=kinds)
    body = [b for b in blocks if b.page_start == 5]
    assert body and body[0].section is None
