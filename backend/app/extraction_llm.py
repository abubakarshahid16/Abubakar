"""Layer 1: the LLM reads a datasheet page, Python verifies every claim.

The model is INJECTED as a callable (page_prompt -> raw text), so this module
never imports a transport and tests standalone with a fake model. The real
caller passes a closure over model_transport.post_json.

The contract that makes hallucination impossible to smuggle through:
every extracted fact must carry `quote` - the exact text the model read the
value from - and accept() keeps a fact only when the quote genuinely appears
on the page AND the value appears inside the quote. A fact the model imagined
has no true quote to give.

Pre-built and pre-tested by Cowork (8 tests) on cowork/layer1-llm-extraction.
See docs/design/layer1-llm-extraction.md for the experiment protocol.
"""
import json
import re

PROMPT = """You are reading one page of an engineering datasheet.
List every field that has a stated value. For each, give:
- field: the label, exactly as printed
- value: the value as printed (keep units out of it when they are separate)
- unit: the unit if printed, else null
- quote: the EXACT text of the row you read this from, copied verbatim

Rules: never invent; a blank field is skipped; "By Contractor" or "*" means
blank - skip it; copy quotes character-for-character.
Answer as JSON only: {"facts": [{"field":..., "value":..., "unit":..., "quote":...}]}

PAGE TEXT:
"""


def _fold(text: str) -> str:
    """Whitespace-insensitive form, so a quote broken across lines still
    matches the page it truly came from."""
    return re.sub(r"\s+", " ", text).strip().lower()


def parse_response(raw: str) -> tuple[list[dict], str | None]:
    """Strict parse. Anything malformed yields no facts and a reason -
    a reason, never a guess."""
    try:
        body = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return [], "model_malformed"
    facts = body.get("facts") if isinstance(body, dict) else None
    if not isinstance(facts, list):
        return [], "model_malformed"
    out = []
    for f in facts:
        if not isinstance(f, dict) or not f.get("field") or not f.get("quote"):
            continue
        out.append({"field": str(f["field"]), "value": f.get("value"),
                    "unit": f.get("unit"), "quote": str(f["quote"])})
    return out, None


def accept(facts: list[dict], page_text: str) -> dict:
    """The no-lying gate. A fact survives only when:
    1. its quote appears on the page (whitespace-folded), and
    2. its value appears inside its own quote.
    Everything else is rejected WITH the reason kept, so the report can say
    'the model imagined N rows' with names."""
    page = _fold(page_text)
    accepted, rejected = [], []
    for f in facts:
        q = _fold(f["quote"])
        if not q or q not in page:
            rejected.append({**f, "reason": "quote_not_on_page"})
            continue
        v = _fold(str(f["value"])) if f.get("value") not in (None, "") else ""
        if v and v not in q:
            rejected.append({**f, "reason": "value_not_in_quote"})
            continue
        accepted.append(f)
    return {"accepted": accepted, "rejected": rejected}


def extract_page(page_text: str, model_call, second_call=None) -> dict:
    """One page through the model and the gate. When `second_call` is given
    (usually the same model again), both runs must agree per fact - a fact
    only one run produced drops as unstable, the same determinism rule the
    matcher tier used."""
    facts1, err = parse_response(model_call(PROMPT + page_text))
    if err:
        return {"accepted": [], "rejected": [], "error": err}
    if second_call is not None:
        facts2, err2 = parse_response(second_call(PROMPT + page_text))
        if err2:
            return {"accepted": [], "rejected": [], "error": err2}
        keys2 = {(_fold(f["field"]), _fold(str(f.get("value"))))
                 for f in facts2}
        stable = [f for f in facts1
                  if (_fold(f["field"]), _fold(str(f.get("value")))) in keys2]
        dropped = [{**f, "reason": "model_unstable"} for f in facts1
                   if f not in stable]
        gate = accept(stable, page_text)
        gate["rejected"].extend(dropped)
        return gate
    return accept(facts1, page_text)
