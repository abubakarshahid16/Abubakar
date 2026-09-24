"""One interface for "give this bounded packet to a model and tell me exactly
what answered".

WHY THIS EXISTS. Today nothing in the system can say WHICH model produced an
answer. `review_runs.model_name` is NULL on every row and nothing writes it;
there is no `provider`, no `model_tag` and no digest column anywhere; and on
the local path the information was available and thrown away, because Ollama
reports the tag it loaded in every response and `synthesis.Generation` kept
only the text. That is B54, and it is symmetric - neither engine recorded
itself, so provenance is not a cost of adding a second provider. It is a debt
the first one already had.

So provenance is not an optional field here. A `Response` cannot be built
without a provider name, and the model tag is whatever the ENGINE reported,
never what configuration asked for: a floating tag can move under a running
system, and that is precisely the case where the recorded value earns its keep.

WHAT THIS IS NOT. It is not a refactor of the `claude_*` modules. Those take
an injected `model_call(prompt) -> str` and each one owns a prompt builder, a
`Reason` enum and gates that encode measured defects; flattening them into a
generic interface would spend risk in the wrong place for no gain. When cloud
processing is authorised in writing, `ClaudeProvider` becomes a thin adapter
over the existing `reader_api` / `reader_transport` client - one request
builder, one socket, one audit line - and those modules are left alone.

EGRESS. `OllamaProvider` is local and carries no egress question: it talks to
the URL `model_transport` validates, which is loopback unless an explicit
allow-list says otherwise. A future `ClaudeProvider` inherits the two existing
flags (`STANDARDS_READER_ENABLED`, `STANDARDS_READER_ALLOW_PUBLIC_EGRESS`) and
any new switch is ANDed with them, never ORed - a second switch that can turn
egress ON is not a guard, it is a bypass.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Protocol

from . import model_transport
from .config import settings

#: Every provider name that may appear in a stored answer. A closed set,
#: because "which engine produced this" is a question with a finite list of
#: answers and an open string invites a typo to become a new provider.
OLLAMA = "ollama"
CLAUDE = "claude"
PROVIDERS = (OLLAMA, CLAUDE)


class ProviderRefused(RuntimeError):
    """The provider would not make the call, and says why.

    A refusal is not an empty answer. The distinction is the same one B44 draws
    for an unreadable file and B50 for an unparseable response: "it did not
    happen, here is the reason" and "it happened and produced nothing" are
    different facts, and only one of them is about the model.
    """


@dataclass(frozen=True)
class Packet:
    """What is sent. Built by Python, never by a model.

    `num_ctx` and `num_predict` are REQUIRED and explicit. The Phase A matrix
    was run with them pinned for exactly this reason: a defaulted context
    window silently changes what the model saw between two runs that are then
    compared as if they were the same test.
    """

    prompt: str
    num_ctx: int
    num_predict: int
    temperature: float = 0.0
    #: Off by default. Measured on the frozen packet: thinking on cost roughly
    #: seven times the wall time for the same answer, and twice ran out of
    #: budget inside the thinking channel and returned nothing at all.
    think: bool = False
    seed: int | None = None
    options: dict[str, object] = field(default_factory=dict)
    #: #180: base64-encoded images for a vision-capable model, sent in
    #: Ollama's `images` field. Empty for every text packet, whose request
    #: body is then byte-for-byte what it was before images existed.
    images: tuple[str, ...] = ()
    #: #180: seconds the transport waits. `model_transport.post_json` REQUIRES
    #: one, and this interface used to pass none - see `OllamaProvider.reason`.
    timeout_s: float = 300.0

    @property
    def sha256(self) -> str:
        """What was actually sent, so a result can be tied to its input.

        The images are part of it: one prompt over two different page images
        is two different inputs. A text packet hashes exactly as it always
        did, so no stored `prompt_sha256` changes meaning.
        """
        digest = hashlib.sha256(self.prompt.encode("utf-8"))
        for image in self.images:
            digest.update(b"\x00image\x00")
            digest.update(image.encode("ascii"))
        return digest.hexdigest()


@dataclass(frozen=True)
class Response:
    """What came back, and what produced it.

    `provider` and `model_tag` are not optional and not defaulted: a stored
    answer that cannot name its engine is a claim without provenance.
    `finish_reason` carries Ollama's `done_reason` verbatim, because "stop" and
    "length" are different outcomes and a truncated answer that reads as
    complete is the failure mode the Phase A runs hit twice.
    """

    text: str
    provider: str
    #: As the ENGINE reported it, never as configuration asked for it.
    model_tag: str
    #: sha256 of the response text. There is no content-addressed digest from
    #: either engine, so this is ours: it identifies the answer, not the model.
    digest: str
    finish_reason: str
    prompt_sha256: str
    tokens_in: int | None = None
    tokens_out: int | None = None
    wall_time_s: float = 0.0
    thinking: str = ""

    def __post_init__(self) -> None:
        if self.provider not in PROVIDERS:
            raise ValueError(f"unknown provider {self.provider!r}; expected one of {PROVIDERS}")
        if not self.model_tag:
            raise ValueError(
                "a response with no model tag cannot be stored: provenance is "
                "the one thing this interface exists to guarantee")

    @property
    def truncated(self) -> bool:
        """The cap ended it, not the model - `synthesis.Generation`'s rule."""
        return self.finish_reason == "length"


class ReasoningProvider(Protocol):
    """One method. A third provider must require no change to any caller."""

    name: str

    def reason(self, packet: Packet) -> Response: ...


class OllamaProvider:
    """The local engine, through the one transport allowed to reach it.

    Never calls httpx itself: `model_transport` is on the socket allow-list
    that `test_socket_containment` enforces across the whole package, and it
    re-validates the URL immediately before the socket. A module that opened
    its own connection would fail that test by construction, which is the
    point of it.
    """

    name = OLLAMA

    def __init__(self, model: str | None = None) -> None:
        #: Configuration's ANSWER, not the engine's. Recorded separately from
        #: the tag the response reports, so the two can disagree visibly.
        self.requested_model = model or settings.answer_model

    def reason(self, packet: Packet) -> Response:
        options: dict[str, object] = {
            "temperature": packet.temperature,
            "num_ctx": packet.num_ctx,
            "num_predict": packet.num_predict,
            **packet.options,
        }
        if packet.seed is not None:
            options["seed"] = packet.seed
        body = {
            "model": self.requested_model,
            "prompt": packet.prompt,
            "stream": False,
            "think": packet.think,
            "options": options,
        }
        if packet.images:
            body["images"] = list(packet.images)
        started = time.time()
        try:
            # #180: the timeout is REQUIRED by `post_json` (keyword-only, no
            # default). It was missing, so every real call raised TypeError
            # and surfaced as a ProviderRefused - invisible to tests whose
            # fakes took `**kwargs`. Measured when the vision reader made the
            # first real call through this seam.
            raw = model_transport.post_json("/api/generate", body,
                                            timeout=packet.timeout_s)
        # Broad on purpose, and it RE-RAISES: every transport failure becomes a
        # named refusal rather than an empty answer. No `noqa` is needed -
        # ruff's blind-except rule is about swallowing, which this does not do.
        except Exception as exc:
            raise ProviderRefused(f"{self.name}: {type(exc).__name__}: {exc}") from exc
        wall = time.time() - started

        text = str(raw.get("response") or "").strip()
        # THE ENGINE'S OWN ANSWER about what ran. Falling back to the requested
        # tag would quietly paper over precisely the case worth recording - a
        # floating tag that resolved to something else - so the fallback is
        # marked rather than silent.
        reported = str(raw.get("model") or "")
        model_tag = reported or f"{self.requested_model} (unreported)"
        return Response(
            text=text,
            provider=self.name,
            model_tag=model_tag,
            digest=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            finish_reason=str(raw.get("done_reason") or ""),
            prompt_sha256=packet.sha256,
            tokens_in=raw.get("prompt_eval_count"),
            tokens_out=raw.get("eval_count"),
            wall_time_s=round(wall, 3),
            thinking=str(raw.get("thinking") or ""),
        )
