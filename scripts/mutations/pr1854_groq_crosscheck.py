"""PR #1854: the second AI's lane on Groq (owner decision 17 Nov 2026, #1584). `groq_transport.py` opens a socket and
`groq_spend.py` holds its money caps: both in the danger zone (rule 6)."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_groq_crosscheck.py"
_C = "tests/test_socket_containment.py"
_P = APP / "groq_transport.py"
_S = APP / "groq_spend.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M1854-01", phase=1854, description="the switch is not asked before a client is built",
             path=_P, anchor='    if not settings.groq_crosscheck_enabled:\n        raise GroqRefused("switch_off")\n',
             replacement="",
             target=_C, keyword="groq_transport_is_off_by_default", tags=("privacy", "critical")),
    Mutation(id="M1854-02", phase=1854, description="a missing key is not refused before a client is built",
             path=_P, anchor='    if not _key():\n        raise GroqRefused("no_key")\n',
             replacement="",
             target=_C, keyword="groq_transport_is_off_by_default", tags=("privacy",)),
    Mutation(id="M1854-03", phase=1854, description="the host is checked by name only: user info and a port pass",
             path=_P, anchor="        and parts.netloc.lower() == HOST\n",
             replacement="",
             target=_T, keyword="any_other_url_is_refused", tags=("privacy", "critical")),
    Mutation(id="M1854-04", phase=1854, description="plain http is accepted",
             path=_P, anchor='        parts.scheme == "https"\n',
             replacement='        parts.scheme in ("https", "http")\n',
             target=_T, keyword="any_other_url_is_refused", tags=("privacy", "critical")),
    Mutation(id="M1854-05", phase=1854, description="the approved-document gate is ignored",
             path=_P, anchor="    if refused is not None:\n        raise GroqRefused(refused)\n",
             replacement="    if False:\n        raise GroqRefused(refused)\n",
             target=_T, keyword="not_on_both_lists or not_approved_sends_nothing", tags=("privacy", "critical")),
    Mutation(id="M1854-06", phase=1854, description="a 4xx is treated as billed",
             path=_P, anchor="        return 400 <= exc.status < 500\n",
             replacement="        return False\n",
             target=_T, keyword="our_sentence_never_the_api_text or a_4xx_costs_nothing", tags=("budget",)),
    Mutation(id="M1854-07", phase=1854, description="an answer over the size cap is read",
             path=_P, anchor="    if len(content) > MAX_RESPONSE_BYTES:\n",
             replacement="    if False:\n",
             target=_T, keyword="big_or_non_json_answer", tags=("privacy",)),
    Mutation(id="M1854-08", phase=1854, description="an answer that is not declared JSON is read",
             path=_P, anchor='    if "json" not in content_type.lower():\n',
             replacement="    if False:\n",
             target=_T, keyword="big_or_non_json_answer", tags=("privacy",)),
    Mutation(id="M1854-09", phase=1854, description="redirects are followed (a host no gate saw)",
             path=_P, anchor="            follow_redirects=False,  # a 302 is a host no gate saw\n",
             replacement="            follow_redirects=True,  # a 302 is a host no gate saw\n",
             target=_T, keyword="a_good_answer_is_returned", tags=("privacy", "critical")),
    Mutation(id="M1854-10", phase=1854, description="an ambient proxy may route the request",
             path=_P, anchor="            trust_env=False,  # no ambient HTTP_PROXY routing this elsewhere\n",
             replacement="            trust_env=True,  # no ambient HTTP_PROXY routing this elsewhere\n",
             target=_T, keyword="a_good_answer_is_returned", tags=("privacy", "critical")),
    Mutation(id="M1854-11", phase=1854, description="a failed connection chains the httpx error (its request holds the key)",
             path=_P, anchor="        failed = (type(exc).__name__, False)\n",
             replacement="        raise GroqUnreachable(type(exc).__name__, sent=False)\n",
             target=_T, keyword="failed_connection_carries_no_request", tags=("privacy", "critical")),
    Mutation(id="M1854-12", phase=1854, description="the per-run cap is not checked",
             path=_S, anchor="        if spent(run=run) + worst > run_cap():\n",
             replacement="        if False:\n",
             target=_T, keyword="caps_refuse or run_cap_stops", tags=("budget", "critical")),
    Mutation(id="M1854-13", phase=1854, description="the per-day cap is not checked",
             path=_S, anchor="        if spent(day=today) + worst > day_cap():\n",
             replacement="        if False:\n",
             target=_T, keyword="caps_refuse or torn_ledger", tags=("budget", "critical")),
    Mutation(id="M1854-14", phase=1854, description="an open reservation counts nothing until settled",
             path=_S, anchor='        and not (e.get("reservation") and e["reservation"] in closed)\n',
             replacement='        and not e.get("reservation")\n',
             target=_T, keyword="caps_refuse", tags=("budget",)),
)
