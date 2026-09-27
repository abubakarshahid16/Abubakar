"""Owner order 2d-2: for a standard the submittal CITES but the library does
NOT HOLD, an OPTIONAL check against a PUBLIC copy of it on the web.

WHAT IT IS NOT, ENFORCED IN CODE:

  * NEVER A COMPANY STANDARD. `is_public_identifier` is an ALLOW-list (a
    known public standards body's own numbering), not merely "not on a
    block-list" - and a company marker (SAES, SAMSS, KOC-*) refuses an
    identifier even if it also happened to match the allow-list, so the
    block-list is a second gate, not the only one. A refused identifier is
    never searched, never logged with its own text: it reads "Company
    standard - upload required", the same wording every other missing
    reference already carries.
  * NEVER FROM DATASHEET TEXT. The query sent is the identifier plus a
    generic topic word, scrubbed by the same `market_phrase` that scrubs a
    chat web question - never a datasheet value, a document number, or a
    project name.
  * NEVER AN UNVERIFIED QUOTE. A candidate is kept only when its quote can be
    found, word for word, on the page this module itself fetched - a search
    snippet alone is never enough.
  * NEVER A VERDICT WITHOUT A RULE. The quote is run through `rule_eval`
    exactly as a held standard's own clause would be; when it does not parse
    as a rule, the item is a question for the engineer, never a guess from
    prose.
  * NEVER COMPARED ACROSS EDITIONS. The edition the submittal cites is read
    LOCALLY from the submittal's own text (`cited_edition`, never sent
    anywhere) and set against the web page's own date. When they differ
    (`edition_differs`) the item is stored as "edition differs - not
    compared", naming both, and `compare` is never called for it. An
    UNKNOWN is not a match either: when either side has no year (the
    citation names none, or the page gives no date) the item is stored as
    "edition not confirmed - not compared". Only a confirmed same year is
    compared. Every one of the three is the same pending, unconfirmed draft.
  * NEVER COUNTED. Stored as a pending, unconfirmed draft
    (`origin = 'web_standard_check'`), exactly like the AI engineering check
    (kind C) - `comparison.recommend_code` never sees it, and it is shown on
    the CRS only after an engineer confirms it.

OFF BY DEFAULT (`settings.review_web_standards_enabled`). Even on, nothing is
sent unless the market lane's own two egress flags are also on and a search
tier is configured - the SAME lane the chat web question and the market page
already use, with the same host allowlist, rate limit and audit. This module
opens no socket of its own; `market_transport` is the one of the four gated
transports it calls into.
"""
from __future__ import annotations

import re

from .config import settings
from .db import connect

#: `review_findings.origin` for every item this module stores.
ORIGIN = "web_standard_check"
#: The label the screen and the CRS print beside a kept item.
LABEL_TEMPLATE = (
    "Checked against a public web source - not the contract copy of {name} - "
    "engineer to confirm"
)
#: What a company standard reads instead of ever being searched for.
NOT_SEARCHABLE_LABEL = "Company standard - upload required"
CONFIDENCE = "low"

#: A known public standards body's OWN numbering. This is an ALLOW-list: an
#: identifier must match one of these to be searched at all.
_PUBLIC_PREFIX = re.compile(
    r"^\s*(API|ASME|ASTM|ISO|IEC|NFPA|ANSI|NACE|MSS|AWS|AWWA|BS\s*EN|BS|EN|"
    r"DIN|IEEE|UL|NORSOK|PED|ASCE)\b",
    re.IGNORECASE,
)
#: Company / project identifiers this must NEVER search for, whatever else
#: they resemble. Named explicitly rather than inferred, so this stays a
#: second, independent gate rather than the only one an allow-list mistake
#: could slip past.
_COMPANY_MARKERS = re.compile(r"\bSAES\b|\bSAMSS\b|\bKOC\b|KOC-", re.IGNORECASE)


def is_public_identifier(identifier: str) -> bool:
    """Whether this identifier may ever be sent off this machine."""
    text = (identifier or "").strip()
    if not text or _COMPANY_MARKERS.search(text):
        return False
    return bool(_PUBLIC_PREFIX.match(text))


def _claude_native_web_search_available() -> bool:
    """The Anthropic server-side web search tool.

    NOT WIRED IN THIS BUILD - named honestly rather than silently skipped,
    so nothing here claims a capability that does not exist. Every check
    goes through the market lane below, which IS wired, gated and audited.
    """
    return False


def available() -> tuple[bool, str]:
    """Whether ANY web standards check could be attempted right now."""
    if not settings.review_web_standards_enabled:
        return False, "the public web standards check is switched off"
    if _claude_native_web_search_available():
        return True, "ok"
    from . import market_providers
    if not market_providers.live_enabled():
        return False, "this system does not permit outbound web searches"
    if not market_providers.tiers_configured():
        return False, "no web search provider is configured"
    return True, "ok"


def _generic_query(identifier: str, topic: str | None) -> str:
    """ONLY the identifier and a generic topic word - never a datasheet
    value, a document number, a project name, or anything typed verbatim."""
    from . import market_phrase as market_phrase_mod
    words = [identifier]
    if topic:
        scrubbed = market_phrase_mod.market_phrase(topic, ())
        if scrubbed:
            words.append(scrubbed)
    return " ".join(w for w in words if w).strip()


def search(identifier: str, *, topic: str | None = None, fetch=None) -> dict:
    """The market lane's own `search_all`, scoped to a public identifier.

    A company identifier never reaches this far: `run_check` below refuses
    it before calling `search`, and this function refuses it again on its
    own, so a caller of `search` directly gets the same guarantee.
    """
    from . import market_providers
    if not is_public_identifier(identifier):
        return {"enabled": False, "phrase": None, "rows": [], "failure": None,
                "tiers_attempted": [], "tiers_answered": [],
                "tiers_unconfigured": market_providers.tiers_unconfigured(),
                "tier_labels": market_providers.tier_labels()}
    phrase = _generic_query(identifier, topic)
    return market_providers.search_all(phrase, fetch=fetch)


def _fold(text: str) -> str:
    return " ".join((text or "").split())


def _verify_quote(quote: str, page_text: str) -> bool:
    """The quote must appear, word for word (whitespace folded), on the
    page this module fetched - never merely "plausible" from a snippet."""
    return bool(quote) and _fold(quote) in _fold(page_text)


def build_requirement(
    identifier: str, *, topic: str | None = None, fetch_search=None,
    fetch_text=None, timeout: float = 15.0,
) -> dict | None:
    """A web requirement - url, title, date, a QUOTE VERIFIED against the
    fetched page - or None. Never guessed: a row with no usable snippet, or
    a snippet that cannot be found again on the page itself, is dropped."""
    from . import market_transport
    result = search(identifier, topic=topic, fetch=fetch_search)
    rows = result.get("rows") or []
    if not rows:
        return None
    row = rows[0]
    url, title, quote, published = (
        row.get("url"), row.get("publisher"), row.get("text"), row.get("published"))
    if not url or not quote:
        return None
    fetcher = fetch_text or (lambda u, t: market_transport.fetch_text(u, timeout=t))
    try:
        page_text = fetcher(url, timeout)
    except Exception:  # noqa: BLE001 - a fetch failure is "no requirement", not a crash
        return None
    if not _verify_quote(quote, page_text):
        return None
    return {"identifier": identifier, "url": url, "title": title or url,
            "date": published, "quote": quote.strip()}


_YEAR = re.compile(r"(19|20)\d{2}")


def edition_differs(cited_edition: str | None, web_date: str | None) -> bool:
    """A cited edition/year that does not match the web page's own date -
    'edition differs' beats a wrong verdict read from the wrong edition.

    True ONLY when a difference is PROVEN: both sides carry a year and the
    years differ. False when either side is missing or has no year - which
    means "not proven different", NEVER "the same". A caller must not read
    False as a match; `edition_confirmed_same` is that question, and
    `run_check` asks both.
    """
    if not cited_edition or not web_date:
        return False
    cited = _YEAR.search(cited_edition)
    web = _YEAR.search(web_date)
    return bool(cited and web and cited.group() != web.group())


def edition_confirmed_same(cited_edition: str | None, web_date: str | None) -> bool:
    """Both sides carry a year and it is the same year. The ONLY case that
    may be compared - an unknown on either side is not a match."""
    cited = _YEAR.search(cited_edition or "")
    web = _YEAR.search(web_date or "")
    return bool(cited and web and cited.group() == web.group())


#: What may follow a citation to state its edition: an optional separator,
#: an optional "11th edition" / "Ed." / "Rev." word, then a year - or the
#: edition word alone. Read from the text right after the citation, on the
#: same line, and nowhere else.
_EDITION_TAIL = re.compile(
    r"^[ \t]*(?:[-:/,(][ \t]*)?"
    r"(?P<edition>"
    r"(?:(?:\d{1,2}(?:st|nd|rd|th)[ \t]+)?(?:edition|ed\.?|rev(?:ision)?\.?)[ \t]*[,(]?[ \t]*)?"
    r"(?:19|20)\d{2}\b"
    r"|\d{1,2}(?:st|nd|rd|th)[ \t]+(?:edition\b|ed\.))",
    re.IGNORECASE,
)


def cited_edition(submittal_text: str, identifier: str) -> str | None:
    """The edition the submittal ITSELF gives for this citation, in its own
    spelling ("2010", "11th edition (2010)", "11th edition") - or None.

    Read locally, from the submittal's own text; this value is never put in
    a search query and never leaves the machine. None when no citation of
    this identifier states an edition, AND when two citations of it state
    DIFFERENT years: the submittal is then ambiguous about which edition
    governs, and picking one would be a guess.
    """
    from . import applicability, datasheets
    key = applicability.normalise_identifier(identifier)
    if not key:
        return None
    text = submittal_text or ""
    found: list[str] = []
    for raw, _start, end in datasheets.referenced_standard_spans(text):
        if applicability.normalise_identifier(raw) != key:
            continue
        match = _EDITION_TAIL.match(text[end:end + 40].split("\n", 1)[0])
        if match:
            edition = match.group("edition").strip().rstrip(",(").strip()
            if edition.count("(") > edition.count(")"):
                edition += ")"
            found.append(edition)
    years = {y.group() for y in (_YEAR.search(e) for e in found) if y}
    if len(years) > 1:
        return None
    with_year = [e for e in found if _YEAR.search(e)]
    return (with_year or found or [None])[0]


def _submittal_text(submittal_document_id: str) -> str:
    """The submittal's own chunk text - the same source `_missing_references`
    reads its citations from, so the edition is read beside the citation
    that made it missing. Local only."""
    return " ".join(
        row["text"] or "" for row in connect().execute(
            "SELECT text FROM chunks WHERE document_id = ?", (submittal_document_id,)))


def compare(requirement: dict, facts: list[dict], *,
           output_field: str | None = None) -> tuple[dict, dict | None]:
    """(verdict, fact judged): the web quote run through `rule_eval` ONLY
    when the caller names the field it is about (`output_field`) - this
    module has no way to guess which datasheet field an arbitrary web quote
    concerns, and a wrong guess would be a wrong verdict wearing a real
    field's name. `run_check` below never guesses one, so its items are
    always a question for the engineer; a caller that DOES know the field
    (a future, more targeted lookup) gets the same table/formula handling
    `rule_eval` gives a held standard's own clause."""
    if output_field:
        from . import rule_eval
        rule = rule_eval.parse_rule(requirement["quote"], output=output_field,
                                    input_names=[output_field])
        if rule and rule_eval.verify_numbers(rule, requirement["quote"]):
            return rule_eval.judge(rule, facts)
    return ({"status": "NEEDS_ENGINEER_REVIEW",
             "detail": f"A public web source names a requirement for "
                       f"{requirement['identifier']} that could not be read as a "
                       f"rule - engineer to check."}, None)


def run_check(
    review_run_id: str, *, allowed_document_ids: frozenset[str],
    missing_identifiers: list[str], fetch_search=None, fetch_text=None,
) -> dict:
    """Ask once per public identifier, verify, check the edition, compare,
    store the kept ones as pending kind D drafts. Company identifiers are
    never attempted.

    Counts, all for THIS run only: `checked` identifiers attempted; `kept`
    drafts stored (a verified quote); of those, `compared` (edition
    confirmed the same), `edition_differs` (both years known and different
    - never compared) and `edition_unconfirmed` (a year missing on either
    side - never compared). compared + edition_differs + edition_unconfirmed
    == kept.

    Earlier UNCONFIRMED items of this run are replaced; a confirmed one is
    an engineer's decision and is never deleted (same rule as kind C).
    """
    from . import review as review_mod
    from . import submittal_review

    empty = {"checked": 0, "kept": 0, "compared": 0,
             "edition_differs": 0, "edition_unconfirmed": 0}
    ok, why = available()
    if not ok:
        return {"ran": False, "reason": why, **empty}
    run = submittal_review.get_review_run(review_run_id, allowed_document_ids=allowed_document_ids)
    if run is None:
        return {"ran": False, "reason": "no review run with that id", **empty}
    submittal = run["submittal_document_id"]
    facts = submittal_review.list_submittal_facts(
        allowed_document_ids=allowed_document_ids, review_run_id=review_run_id)
    submittal_text = _submittal_text(submittal)
    conn = connect()
    with conn:
        conn.execute("DELETE FROM review_findings WHERE review_run_id = ? AND origin = ?"
                     " AND confirmed_by IS NULL", (review_run_id, ORIGIN))
    counts = dict(empty)
    for identifier in missing_identifiers:
        # A COMPANY IDENTIFIER IS NEVER ATTEMPTED - not searched, not fetched,
        # not sent anywhere. This is the gate, not a filter on the results.
        if not is_public_identifier(identifier):
            continue
        counts["checked"] += 1
        requirement = build_requirement(
            identifier, fetch_search=fetch_search, fetch_text=fetch_text)
        if requirement is None:
            continue
        label = LABEL_TEMPLATE.format(name=identifier)
        cited = cited_edition(submittal_text, identifier)
        web_date = requirement["date"]
        fact = None
        # NEVER COMPARED ACROSS EDITIONS - and an unknown is not a match.
        # Only a confirmed same year reaches `compare`.
        if edition_differs(cited, web_date):
            counts["edition_differs"] += 1
            finding_text = (f"Edition differs - not compared. The submittal cites "
                            f"{identifier} {cited}; the public web source is dated "
                            f"{web_date}. {label}")
            action = (f"Obtain {identifier} {cited} (the edition the submittal cites) "
                      f"and check against it - the web source is a different edition.")
        elif not edition_confirmed_same(cited, web_date):
            counts["edition_unconfirmed"] += 1
            finding_text = (f"Edition not confirmed - not compared. The submittal cites "
                            f"{identifier} {cited or '(no edition stated)'}; the public "
                            f"web source is dated {web_date or '(no date given)'}. {label}")
            action = (f"Confirm which edition of {identifier} governs before relying "
                      f"on the web source - engineer to check.")
        else:
            counts["compared"] += 1
            # No field is named for a generic missing-standard lookup, so this
            # is always a question for the engineer - never a guessed verdict
            # from a field this module invented (see `compare`'s docstring).
            verdict, fact = compare(requirement, facts)
            finding_text = label
            action = verdict.get("detail") or "Engineer to confirm."
        finding = review_mod.create({
            "document_id": submittal,
            "category": "technical_query",
            "severity": "minor",
            "confidence": CONFIDENCE,
            "requirement": f"Requirement named for {identifier}",
            "finding": finding_text,
            "required_action": action,
            "status": "open",
            "approval_status": "pending",
        }, created_by=None)
        with conn:
            conn.execute(
                """UPDATE review_findings SET review_run_id = ?, origin = ?,
                       contractor_page = ?, contractor_evidence_text = ?, ai_rationale = ?
                   WHERE id = ?""",
                (review_run_id, ORIGIN,
                 (fact or {}).get("page"), (fact or {}).get("field_value"),
                 f"{finding_text}. "
                 f"Source: {requirement['title']} "
                 f"({web_date or 'date not given'}), {requirement['url']}. "
                 f"Quote: “{requirement['quote']}”",
                 finding["id"]))
        counts["kept"] += 1
    return {"ran": True, "reason": None, **counts}
