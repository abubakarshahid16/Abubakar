"""A citation written after the full stop must not strand the claim.

Found on the owner's library 2026-10-02: Claude-written comparison bullets
showed only a number ("Minimum temperature: 1", "Timing: 6"). The model wrote
`<claim>. [S1 "quote"]`; the sentence splitter cut at the full stop, the claim
became an uncited sentence with a figure and was dropped, and the citation on
its own was kept as if it were a claim. Synthetic text only.
"""

from app import answer

PASSAGES = [{
    "chunk_id": "c1",
    "text": ("A minimum post weld heat treatment temperature of 621 C shall be "
             "used for low alloy steels. The heat treatment shall follow welding."),
}]
QUOTE = '[S1 "minimum post weld heat treatment temperature of 621"]'


def test_a_claim_with_its_citation_after_the_full_stop_is_kept():
    """MUTATION TARGET."""
    text = f"* Minimum temperature: A minimum PWHT temperature of 621 C shall be used. {QUOTE}"
    clean, verification, claims, removed = answer.verify_claims(text, PASSAGES)
    assert "minimum PWHT temperature of 621 C" in clean
    assert clean.rstrip().endswith("[S1]")
    assert verification["verified"] == 1 and removed == 0


def test_the_citation_inside_the_sentence_still_works():
    text = f"* Minimum temperature: A minimum PWHT temperature of 621 C shall be used {QUOTE}."
    clean, verification, _claims, removed = answer.verify_claims(text, PASSAGES)
    assert "621 C" in clean and removed == 0


def test_a_wrong_figure_is_still_removed_when_the_citation_follows_the_stop():
    """NOT VACUOUS: joining must not let an unsupported figure through."""
    text = f"* Minimum temperature: A minimum PWHT temperature of 700 C shall be used. {QUOTE}"
    clean, _verification, _claims, removed = answer.verify_claims(text, PASSAGES)
    assert "700" not in clean
    assert removed == 1


def test_an_unquoted_wrong_claim_is_still_removed():
    """NOT VACUOUS: a quote that is not on the page still removes the claim."""
    text = '* Soak time: The soak time is 5 hours. [S1 "the soak time shall be five hours here"]'
    clean, _verification, _claims, removed = answer.verify_claims(text, PASSAGES)
    assert "5 hours" not in clean
    assert removed == 1


def test_an_uncited_figure_sentence_before_a_cited_one_is_not_absorbed():
    """NOT VACUOUS: only a fragment that is NOTHING BUT citations is joined
    back. A separate, uncited sentence with a figure is still dropped and does
    not take the cited sentence with it."""
    text = ("The tank holds 900 litres. The heat treatment shall follow welding "
            '[S1 "heat treatment shall follow welding"].')
    clean, _verification, _claims, removed = answer.verify_claims(text, PASSAGES)
    assert "900" not in clean
    assert "heat treatment shall follow welding" in clean
