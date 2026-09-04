"""Ligature repair, and the safety property that makes it a repair.

Some PDFs encode `ti` and `fi` as glyphs whose embedded font mapping is wrong,
so extraction yields the wrong character entirely: "Introduc,on" for
Introduction, "Sec3on" for Section, "DeEinitions" for Definitions.

This is a COVERAGE limit, not a retrieval one. No ranking change can match a
word that is not in the text.

Measured on book4 (1,400 pages) BEFORE any of this was written:

    pattern     pages   % pages   hits    clean pages   coexist
    ti -> ,       177     12.6%     233         1196        171
    ti -> 3        93      6.6%     119         1196         91
    fi -> Ei       89      6.4%     133          613         35

    292 of 1,400 pages affected (20.9%), 535 corrupted tokens
    = 0.68% of words on affected pages, 0.18% of the document

Sparse, but concentrated where it hurts: the commonest corruptions are
"Sec3on" (91), "Introduc,on" (83) and "Ques,on" (51) - the structural words a
"what is section 3.4 about" question matches on.

THE PROPERTY THAT MATTERS is the last group of tests: applying the repair to
correctly extracted text must change nothing. Both forms coexist in the same
document - 177 pages corrupt against 1,196 clean - which is what makes this
verifiable rather than a guess.
"""

import pytest

from app import ligatures
from app.quality import normalise_text


# ---------------------------------------------------------------- repairs


@pytest.mark.parametrize(
    "corrupt,clean",
    [
        ("Introduc,on", "Introduction"),
        ("Sec3on", "Section"),
        ("Ques,on", "Question"),
        ("Distribu,on", "Distribution"),
        ("Applica,on", "Application"),
        ("Func,on", "Function"),
        ("miza,on", "mization"),
        ("miza3on", "mization"),
        ("Introduc,ons", "Introductions"),
        ("DeEinitions", "Definitions"),
        ("speciEied", "specified"),
        ("difEicult", "difficult"),
        ("CoefEicient", "Coefficient"),
        ("coefEicient", "coefficient"),
        ("modiEied", "modified"),
        ("conEiguration", "configuration"),
        ("BeneEits", "Benefits"),
        ("ProEile", "Profile"),
    ],
)
def test_a_substituted_ligature_is_repaired(corrupt, clean):
    assert ligatures.repair(corrupt) == clean


def test_repair_works_inside_a_real_heading():
    assert ligatures.repair("1.4 DeEinitions and Terminology") == (
        "1.4 Definitions and Terminology"
    )
    assert ligatures.repair("9.10 User-DeEined Functions") == (
        "9.10 User-Defined Functions"
    )


def test_the_repair_runs_at_extraction():
    """Fixed at the source, so every downstream stage sees repaired text.
    Doing it at query time would leave the index holding words no question can
    match."""
    assert normalise_text("Sec3on 5 Introduc,on") == "Section 5 Introduction"


# -------------------------------------------- THE SAFETY PROPERTY


CLEAN_TEXT = [
    # a comma genuinely followed by "on" - with the space that real prose has
    "The value, on which everything depends, shall be recorded.",
    "Refer to Table 3, on page 12, for the full list of requirements.",
    # words legitimately starting with Ei
    "Einstein derived the relation in 1905.",
    "Eigenvalues of the matrix are computed numerically.",
    # an acronym followed by a capital I
    "The PID controller and the DEIonised water supply are separate.",
    # a digit 3 genuinely followed by "on"
    "See Figure 3 on the following page for the arrangement.",
    "Chapter 3 online resources are listed in the appendix.",
    # ordinary engineering prose with -tion words already correct
    "Introduction to the specification. Section 5 covers application methods.",
    "The distribution function and its coefficient are defined in clause 9.",
    # a table row of numbers
    "Cleanliness ISO 8501-1 Sa 2 1/2 Roughness ISO 8503 Grade Medium 50 85",
]


@pytest.mark.parametrize("text", CLEAN_TEXT)
def test_correctly_extracted_text_is_never_altered(text):
    """The difference between a repair and a rewrite.

    Every rule is anchored on a shape that cannot occur in correct prose: the
    substituted character must sit between letters with NO space, and the word
    must end in -on or -ons. Real prose writes "value, on which" with a space.
    """
    assert ligatures.repair(text) == text


def test_validate_reports_nothing_on_clean_text():
    """The same property, through the function used to check it against the
    real corpus. Measured: 0 changes across 2,281 clean pages."""
    assert ligatures.validate(CLEAN_TEXT) == []


def test_validate_would_report_a_change_if_the_repair_were_too_loose():
    """Guard the guard. If validate() could not detect an alteration it would
    certify anything, which is worse than not checking."""
    changed = ligatures.validate(["Introduc,on to the topic."])
    assert changed, "validate() failed to notice text it had altered"


# ------------------------------------------------------------ not repaired


def test_ff_substitution_is_left_alone_and_recorded_instead():
    """37 pages carry an `ff -> ?` substitution with 50 hits, and no clean
    reference was measured in that document - so there is nothing to validate
    a rule against. Recorded as a limitation rather than guessed at."""
    text = "the di?erence between the two values"
    assert ligatures.repair(text) == text


def test_counting_corruptions_is_available_for_the_coverage_report():
    """Reported as a coverage limit alongside the character-coverage audit,
    never as a retrieval failure."""
    assert ligatures.count_corruptions("Sec3on and Introduc,on") == 2
    assert ligatures.count_corruptions("nothing wrong here at all") == 0
