"""The one place in this codebase that may open a socket to the public internet.

WHY IT IS ITS OWN MODULE. `market.py`, `market_phrase.py` and
`market_providers.py` are forbidden to import an HTTP client, and that is
enforced by AST inspection in tests/test_market_no_document_leak.py rather
than by anybody's discipline. A module that cannot make a request cannot leak
a document however wrong its logic goes. The cost of that guarantee is that
something else has to hold the client, and this is that something: one file,
one function, easy to read in full before deciding whether to trust it.

The mirror of that rule applies here. This module may open sockets and MUST
NOT be able to reach the corpus - it imports no `db`, `search`, `keyword`,
`chunker`, `passages`, `claims` or `analysis`, and the same AST test checks
it. The two halves of the leak are therefore in different files, and neither
file can perform both.

DEFAULT OFF, AND OFF MEANS NO CLIENT EXISTS. `transport()` returns None
unless BOTH flags are true. `market_providers.search_all` treats a None
transport as "no transport supplied" and reports a failure, so the wiring is
inert rather than merely unused: with the flags off there is no client object,
no connection pool and no code path that could construct one. That is the
property that makes flipping two flags the entire change on the day the client
says yes.

THREE GATES BEFORE A BYTE LEAVES, deliberately redundant:

  1. `live_enabled()` - both flags, checked here, before a client is built.
  2. `check_host()` - the provider checks the URL it built; this checks it
     AGAIN immediately before the request. The provider's check can be
     bypassed by a bug in a provider; this one cannot be bypassed by anything
     short of editing this file, because it is the last thing between the URL
     and the socket.
  3. The OS. Code-level allowlisting is defence in depth and NOT the control -
     a process that can open a socket can reach any host it likes. The real
     control is a firewall rule or an egress proxy restricting this process to
     `market_allowed_hosts`, applied where the application cannot edit it.
     This file makes an accident loud; the firewall is what makes a deliberate
     exfiltration hard.

WHAT IS NOT SENT. No cookies, no redirects followed, no client certificate,
and a fixed User-Agent that names the software and nothing about the client.
Redirects are off because a 302 is a host the allowlist never saw: following
one would move the destination outside the check that had just passed.
"""

from __future__ import annotations

from collections.abc import Mapping

import httpx

from . import market_providers

#: Identifies the software, and says nothing about who is running it. No
#: client name, no organisation, no version of the corpus. OpenAlex and
#: Wikipedia both ask callers to identify themselves; this is the honest
#: minimum that does not disclose the deployment.
USER_AGENT = "rag-intelligence/1.0 (public-information tier; offline-first)"

#: Bytes. A response larger than this is refused rather than read: a public
#: search result is a few hundred KB at the outside - the real OpenAlex
#: response for five works is ~113 KB - and an unbounded read on a 15 W
#: machine holding a client's corpus is a denial of service waiting for a bad
#: day.
MAX_RESPONSE_BYTES = 4 * 1024 * 1024


class TransportRefused(RuntimeError):
    """A request this module will not make.

    Distinct from an HTTP error on purpose: an HTTP error means the request
    happened and failed, and this means it never happened.
    """


def available() -> bool:
    """Whether a transport can exist at all. Both flags, and nothing else."""
    return market_providers.live_enabled()


def _fetch(url: str, headers: Mapping[str, str], timeout: float) -> object:
    """One request, decoded as JSON. Raises rather than returning a partial.

    The signature is `market_providers.Fetch` and nothing here knows what tier
    it is serving - the provider built the URL and the headers, and this
    carries them. That separation is why the providers are testable with a
    fabricated function and no network.
    """
    if not available():
        # Belt and braces: `transport()` already refuses to build a client
        # when the flags are off, so reaching here means somebody kept a
        # reference to `_fetch` across a settings change.
        raise TransportRefused(
            "public egress is disabled; both market_live_enabled and "
            "market_allow_public_egress must be true"
        )

    # GATE 2. The provider checked the URL it built; this checks the URL that
    # is actually about to be requested. Last thing before the socket.
    market_providers.check_host(url)

    sent = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    sent.update(dict(headers or {}))

    with httpx.Client(
        timeout=httpx.Timeout(timeout),
        # A 302 is a host the allowlist never saw. Following one would move
        # the destination outside the check that just passed.
        follow_redirects=False,
        # No cookie jar: nothing about one request may influence the next, and
        # a cookie is state a third party chose to put on this machine.
        cookies=None,
        trust_env=False,   # ignore ambient HTTP_PROXY/NO_PROXY surprises
    ) as client:
        response = client.get(url, headers=sent)

    if response.status_code >= 400:
        # The status and the HOST, never the URL: a URL can carry a key in a
        # query parameter, and this string reaches a log.
        raise httpx.HTTPStatusError(
            f"{response.status_code} from {response.request.url.host}",
            request=response.request, response=response,
        )
    if len(response.content) > MAX_RESPONSE_BYTES:
        raise TransportRefused(
            f"response from {response.request.url.host} is "
            f"{len(response.content)} bytes, over the "
            f"{MAX_RESPONSE_BYTES} limit"
        )
    return response.json()


def transport() -> market_providers.Fetch | None:
    """A callable that can make requests, or None.

    None IS THE DEFAULT AND None IS SAFE. `search_all` treats it as "no
    transport supplied" and reports a retrieval failure, so with the flags off
    the feature is inert and says so rather than silently appearing to work.

    GATE 1 is here: no client is constructed unless both flags are true, so
    the off state is the absence of a transport rather than the presence of an
    unused one.
    """
    if not available():
        return None
    return _fetch
