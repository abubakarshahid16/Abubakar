"""Applicability v2 - the DECISION, by code (owner order 2026-09-25, 4.5).

PROPOSAL STAGE: not called by any live route. The taxonomy and the term
lexicon are PARAMETERS, because both are still proposals awaiting owner
approval (.cowork/equipment-taxonomy-PROPOSED-v1.md); nothing unapproved is
baked in here.

Division of labour (the order's design principle):
- the MODEL reads a standard's scope once into a scope record (covered
  equipment, exclusions, limits, generic flag), every item with a quote;
- the CALLER drops every item whose quote does not verify
  (app.model_evidence.quote_verified) BEFORE calling `decide`;
- this module decides, by code: taxonomy matching and number comparison.
  The model never decides that a pump is static equipment.

ASYMMETRIC SAFETY RULE. A wrong NOT_APPLICABLE hides a standard from the
engineer - the worst error - so NOT_APPLICABLE needs positive evidence:
  (a) an explicit EXCLUSION whose term names the submittal's type, family
      or class, or
  (b) an explicit LIMIT that restricts the standard to other equipment, or
      to numbers / a facility the submittal clearly falls outside of.
A scope that merely lists OTHER equipment is UNKNOWN, never NOT_APPLICABLE.
A GENERIC scope ("equipment", "facilities") is APPLICABLE_CANDIDATE or
UNKNOWN - never NOT_APPLICABLE, unless an explicit exclusion names the
submittal (rule (a)).
Every APPLICABLE / NOT_APPLICABLE carries the deciding quote and page.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

APPLICABLE = "APPLICABLE"
NOT_APPLICABLE = "NOT_APPLICABLE"
APPLICABLE_CANDIDATE = "APPLICABLE_CANDIDATE"
UNKNOWN = "UNKNOWN"

TYPE, FAMILY, CLASS = "type", "family", "class"


@dataclass(frozen=True)
class Profile:
    """The submittal, from verified data only (order 4.2). None = UNKNOWN."""
    type: str | None
    family: str | None
    cls: str | None
    facility: str | None = None                 # "onshore" / "offshore"
    numbers: dict = field(default_factory=dict)  # kind -> (min, max, unit)


# ------------------------------------------------------------ term matching

def nodes_for(term: str | None, lexicon: dict[str, tuple[str, str]]) -> set[tuple[str, str]]:
    """Taxonomy nodes a scope term names. `lexicon` maps a lower-case phrase
    to (level, name). Whole-word match, optional plural; longest phrases
    first, and a shorter phrase inside an already-matched longer one does not
    count again ("pressure relief valve" is not also "valve")."""
    text = (term or "").lower()
    found: set[tuple[str, str]] = set()
    taken: list[tuple[int, int]] = []
    for phrase in sorted(lexicon, key=len, reverse=True):
        for m in re.finditer(rf"\b{re.escape(phrase)}(?:s|es)?\b", text):
            if any(m.start() >= a and m.end() <= b for a, b in taken):
                continue
            taken.append((m.start(), m.end()))
            found.add(lexicon[phrase])
    return found


def _names_submittal(nodes: set[tuple[str, str]], p: Profile) -> bool:
    return any((level == TYPE and name == p.type) or (level == FAMILY and name == p.family)
               or (level == CLASS and name == p.cls) for level, name in nodes)


# --------------------------------------------------------- number comparison

_TO_MPA = {"mpa": 1.0, "kpa": 0.001, "bar": 0.1, "barg": 0.1, "psi": 0.00689476, "psig": 0.00689476}


def _in_base(value: float, unit: str | None, kind: str) -> float | None:
    u = (unit or "").lower().replace(" ", "").replace("°", "")
    if kind == "pressure":
        return value * _TO_MPA[u] if u in _TO_MPA else None
    if kind == "temperature":
        if u in ("c", "degc"):
            return value
        if u in ("f", "degf"):
            return (value - 32) * 5 / 9
        return None
    if kind == "size":
        return value * 25.4 if u in ("in", "inch", "nps") else (value if u == "mm" else None)
    return None


def _outside(limit: dict, p: Profile) -> bool:
    """True only when the submittal is CLEARLY outside a numeric limit: both
    sides known, units convertible, and the whole submittal range outside."""
    kind = limit.get("kind")
    have = p.numbers.get(kind)
    if not have:
        return False
    s_min, s_max, s_unit = have
    lo = limit.get("min")
    hi = limit.get("max")
    conv = lambda v, u: None if v is None else _in_base(float(v), u, kind)  # noqa: E731
    s_lo, s_hi = conv(s_min, s_unit), conv(s_max, s_unit)
    l_lo, l_hi = conv(lo, limit.get("unit")), conv(hi, limit.get("unit"))
    if (lo is not None and l_lo is None) or (hi is not None and l_hi is None):
        return False                      # a limit unit we cannot convert
    if s_lo is None and s_hi is None:
        return False
    s_lo = s_hi if s_lo is None else s_lo
    s_hi = s_lo if s_hi is None else s_hi
    return (l_hi is not None and s_lo > l_hi) or (l_lo is not None and s_hi < l_lo)


# ------------------------------------------------------------------ decision

def _has_quote(item: dict) -> bool:
    return bool((item.get("quote") or "").strip())


def _result(decision: str, basis: str, item: dict | None = None) -> dict:
    return {"decision": decision, "basis": basis,
            "quote": item.get("quote") if item else None,
            "page": item.get("page") if item else None,
            "term": item.get("term") if item else None}


def decide(record: dict | None, profile: Profile, lexicon: dict[str, tuple[str, str]]) -> dict:
    """APPLICABLE / NOT_APPLICABLE / APPLICABLE_CANDIDATE / UNKNOWN for one
    (verified scope record, submittal profile) pair. See the module doc."""
    if not record:
        return _result(UNKNOWN, "no verified scope record")
    covered = [i for i in record.get("covered_equipment") or [] if _has_quote(i)]
    exclusions = [i for i in record.get("explicit_exclusions") or [] if _has_quote(i)]
    limits = [i for i in record.get("explicit_limits") or [] if _has_quote(i)]
    generic = bool(record.get("generic_scope"))

    # (a) an explicit exclusion naming the submittal - allowed even when generic
    for item in exclusions:
        if _names_submittal(nodes_for(item.get("term"), lexicon), profile):
            return _result(NOT_APPLICABLE, "explicit exclusion names the submittal", item)

    match = next((i for i in covered
                  if _names_submittal(nodes_for(i.get("term"), lexicon), profile)), None)

    # (b) explicit limits - never for a generic scope
    if not generic:
        for item in limits:
            kind = item.get("kind")
            if kind == "equipment":
                nodes = nodes_for(item.get("term"), lexicon)
                if nodes and not _names_submittal(nodes, profile) and profile.type:
                    return _result(NOT_APPLICABLE, "limit restricts it to other equipment", item)
            elif kind == "facility":
                want = (item.get("term") or "").lower()
                if profile.facility and want in ("onshore", "offshore") and want != profile.facility:
                    return _result(NOT_APPLICABLE, "limit restricts it to another facility", item)
            elif kind in ("pressure", "temperature", "size") and _outside(item, profile):
                return _result(NOT_APPLICABLE, f"submittal outside the {kind} limit", item)

    if match:
        return _result(APPLICABLE, "covered equipment names the submittal", match)
    if generic:
        return _result(APPLICABLE_CANDIDATE, "generic scope, no exclusion", covered[0] if covered else None)
    return _result(UNKNOWN, "scope does not settle it")
