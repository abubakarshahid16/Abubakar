"""The competition judge: extracted facts vs hand-counted ground truth.

Ground truth rows are {field, value} as a human read them off the page.
Matching is forgiving on spelling (folded), strict on substance."""
import re


def _fold(t) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(t).lower()).strip()


def score(extracted: list[dict], truth: list[dict]) -> dict:
    t_pairs = {(_fold(r["field"]), _fold(r["value"])) for r in truth}
    e_pairs = {(_fold(r["field"]), _fold(r.get("value"))) for r in extracted}
    hits = t_pairs & e_pairs
    return {
        "truth_rows": len(t_pairs),
        "read_correctly": len(hits),
        "missed": sorted(t_pairs - e_pairs),
        "extra_or_wrong": sorted(e_pairs - t_pairs),
        "recall": round(len(hits) / len(t_pairs), 3) if t_pairs else None,
        "precision": round(len(hits) / len(e_pairs), 3) if e_pairs else None,
    }
