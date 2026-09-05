"""Public market information: a fixture, labelled as one, that cannot pretend.

THIS MACHINE IS OFFLINE AND THIS MODULE MAKES NO NETWORK CALL. There is no
provider, no HTTP client, no URL that resolves. Every row is loaded from
`samples/market_sample.json`, every row carries `is_sample: true`, and every
URL is `sample://` - a scheme no browser will fetch, chosen so a row cannot be
turned into a real citation by clicking it.

WHY A FIXTURE AT ALL. The screen exists so the shape of the feature can be
reviewed before egress is ever considered: what a finding looks like, where the
verification state sits, and what a reader is told about how it was obtained.
A blank panel would leave that unreviewed until the day the network is opened,
which is the worst day to discover the labelling is wrong.

THE ONE RULE. A sample row is never presented as a source. It is enforced three
ways rather than by intention:

  * `is_sample` is not optional and not defaulted. `_load` REFUSES a row that
    lacks it or sets it false, at load time, so a fixture edited later cannot
    silently become "real".
  * `verification` may only be `source_not_verified` for a sample. Nothing here
    has been read, so nothing here may claim it was.
  * The response carries `egress` stating that web search is off and public
    egress is blocked, so the panel's own banner is driven by the API rather
    than hard-coded in the component.

EGRESS. `PublicMarketQuery` is the only object that would ever leave this
machine, and building one is a preview - it is never sent. It is assembled from
the caller's own words plus two public fields, and NEVER from retrieved
document text: a query built from a client's specification would exfiltrate
that specification to a search engine one word at a time. `preview_query`
therefore takes a query string from the caller and refuses to accept passages.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

SAMPLE_PATH = Path(__file__).resolve().parent / "samples" / "market_sample.json"

#: The only verification state a fixture may carry. Nothing here was read.
SAMPLE_VERIFICATION = "source_not_verified"

#: A scheme that resolves nowhere, on purpose.
SAMPLE_SCHEME = "sample://"

NOTICE = (
    "SAMPLE DATA - NOT LIVE. This machine is offline. Every row is an "
    "illustrative placeholder: no publisher, URL or figure is real, and none "
    "may be described as market research, live data, or a source."
)


class SampleIntegrityError(Exception):
    """A fixture row that could be mistaken for a real finding."""


def _check(row: dict, index: int) -> dict:
    """Refuse anything that could read as real. At LOAD time, not at render."""
    where = f"market_sample.json row {index}"
    if row.get("is_sample") is not True:
        raise SampleIntegrityError(
            f"{where}: is_sample is {row.get('is_sample')!r}. Every row in this "
            f"file must be marked as a sample; there is no live provider to "
            f"produce a real one."
        )
    url = str(row.get("url") or "")
    if not url.startswith(SAMPLE_SCHEME):
        raise SampleIntegrityError(
            f"{where}: url {url!r} is not {SAMPLE_SCHEME}. A fetchable URL on a "
            f"sample row is a citation waiting to be believed."
        )
    if row.get("verification") != SAMPLE_VERIFICATION:
        raise SampleIntegrityError(
            f"{where}: verification is {row.get('verification')!r}. Nothing in "
            f"this file has been read, so no row may claim it was."
        )
    return {
        "claim": row["claim"],
        "url": url,
        "publisher": row["publisher"],
        "published_at": row.get("published_at"),
        "retrieved_at": row["retrieved_at"],
        "verification": SAMPLE_VERIFICATION,
        "is_sample": True,
    }


@lru_cache(maxsize=1)
def _load() -> tuple[dict, ...]:
    data = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
    rows = data.get("findings") or []
    if not rows:
        # An empty panel would render as "no market findings", which reads as
        # a measurement. There are no findings because there is no provider.
        raise SampleIntegrityError("market_sample.json carries no findings")
    return tuple(_check(row, i) for i, row in enumerate(rows))


def reload_samples() -> None:
    """For tests that write their own fixture."""
    _load.cache_clear()


def egress_state() -> dict:
    """What this build will and will not do. Read by the panel's banner."""
    return {"web_search_enabled": False, "allow_public_egress": False}


def findings() -> dict:
    return {
        "notice": NOTICE,
        "egress": egress_state(),
        "findings": list(_load()),
        # Said in the payload as well as in the rows, so a caller that renders
        # only the list still has somewhere to read it from.
        "is_sample": True,
    }


def preview_query(query: str, country: str | None = None,
                  freshness_days: int | None = None) -> dict:
    """Build the object that WOULD be sent, and do not send it.

    Nothing here touches the corpus. A query assembled from retrieved document
    text would exfiltrate the client's specification to a search engine one
    phrase at a time, so the only inputs are the caller's own words and two
    public fields.
    """
    return {
        "query": " ".join((query or "").split())[:200],
        "country": country,
        "freshness_days": freshness_days,
        # Stated in the response so a client cannot show a "Search" button that
        # implies otherwise.
        "would_be_sent_to": None,
        "sent": False,
        "reason": (
            "Public egress is disabled in this build. This is what would be "
            "sent if it were enabled; nothing left this machine."
        ),
    }
