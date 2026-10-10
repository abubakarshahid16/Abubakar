"""#560: web search for standard identifiers, filtered and approved. Ids M6201-M6210."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_w5b_560_standard_lookup.py"
_S = APP / "standard_lookup.py"
_TAG = ("w5b", "privacy", "egress")


def _m(i, desc, anchor, repl, kw=None):
    return Mutation(id=f"M{i}", phase=i, description=desc, path=_S, anchor=anchor,
                    replacement=repl, target=_T, keyword=kw, tags=_TAG)


MUTATIONS: tuple[Mutation, ...] = (
    _m(6201, "a quoted sentence is sent", "    if _QUOTES.search(text):\n", "    if False:\n", "named_reason"),
    _m(6202, "a value after an identifier is sent",
       "        if _HAS_DIGIT.search(token):\n            return Check(None, BLOCKED_VALUE)\n", "",
       "named_reason"),
    _m(6203, "a name is sent", "        if token[:1].isupper():\n            return Check(None, BLOCKED_NAME)\n",
       "", "named_reason"),
    _m(6204, "a company document number behind a public body is sent",
       "            if not is_public_identifier(identifier):\n", "            if False:\n",
       "company_identifier"),
    _m(6205, "a word off the list is sent", "        return Check(None, BLOCKED_WORD)\n    if not identifiers:",
       "        i += 1\n        continue\n    if not identifiers:", "named_reason"),
    _m(6206, "a second number is taken into the identifier",
       "            if j < len(tokens) and _DESIGNATOR.match(tokens[j]) and _HAS_DIGIT.search(tokens[j]):\n"
       "                parts.append(tokens[j])\n                j += 1\n",
       "            while j < len(tokens) and _DESIGNATOR.match(tokens[j]) and _HAS_DIGIT.search(tokens[j]):\n"
       "                parts.append(tokens[j])\n                j += 1\n",
       "named_reason"),
    _m(6207, "the lane ignores its own flag",
       "    return bool(settings.standard_lookup_enabled) and market_providers.live_enabled()",
       "    return market_providers.live_enabled()", "without_its_own_flag"),
    _m(6208, "the lane ignores the market egress flags",
       "    return bool(settings.standard_lookup_enabled) and market_providers.live_enabled()",
       "    return bool(settings.standard_lookup_enabled)", "without_the_market_egress_flags"),
    _m(6209, "an approval can be used twice",
       "    if claimed != 1:\n", "    if False:\n", "sent_once"),
    _m(6210, "the stored query is not re-checked before sending",
       "    if result.sendable is None or result.sendable != row[\"query\"]:\n", "    if False:\n",
       "changed_after_approval"),
)
