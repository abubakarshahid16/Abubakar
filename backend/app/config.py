from __future__ import annotations

import ipaddress
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ModelHostRefused(RuntimeError):
    """A model endpoint this system will not talk to.

    Deliberately NOT an `httpx` error. An HTTP error means the request
    happened and failed; this means it never happened, and the two must not be
    collapsed - `analysis._generate_or_refuse` turns an `httpx.HTTPError` into
    a polite "the model is unavailable", which is exactly the wrong answer for
    a misconfigured destination. A refusal has to be loud.
    """


class NotificationConfigError(RuntimeError):
    """SMTP notifications were enabled without a complete configuration."""


#: Host names that mean "this machine" without being an IP literal.
#: `localhost` only. NOT any name a resolver happens to point at 127.0.0.1: a
#: DNS name is somebody else's to change, and a check that trusts resolution
#: is a check whose answer can be edited from outside the machine.
LOOPBACK_NAMES = frozenset({"localhost"})


def model_host_of(url: str) -> str:
    """The host a request to `url` would actually be sent to, parsed properly.

    PARSED, NEVER SPLIT. `market_providers._host_of` extracts a host with
    `split("://")` / `split("@")` / `split(":")`, and that is a live bypass
    bug: `https://evil.test?@api.openalex.org/` has the authority
    `evil.test` (the `?` starts the query, so the `@` is inside it), while the
    hand-parser reads everything after the last `@` and reports
    `api.openalex.org`. It approves one host and requests another. This
    function asks `urllib.parse` - the same parser httpx uses to decide where
    to connect - so the string that is checked and the string that is dialled
    cannot disagree.

    Returns the lowercased host, or "" when the URL names none.
    """
    return (urlsplit(url).hostname or "").lower()


def check_model_url(
    url: str,
    *,
    allow_remote: bool = False,
    allowed_hosts: tuple[str, ...] = (),
) -> tuple[str, str | None]:
    """Validate the answer-model endpoint. Returns `(base_url, remote_host)`.

    `remote_host` is None for the normal loopback case and the host name when
    a deliberately permitted non-loopback host was accepted - the caller uses
    it to decide whether an audit row is owed. Anything else raises
    `ModelHostRefused`.

    THE PROMISE THIS ENFORCES. README:14 and ADR-0002 say client document
    content never leaves this machine. The prompt posted to this endpoint
    carries retrieved passages verbatim (`answer._build_prompt`,
    `synthesis.build_prompt`), so this URL is the largest outbound lane in the
    system and it was an unvalidated `.env` string with a loopback *default*
    and no check of any kind. One wrong `OLLAMA_URL` sent document text to an
    arbitrary host, silently. See docs/status-honesty-audit.md entry 25.

    WHY NON-LOOPBACK IS REFUSED BY DEFAULT AND NOT MERELY WARNED ABOUT. A
    model on another host - however private the network - is the ADR's
    forbidden "hosted inference API" as far as the client's documents are
    concerned: the passages leave this machine, and no wording of "private
    subnet" changes what left. So loopback-only is the default and the
    refusal is total. A deployment that genuinely runs the model on another
    box must say so TWICE, on the market lane's two-flag precedent:
    `answer_model_allow_remote_host` (this deployment permits it at all) and
    `answer_model_allowed_hosts` (this exact destination). One careless edit
    cannot open the lane, and using it writes an audit row.

    Errors name the HOST and never the whole URL: a URL can carry credentials
    or a key in a query string, and these strings reach logs and API
    responses. Same rule as `market_transport._fetch`.
    """
    parts = urlsplit(url.strip())

    if parts.scheme not in ("http", "https"):
        raise ModelHostRefused(
            f"answer model URL has scheme {parts.scheme!r}; only http and "
            f"https are usable, and a missing scheme means the value is not a "
            f"URL at all"
        )

    host = (parts.hostname or "").lower()
    if not host:
        raise ModelHostRefused(
            "answer model URL names no host; refusing to guess one")

    # Credentials in the URL are refused rather than stripped. A value shaped
    # like `http://user:pass@host` is either an accident or a proxy nobody
    # documented; sending a prompt built from client documents through it is
    # not something to do on a silent guess. Checked BEFORE the loopback test
    # so `http://user:pass@127.0.0.1` is refused too.
    if parts.username or parts.password:
        raise ModelHostRefused(
            f"answer model URL for host {host!r} carries embedded "
            f"credentials; refused (the value is not echoed, it may hold a "
            f"secret)"
        )

    # A base URL is a scheme, a host and a port. A path, query or fragment
    # here means the value is not what this setting is for - and it is also
    # the shape the `?@` bypass hides in, so refusing it closes that family
    # of value twice over, independently of the parse.
    if parts.path.strip("/") or parts.query or parts.fragment:
        raise ModelHostRefused(
            f"answer model URL for host {host!r} carries a path, query or "
            f"fragment; this setting is a base URL (scheme, host, port) and "
            f"the request path is appended by the transport"
        )

    loopback = host in LOOPBACK_NAMES
    if not loopback:
        try:
            loopback = ipaddress.ip_address(host.strip("[]")).is_loopback
        except ValueError:
            loopback = False   # a name that is not `localhost`: not loopback

    base = f"{parts.scheme}://{parts.netloc}"
    if loopback:
        return base, None

    if not allow_remote:
        raise ModelHostRefused(
            f"answer model host {host!r} is not loopback. The prompt sent to "
            f"this host contains retrieved document passages, and ADR-0002 "
            f"says client document content never leaves this machine. Set "
            f"answer_model_allow_remote_host=true AND list the host in "
            f"answer_model_allowed_hosts to override deliberately; the "
            f"override is audited."
        )
    if host not in tuple(h.lower() for h in allowed_hosts):
        raise ModelHostRefused(
            f"answer model host {host!r} is not in answer_model_allowed_hosts. "
            f"Permitting remote inference is not permitting every host: the "
            f"flag says this deployment may, the list says which."
        )
    return base, host

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    # ANCHORED, like every other path in this class. It was `".env"` - a
    # relative path, resolved by pydantic-settings against the process working
    # directory - while `data_dir`, `db_path` and the model directories were
    # all built from BACKEND_DIR. So the database and the models were found
    # wherever the process started, and the file deciding whether anyone needs
    # to log in was not.
    #
    # Launched from the repository root, `backend/.env` was simply not read:
    #
    #     from repo root :  auth_mode = disabled       secret len = 0
    #     from backend/  :  auth_mode = demo_required  secret len = 64
    #
    # A security control that can be switched on and stay off, with no error
    # and no log line. The startup guard in auth.py that refuses a weak secret
    # under `demo_required` could not help, because it never saw
    # `demo_required` - the same mechanism that disabled the control also
    # bypassed its guard.
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env", extra="ignore")

    # Bind loopback only. Never 0.0.0.0 - document content must not be reachable.
    host: str = "127.0.0.1"
    port: int = 8000

    data_dir: Path = BACKEND_DIR / "data"
    upload_dir: Path = BACKEND_DIR / "data" / "uploads"
    db_path: Path = BACKEND_DIR / "data" / "rag_intelligence.sqlite"

    embed_model_dir: Path = BACKEND_DIR / "models" / "e5-small"

    # ------------------------------------------------------------------ OCR
    #: Weights are VENDORED and addressed by explicit path. RapidOCR resolves
    #: an unset model_path by downloading from modelscope.cn on first
    #: construction, which fails on an air-gapped machine at the first
    #: recognition rather than at install. Staged by scripts/fetch_models.py.
    #: `disabled` (default) or `demo_required`. Disabled must behave exactly as
    #: the system did before authorisation existed, so every pre-existing test
    #: passes unchanged with it off - which is what proves the enforcement is
    #: additive, and what makes the rollback a config change rather than a
    #: revert. The enforcement path runs in BOTH modes; only the contents of
    #: the scope differ.
    auth_mode: str = "disabled"

    #: HMAC signing key for bearer tokens. Empty is FINE under `disabled` and
    #: refused at STARTUP under `demo_required` - a system that boots and then
    #: rejects everyone looks broken, and one that boots with a guessable key
    #: looks like it is working. See auth.check_secret_or_refuse.
    auth_secret: str = ""
    #: Eight hours, and no refresh token. A refresh flow exists to make short
    #: tokens tolerable; a long token is the alternative to it, not a
    #: companion. Justified against this system: a Tier 2 answer takes ~50 s
    #: and an ingest runs for minutes, so a short token means a login screen
    #: appearing in the middle of a demo.
    auth_token_seconds: int = 8 * 60 * 60
    #: Failed logins per email before a lockout, and the window. In memory,
    #: never a table: a row per failed login would let anyone who can reach
    #: the port write to the SQLite file ingestion is using.
    auth_max_attempts: int = 8
    auth_lockout_seconds: int = 300

    ocr_model_dir: Path = BACKEND_DIR / "models" / "ocr"
    ocr_det_model: str = "PP-OCRv6_det_tiny.onnx"
    #: The recogniser is the open decision. PP-OCRv6 ships no English model, so
    #: this multilingual one can emit CJK into an English document - measured:
    #: 凤, 日, ≦ for "Save". `en_PP-OCRv5_rec_mobile.onnx` cannot, by
    #: construction, at 2.16 s/page against 0.90. Switch when the client
    #: confirms whether the corpus contains Arabic. See ADR-0005.
    ocr_rec_model: str = "PP-OCRv6_rec_tiny.onnx"
    ocr_cls_model: str = "ch_ppocr_mobile_v2.0_cls_mobile.onnx"

    #: 150, measured, not assumed. 300 dpi produced WORSE text on these
    #: documents for 39% more time and 186 MB more RSS - it splits words and
    #: drops letters from proper names. See ADR-0005.
    ocr_dpi: int = 150
    #: Kept ON. Turning it off saved 1% and changed the output on 2 of 12
    #: pages; a 1% saving is not worth a behaviour change.
    ocr_use_cls: bool = True
    #: Bounded explicitly. Never -1: that takes all 12 logical cores and
    #: allocates a per-thread arena each, which is how the reranker came to
    #: reserve 829 MB for a 22 MB model.
    # Laptop-safe defaults: OCR is CPU-heavy and a second worker competes with
    # the local answer model for all cores and memory.
    ocr_threads: int = 1
    ocr_rec_batch: int = 2
    ocr_max_side_len: int = 2000
    #: Memory-bound, not CPU-bound, and ONE - corrected by measuring the real
    #: stage rather than one worker in isolation. Isolated workers peaked at
    #: 524-549 MB, which suggested two would fit in the 1.15 GiB free at demo
    #: time. Running the actual stage measured the WHOLE operation, parent plus
    #: children at their simultaneous peak: 1,399 MB for two workers against
    #: 598 MB for one. Two do not fit. NOT scaled to cores - that is how the
    #: reranker came to reserve 829 MB for a 22 MB model.
    ocr_processes: int = 1
    ocr_batch_size: int = 8
    #: Characters outside this script in recognised text are a recognition
    #: failure, not a curiosity. Counted and flagged, never deleted.
    ocr_expected_script: str = "latin"

    #: THE ANSWER MODEL'S ADDRESS, AND THE ONE OUTBOUND URL ON THE QUERY PATH
    #: THAT CARRIES DOCUMENT TEXT. Validated by `check_model_url`, at startup
    #: (below) and again immediately before every request
    #: (`model_transport`). The default has always been loopback; what was
    #: missing was anything that made the default a rule.
    ollama_url: str = "http://127.0.0.1:11434"
    #: Does this DEPLOYMENT permit the answer model to live on another host.
    #: False, and false means refused rather than warned about: the passages in
    #: the prompt would leave this machine. Two settings on the
    #: `market_live_enabled` / `market_allow_public_egress` precedent, so
    #: opening this lane cannot be one careless edit.
    answer_model_allow_remote_host: bool = False
    #: WHICH host, if the flag above is set. Empty by default, so the flag
    #: alone still refuses everything. Checked with a real URL parser, never a
    #: string split - see `model_host_of`.
    answer_model_allowed_hosts: tuple[str, ...] = ()
    answer_model: str = "qwen3.5:4b"
    #: Resident size of the answer model. Used to warn BEFORE someone presses
    #: Explain: with 14.7 GB of 16 GB already in use, Tier 2 will swap hard or
    #: fail, and that is a fact worth surfacing before the button is clicked
    #: rather than after a two-minute stall in front of a client.
    answer_model_ram_bytes: int = 3_400_000_000

    # Measured on the target CPU - see docs/benchmarks.md
    num_thread: int = 12
    num_batch: int = 2048
    # 1536 -> 4096, and this is a DECISION, not a tuning pass. The execution
    # plan's change budget forbade touching model settings mid-sprint so the
    # evidence base would stay comparable; the project owner overrode that
    # after the measurement in #82, which showed why: at 1536 the evidence
    # budget fits TWO passages, so a question naming two documents can never
    # show the model both of them, and every multi-document feature was
    # structurally impossible rather than merely weak. Measured on the same
    # question, same machine (1.6 GB free): 1536 -> two passages, model
    # correctly refuses, 18 s; 4096 -> six of eight passages, a correct
    # doc17-vs-doc20 comparison, 88 s. The cost is real and is stated here so
    # nobody reads the slower answer as a regression. Below ~1.5 GB free the
    # 4B model swaps regardless of this value.
    num_ctx: int = 4096

    # -------------------------------- model-assisted requirement matching
    #
    # THE SECOND TIER OF §14, AND IT ONLY EVER CHOOSES. The model is handed a
    # numbered list Python built and may pick one entry or decline; it never
    # names a field, never sees a value or a unit, and never sets a status.
    # Containment runs first and the model is consulted only where containment
    # found nothing.

    #: OFF BY DEFAULT, AND IT FAILED ITS OWN GATE TO GET HERE.
    #:
    #: Measured on datasheet 1, 2026-09-19 (§10 of
    #: docs/design/model-assisted-matching.md): 37 requirements reached the
    #: model, it declined 30 and proposed 7 pairings. SIX WERE FALSE FRIENDS
    #: and three of those produced a NON_COMPLIANT verdict against the
    #: contractor - a weld-cleaning distance paired with a corrosion
    #: allowance, an interpass temperature with a service temperature, a
    #: cooling-water outlet with a vessel design temperature. Every one of
    #: them cited correctly, which is what makes a wrong pairing dangerous
    #: rather than obviously broken.
    #:
    #: The design's hard gate is zero false pairings, so the tier does not run
    #: until it is redesigned. The code stays: it is tested, it is honest
    #: about why it declined, and the one genuine pairing it found is recall
    #: containment structurally cannot reach.
    #:
    #: False turns the tier off entirely and the findings SAY SO in their
    #: rationale - a review that silently stopped asking would look identical
    #: to one where the model declined every time.
    match_enabled: bool = False
    #: Generous, because a refusal costs more than a wait: a timeout is
    #: `model_unavailable` and the requirement falls back to
    #: MISSING_INFORMATION, so a tight bound would quietly convert slow
    #: hardware into missing pairings.
    match_timeout_seconds: float = 30.0
    #: Fixed seed. The determinism check calls twice and refuses to pair when
    #: the two answers disagree, which is only meaningful if the sampler is
    #: pinned - with a random seed every requirement would be a coin toss
    #: tossed twice.
    match_seed: int = 0
    #: A CEILING ON A REVIEW, not a tuning knob. §10 of the design expects
    #: tens of calls per review on this corpus; a review that wants hundreds
    #: has a pre-filter defect, and the budget makes that visible as
    #: `model_budget` on the remaining requirements instead of as an hour of
    #: silence.
    match_max_calls_per_run: int = 200
    #: Raised from 100 after measuring what the gold questions actually need.
    #: At 100, 5 of 12 Tier 2 generations stopped mid-sentence and one stopped
    #: inside a citation marker. At 250, 0 of 12 did, and the largest answer
    #: used 108 tokens - so 250 is roughly twice the observed worst case rather
    #: than a round number.
    #:
    #: This costs nothing in latency for answers that already fit: num_predict
    #: is a CEILING, not a target, and a generation that finishes early stops
    #: early. Measured medians moved in both directions across the four
    #: questions (Q1 19.9->24.3s, Q2 21.9->16.1s, Q4 30.5->25.6s), which is
    #: machine noise, not a cost. The extra tokens are paid only by the answers
    #: that were previously being cut off.
    max_output_tokens: int = 250
    temperature: float = 0.1

    upload_chunk_bytes: int = 1024 * 1024
    #: Ceiling on a single upload, enforced DURING the stream in
    #: `upload.stream_to_temp` - the count is checked per block and the read
    #: aborts the moment it is exceeded, rather than discovering afterwards
    #: that the whole file was already on disk. This is the only unbounded
    #: untrusted input in the system.
    #:
    #: SET FROM MEASUREMENT, not from a round number. The largest document
    #: ingested is book4 at 37.6 MB / 1,400 pages (27.5 KB per page); the
    #: corpus ranges 3.6-27.5 KB per page. 512 MB is 13.6x that largest file
    #: and about 19,000 pages at the observed density - comfortably above any
    #: real specification, while bounding what a single malicious request can
    #: write to a volume with ~45 GB free. The previous value of 2048 MB was
    #: 54x the largest real document and had never been measured against
    #: anything.
    max_upload_mb: int = 512
    page_batch_size: int = 32
    extract_processes: int = 1
    embed_batch_size: int = 16

    # ------------------------------------------------------- job retries (#177)
    #: How many times a failed stage is RE-TRIED before it is poisoned. Three
    #: retries is four attempts in all. Small on purpose: every stage here is
    #: deterministic local work, so a failure that survives four attempts
    #: spread over several minutes is a property of the input, not bad luck,
    #: and retrying it further only burns the one worker's time.
    job_max_retries: int = 3
    #: First retry delay in seconds; each later retry doubles it (60, 120,
    #: 240 s by default). See `job_queue.backoff_seconds`.
    job_retry_base_seconds: float = 60.0

    # ------------------------------------------------------- watched folder
    #: The drop folder. EMPTY IS THE DEFAULT AND EMPTY MEANS OFF - there is no
    #: separate `watch_enabled` boolean, because two settings that can disagree
    #: are two settings that eventually do: a folder configured with the
    #: boolean left false is a client dropping documents into a system that is
    #: not looking, and reports nothing wrong. One value, and its emptiness is
    #: the switch.
    #:
    #: FROM `.env` AND FROM NOWHERE ELSE. Never a request body, never a query
    #: parameter, never an admin form. A path supplied by a caller is a
    #: file-disclosure hole: the watcher reads whatever directory it is given
    #: and copies what it finds into a corpus the caller can then search, so a
    #: client-settable path turns "read my drop folder" into "read any folder
    #: this process can open". The value being operator-supplied at deploy time
    #: is what makes reading it safe at all - and it is still withheld from
    #: non-administrators by /api/watch/status, because host filesystem layout
    #: is not corpus data.
    #:
    #: A str rather than a Path, deliberately: `Path("")` is `.`, so an unset
    #: Path setting would silently mean "watch the working directory". The
    #: emptiness has to survive being read.
    watch_folder: str = ""
    #: Five minutes. This is a POLL, not an OS filesystem event subscription -
    #: a network share and a synced folder both fail to deliver events, and the
    #: client's drop folder is expected to be one or the other. Polling costs a
    #: directory listing per interval, which is nothing, and it is the same
    #: code path on every kind of volume.
    #:
    #: Latency is not the constraint people expect it to be: a file is only
    #: eligible once it has been seen UNCHANGED on two consecutive scans, so a
    #: document appears in the corpus one to two intervals after it is dropped
    #: regardless. That two-scan rule is what stops a half-copied 40 MB PDF
    #: being ingested as a truncated document, and shortening this interval
    #: buys latency at the cost of making that race likelier on a slow share.
    watch_interval_seconds: int = 300
    #: WHO the documents the folder brings in belong to. An email of an
    #: EXISTING user, and empty by default.
    #:
    #: A file sitting in a folder carries no identity. Somebody put it there
    #: and the filesystem does not record who in any way this system can
    #: trust, so the two available answers were to invent a service account -
    #: a permanent false record of who supplied every document the client ever
    #: drops - or to have the administrator STATE which real person owns what
    #: the folder brings in. This is the second. `admin.grant_on_upload` then
    #: gives the document exactly the grants a manual upload by that user
    #: would have given it: their disciplines, plus the admin capability. No
    #: more, and it is deliberately the same call rather than a similar one.
    #:
    #: WITHOUT THIS THE FEATURE DOES NOTHING under `AUTH_MODE=demo_required`,
    #: which is the only mode anyone deploys. `document_role_access` is
    #: written by `admin.grant()` and by nothing else, so a document ingested
    #: with no owner is readable by nobody - not by an engineer, not by an
    #: administrator - while holding disk and occupying the worker. The
    #: watcher refuses rather than creating one, and this setting is what
    #: turns that refusal into an ingest.
    #:
    #: FROM `.env` AND FROM NOWHERE ELSE, for a sharper reason than the path
    #: is. This value decides WHO CAN READ the documents: a request that could
    #: set it could point the folder's output at its own roles and read every
    #: specification the client drops. It is an access-control decision, and
    #: access-control decisions in this system come from the grant tables and
    #: from operator configuration, never from a caller.
    #:
    #: The named user must hold a DISCIPLINE role. One who does not would send
    #: every dropped document to no discipline at all, which is the orphan
    #: again wearing a name; the watcher checks and says so rather than
    #: ingesting into a void. See `watcher.resolve_owner`.
    watch_owner_email: str = ""

    # ------------------------------------------------------- watched folder
    #: The drop folder. EMPTY IS THE DEFAULT AND EMPTY MEANS OFF - there is no
    #: separate `watch_enabled` boolean, because two settings that can disagree
    #: are two settings that eventually do: a folder configured with the
    #: boolean left false is a client dropping documents into a system that is
    #: not looking, and reports nothing wrong. One value, and its emptiness is
    #: the switch.
    #:
    #: FROM `.env` AND FROM NOWHERE ELSE. Never a request body, never a query
    #: parameter, never an admin form. A path supplied by a caller is a
    #: file-disclosure hole: the watcher reads whatever directory it is given
    #: and copies what it finds into a corpus the caller can then search, so a
    #: client-settable path turns "read my drop folder" into "read any folder
    #: this process can open". The value being operator-supplied at deploy time
    #: is what makes reading it safe at all - and it is still withheld from
    #: non-administrators by /api/watch/status, because host filesystem layout
    #: is not corpus data.
    #:
    #: A str rather than a Path, deliberately: `Path("")` is `.`, so an unset
    #: Path setting would silently mean "watch the working directory". The
    #: emptiness has to survive being read.
    watch_folder: str = ""
    #: Five minutes. This is a POLL, not an OS filesystem event subscription -
    #: a network share and a synced folder both fail to deliver events, and the
    #: client's drop folder is expected to be one or the other. Polling costs a
    #: directory listing per interval, which is nothing, and it is the same
    #: code path on every kind of volume.
    #:
    #: Latency is not the constraint people expect it to be: a file is only
    #: eligible once it has been seen UNCHANGED on two consecutive scans, so a
    #: document appears in the corpus one to two intervals after it is dropped
    #: regardless. That two-scan rule is what stops a half-copied 40 MB PDF
    #: being ingested as a truncated document, and shortening this interval
    #: buys latency at the cost of making that race likelier on a slow share.
    watch_interval_seconds: int = 300
    #: WHO the documents the folder brings in belong to. An email of an
    #: EXISTING user, and empty by default.
    #:
    #: A file sitting in a folder carries no identity. Somebody put it there
    #: and the filesystem does not record who in any way this system can
    #: trust, so the two available answers were to invent a service account -
    #: a permanent false record of who supplied every document the client ever
    #: drops - or to have the administrator STATE which real person owns what
    #: the folder brings in. This is the second. `admin.grant_on_upload` then
    #: gives the document exactly the grants a manual upload by that user
    #: would have given it: their disciplines, plus the admin capability. No
    #: more, and it is deliberately the same call rather than a similar one.
    #:
    #: WITHOUT THIS THE FEATURE DOES NOTHING under `AUTH_MODE=demo_required`,
    #: which is the only mode anyone deploys. `document_role_access` is
    #: written by `admin.grant()` and by nothing else, so a document ingested
    #: with no owner is readable by nobody - not by an engineer, not by an
    #: administrator - while holding disk and occupying the worker. The
    #: watcher refuses rather than creating one, and this setting is what
    #: turns that refusal into an ingest.
    #:
    #: FROM `.env` AND FROM NOWHERE ELSE, for a sharper reason than the path
    #: is. This value decides WHO CAN READ the documents: a request that could
    #: set it could point the folder's output at its own roles and read every
    #: specification the client drops. It is an access-control decision, and
    #: access-control decisions in this system come from the grant tables and
    #: from operator configuration, never from a caller.
    #:
    #: The named user must hold a DISCIPLINE role. One who does not would send
    #: every dropped document to no discipline at all, which is the orphan
    #: again wearing a name; the watcher checks and says so rather than
    #: ingesting into a void. See `watcher.resolve_owner`.
    watch_owner_email: str = ""

    # Chunking. e5-small has a hard 512-token limit; stay below it so the
    # model never silently truncates a chunk.
    chunk_target_tokens: int = 300
    chunk_overlap_tokens: int = 60
    chunk_max_tokens: int = 480

    # Retrieval. Defaults chosen from measurement on this CPU, not by guess:
    # reranking 30 candidates at 320 tokens costs ~1025ms, 20 at 256 costs
    # ~500ms, which is what keeps the Tier 1 answer inside its 1-2s budget.
    search_candidates: int = 30       # retrieved from each side before fusion
    #: How many candidates the cross-encoder sees. Reduced from 20 to claw
    #: back the latency that widening the rerank window cost, measured over
    #: the independent 15-question set:
    #:
    #:   candidates   retrieval  citation  tokens  refusal  false  median
    #:           20      10/10       9/9   10/10      5/5      0   2213 ms
    #:           16      10/10       9/9   10/10      5/5      0   1961 ms
    #:           12       9/10       8/9    9/10      5/5      0   1712 ms
    #:           10      10/10       9/9   10/10      5/5      0   1697 ms
    #:
    #: 16, not 10. The result is NOT monotonic - 12 degrades and 10 recovers -
    #: which means the shortlist composition is changing under the questions
    #: rather than the depth being genuinely unnecessary. One perfect run at 10
    #: sitting next to a degraded run at 12 is noise, not evidence, so 16 keeps
    #: a margin above the unstable region for the 250 ms it costs.
    rerank_candidates: int = 16
    #: MUST cover chunk_max_tokens, or the cross-encoder judges a chunk on a
    #: fragment of it and is asked to rate relevance it was never shown.
    #:
    #: At 256 this silently broke every long chunk. NORSOK's clause 11 holds
    #: Table 3 flattened to 486 tokens, and "Holiday detection NACE RP0188
    #: voltage" sits at token 350 - so the reranker scored the passage on its
    #: first 256 tokens, which are about environmental conditions and visual
    #: examination, and returned -10.95. That score was CORRECT about what it
    #: had been given and wrong about the passage. The evaluation recorded it
    #: as a retrieval failure, and it was a truncation failure.
    #:
    #: Measured cost of covering the whole chunk, 20 candidates, median of 5:
    #:   256 tokens   583 ms
    #:   320 tokens   603 ms
    #:   384 tokens   910 ms
    #:   480 tokens   796 ms
    #:   512 tokens  1182 ms
    #: +213 ms against 256, which keeps Tier 1 inside its 1-2 second target.
    rerank_max_tokens: int = 480
    rerank_batch: int = 16

    #: ONNX Runtime's CPU arena allocator reserves large per-thread blocks
    #: and never returns them. Measured on this machine (16 GB, 12 threads):
    #:
    #:                       process RSS   tier-1 query   embed
    #:   both arenas on          3,247 MB       ~1,926 ms   6.9 c/s
    #:   rerank off, embed on    2,438 MB       ~2,493 ms   6.8 c/s
    #:   both off                  503 MB       ~2,500 ms   5.7 c/s
    #:
    #: Rerank scores are BIT-IDENTICAL either way (np.array_equal, max diff
    #: 0.0) - arena configuration changes allocation, not arithmetic. So there
    #: is no accuracy trade here, but there IS a latency one: roughly 2.7 GB
    #: against roughly 575 ms.
    #:
    #: DEFAULT IS ON, deliberately. Two hypotheses for turning it off were
    #: tested and both failed:
    #:   * that it would recover the latency lost to memory pressure - it does
    #:     not, it costs latency
    #:   * that freeing memory would speed up Explain, which needs ~2.5 GB for
    #:     qwen3.5:4b - measured warm, Explain is 7.4-7.9 s with the arena on
    #:     against 8.3-10.5 s with it off. A 63 s Explain measured earlier was
    #:     Ollama's cold model load, not the arena.
    #: Left configurable because 503 MB against 3,247 MB is a real option on a
    #: machine that demos at 92% RAM - but it buys stability, not speed.
    onnx_cpu_arena_rerank: bool = True
    onnx_cpu_arena_embed: bool = True
    # Small-to-big. Retrieval runs on the small chunk; the reader is shown
    # the surrounding parent block, expanded to neighbours up to this many
    # characters. The generated budget is smaller because three sources have
    # to fit inside num_ctx alongside the prompt.
    answer_context_chars: int = 2400
    generated_context_chars: int = 1200
    running_line_threshold: float = 0.03   # fraction of pages; a running head repeats per chapter, not book-wide
    # Only the top/bottom N lines of a page are considered for running
    # header/footer removal. NORSOK stacks four lines of furniture -
    # "NORSOK standard M-501" / "Rev. 5, June 2004" / "NORSOK standard" /
    # "Page 6 of 20" - so a 3-line window caught the first three and left the
    # page number prepended to the text of nearly every chunk. The short-page
    # guard inside strip_running_lines keeps a wider window safe.
    running_line_scan_lines: int = 5

    # Content-quality gate. A chunk failing these does not read like natural
    # language and is stored but not retrievable. Tuned against known-good
    # book1 prose and known-bad book2 symbol-font tables.
    quality_min_alpha_ratio: float = 0.55
    quality_max_symbol_ratio: float = 0.20
    quality_min_wordish_ratio: float = 0.45
    quality_min_avg_word_len: float = 2.5
    quality_max_unbroken_run: int = 45
    quality_max_control_chars: int = 3      # only the top/bottom N lines of a page

    # ------------------------------------------- live public-market egress
    #: THE MASTER SWITCH, and it is OFF. With this false the product behaves
    #: EXACTLY as it did before any of the market provider code existed:
    #: `market.findings()` returns the labelled samples, `market.egress_state()`
    #: reports both flags false, and no provider is constructed. That identity
    #: is asserted by a test rather than asserted here, because "behaves the
    #: same" is a claim about behaviour and belongs in something that runs.
    #:
    #: It is a separate flag from `allow_public_egress` on purpose. This one
    #: says "the feature is built and wired"; that one says "this deployment
    #: permits traffic to leave". Both must be true for anything to be sent,
    #: so switching the feature on in a build cannot by itself open egress on
    #: a client machine.
    #:
    #: FROM `.env` AND FROM NOWHERE ELSE, for the same reason as
    #: `watch_owner_email`: a request that could set this could turn on
    #: outbound network access for the process holding the client's corpus.
    #: That is an operator decision, never a caller's.
    market_live_enabled: bool = False

    #: The second half of the switch: does this DEPLOYMENT permit egress.
    #: Kept distinct so the two questions - "is the feature finished" and "is
    #: this machine allowed to talk to the internet" - cannot be answered by
    #: one careless edit.
    market_allow_public_egress: bool = False

    # ------------------------------------------------- the standards reader
    #
    # THE SAME TWO-FLAG SHAPE AS THE MARKET LANE ABOVE, and here it guards
    # more: what leaves is CLAUSE TEXT FROM THE CLIENT'S STANDARDS, not a
    # human-typed search phrase. Both flags must be true before
    # `reader_api.build_request` will build anything. A fresh install calls
    # nothing.
    #
    # WHY THESE MOVED HERE. `reader_api.ReaderSettings.from_env` read them
    # from `os.environ`, and `backend/.env` NEVER REACHES `os.environ` -
    # pydantic-settings populates this model and exports nothing. Measured:
    # `AUTH_MODE` is in that file, `settings.auth_mode` is `demo_required`,
    # and `"AUTH_MODE" in os.environ` is False. So a key placed in the file
    # rule 2 names as its only home was invisible to the reader, which
    # refused with "no API key in the environment" - and the two flags could
    # not be switched on from that file at all. `extra="ignore"` meant the
    # keys were dropped with no error and no log line, which is the same
    # shape as the defect recorded above `model_config`.
    #
    # The alternative was `load_dotenv`, one line, which would copy EVERY
    # secret in that file into the process environment - `AUTH_SECRET`
    # included, where it is not today. Three fields is more code and keeps
    # the blast radius at three names.
    standards_reader_enabled: bool = False

    #: The second half of the switch: does this DEPLOYMENT permit standards
    #: text to leave the machine. Distinct from the flag above for the same
    #: reason the market lane keeps its two apart.
    standards_reader_allow_public_egress: bool = False

    #: FROM `backend/.env` AND FROM NOWHERE ELSE. Never a default, never a
    #: literal, never logged and never echoed in an error - `.gitleaks.toml`
    #: exists because a key in a source tree is a key that has been
    #: published. It stays on this model rather than being exported to
    #: `os.environ`, so it cannot be inherited by a subprocess or read out of
    #: a dump of one.
    anthropic_api_key: str = ""

    #: THE ONE HOST ALLOWLIST. Every outbound URL any tier builds is checked
    #: against this and refused if its host is not here. One list, in one
    #: place, so "where can this talk to" has a single answer that can be read
    #: without grepping three provider modules.
    #:
    #: CODE-LEVEL ALLOWLISTING IS DEFENCE IN DEPTH AND NOT THE CONTROL. A
    #: process that can open a socket can reach any host it likes; this list
    #: only stops the code in THIS repository from doing so by accident or
    #: through a mistaken config value. The real control is an OS-level
    #: firewall rule (or an egress proxy) restricting the backend process to
    #: these hosts, applied outside the application, where the application
    #: cannot edit it. This list is what makes an accident loud; the firewall
    #: is what makes a deliberate exfiltration hard.
    #:
    #: No tier-1 host is listed by default because no tier-1 vendor is chosen.
    market_allowed_hosts: tuple[str, ...] = (
        "api.openalex.org",
        "en.wikipedia.org",
    )

    #: Tier 1, general web search. GENERIC NAME, not a vendor's.
    #:
    #: The vendor originally suggested has started asking for a billing
    #: address, so the choice is unsettled. A setting called
    #: `tavily_api_key` would have to be renamed the day that changes, and
    #: renaming an environment variable on a client's machine is a silent
    #: breakage: the old name keeps being read from their `.env`, resolves to
    #: nothing, and the tier reports itself unconfigured while the operator
    #: believes they configured it. The vendor is named by
    #: `market_search_provider` and the credential is generic, so swapping
    #: vendors is a value change rather than a rename.
    #:
    #: EMPTY IS A NORMAL STATE, not an error. Tier 1 unconfigured means tier 1
    #: is not attempted, which is reported in `tiers_attempted`, and tiers 2
    #: and 3 still answer.
    market_search_api_key: str = ""
    #: Which tier-1 adapter to use. Empty means no tier-1 provider at all.
    #: Named separately from the key so a key can be present while the vendor
    #: is switched off, which is what you want while testing a migration.
    market_search_provider: str = ""
    #: The tier-1 endpoint, config-driven so a vendor swap needs no code
    #: change. Its host is still checked against `market_allowed_hosts`, so
    #: setting this alone cannot open a new destination.
    market_search_endpoint: str = ""

    #: Tier 2, OpenAlex. THE OPERATOR'S ADDRESS, NEVER THE CLIENT'S, and
    #: EMPTY BY DEFAULT.
    #:
    #: OpenAlex asks for a contact address to put a caller in its "polite
    #: pool" - better rate limits in exchange for being identifiable. That is
    #: a reasonable trade for whoever RUNS this software and an unreasonable
    #: one to make on the client's behalf: their address in an outbound query
    #: string tells OpenAlex which organisation is researching which
    #: standards, which is exactly the kind of inference this product exists
    #: to prevent. So it defaults to empty, the tier works without it on the
    #: common pool, and if it is set it must be the address of the operator
    #: deploying the system.
    market_openalex_contact_email: str = ""

    #: PER-TIER TIMEOUT. An offline-first product must not hang because
    #: somebody's network is slow. These are deliberately short: the feature
    #: is advisory background context, and a reader waiting on a spinner for a
    #: "reference - background only" row is worse served than one told the
    #: tier did not answer.
    market_tier_timeout_seconds: float = 6.0

    #: PER-TIER RATE LIMIT, as a minimum interval between outbound calls to
    #: the same tier. Not a quota: a floor on spacing, which is the shape that
    #: protects a free public API from a user holding down a button. Tier 2
    #: and tier 3 are donated public infrastructure and being a bad citizen on
    #: them is both rude and a fast route to being blocked.
    market_tier_min_interval_seconds: float = 1.0

    # ------------------------------------------------------------- notifications
    # Disabled by default: the local-only product must not open an SMTP
    # connection merely because a reminder was calculated. When enabled, the
    # validator below requires an explicit server, sender and recipient.
    smtp_enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_recipient: str = ""
    smtp_starttls: bool = True
    smtp_timeout_seconds: float = 10.0
    # Scheduled summaries are opt-in. The worker calls notifications.run_scheduled_summary.
    summary_schedule: str = "disabled"  # disabled, daily, weekly
    summary_hour_utc: int = 8
    summary_weekday_utc: int = 0  # Monday=0

    @model_validator(mode="after")
    def _refuse_a_non_local_answer_model(self) -> "Settings":
        """The process refuses to start on a misconfigured model host.

        FAILING CLOSED, AT THE EARLIEST POSSIBLE MOMENT. Audit entry 24 - the
        pre-commit hook that warned and exited 0 - is the reason this raises:
        a control whose absence is invisible is not a control, so a bad
        `OLLAMA_URL` stops the backend rather than logging something nobody
        reads and then posting the client's passages anyway.

        This is NOT the only gate, and deliberately so. `settings` is a live
        object: a test or a plugin can assign `settings.ollama_url` after
        import and pydantic does not revalidate on assignment. So
        `model_transport` checks again with the same function immediately
        before the socket - the market lane's gate-1/gate-2 arrangement, for
        the same reason: the early check can be bypassed, and the late one
        cannot be bypassed by anything short of editing that file.
        """
        check_model_url(
            self.ollama_url,
            allow_remote=self.answer_model_allow_remote_host,
            allowed_hosts=self.answer_model_allowed_hosts,
        )
        return self

    @model_validator(mode="after")
    def _validate_smtp_notifications(self) -> "Settings":
        """Fail closed when outbound notifications are explicitly enabled."""
        if not self.smtp_enabled:
            return self
        missing = [name for name, value in (
            ("SMTP_HOST", self.smtp_host),
            ("SMTP_FROM", self.smtp_from),
            ("SMTP_RECIPIENT", self.smtp_recipient),
        ) if not str(value).strip()]
        if missing:
            raise NotificationConfigError(
                "SMTP notifications are enabled but missing: "
                + ", ".join(missing))
        if not 1 <= self.smtp_port <= 65535:
            raise NotificationConfigError("SMTP_PORT must be between 1 and 65535")
        if bool(self.smtp_username) != bool(self.smtp_password):
            raise NotificationConfigError(
                "SMTP_USERNAME and SMTP_PASSWORD must be provided together")
        if self.smtp_timeout_seconds <= 0:
            raise NotificationConfigError("SMTP_TIMEOUT_SECONDS must be positive")
        return self

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.upload_dir):
            d.mkdir(parents=True, exist_ok=True)


settings = Settings()

#: The settings that can change an ANSWER. Kept beside the settings so the list
#: drifts with them rather than living in the reports module and going stale.
#: Deliberately excludes host, port, paths and auth: a report generated on a
#: different port is not a different answer.
ANSWER_AFFECTING_SETTINGS = (
    "answer_model", "num_ctx", "max_output_tokens", "temperature",
    "chunk_target_tokens", "chunk_overlap_tokens", "chunk_max_tokens",
    "search_candidates", "rerank_candidates", "rerank_max_tokens",
    "generated_context_chars", "answer_context_chars",
    "ocr_rec_model", "ocr_expected_script",
)


def config_version() -> str:
    """First 16 hex of a hash over the answer-affecting settings, sorted.

    Stamped on every report so two reports can be told apart when the answer
    machinery changed between them, and NOT told apart when only the port did.
    """
    import hashlib
    import json

    subset = {k: getattr(settings, k) for k in sorted(ANSWER_AFFECTING_SETTINGS)}
    return hashlib.sha256(
        json.dumps(subset, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:16]
