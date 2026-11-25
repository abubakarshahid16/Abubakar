"""Same paper, same comments? (order 14, #1911; used by `scripts/consistency_check.py`): a consistency check of TWO runs of the same paper. Pure code: no model, no answer key, no network.

The points of run A and run B (the "All points" sheet of the team file, or the page JSON's `points`) are MATCHED by RULE ID + FIELD + PAGE,
with the wording only as the last tie-break:

  1. same rule, same field, same page                      (tier "rule+field+page")
  2. same rule, same field, another page                   (tier "rule+field")
  3. same rule, the best wording of what is left (>= 0.6)  (tier "rule+wording"; the wording is only a tie-break inside one rule)

The rule id is the held standard and clause ("STD-X §4.2"); a point from no held standard has the topic of its checklist item instead. A point
is matched once. What is left is only in A or only in B. A matched pair whose verdict class differs (Met, Not met, Question) is a FLIP; a
change to or from any other label (an AI opinion, "does not apply") is counted apart as "other label change".

Every percentage states its denominator ("12 of 30"); with a denominator of 0 there is no percentage (an empty cell), never 0%.

The result is only a CONSISTENCY measure when both runs are the same version of the app on the same paper: the output says so in its first
line, and says "DIFFERENT VERSIONS, NOT A CONSISTENCY MEASURE" when the caller says they are not.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MET, NOT_MET, QUESTION, OPINION, OTHER = (
    "Met",
    "Not met",
    "Question",
    "AI opinion",
    "Other",
)
VERDICTS = (MET, NOT_MET, QUESTION)
KINDS = (NOT_MET, MET, QUESTION, OPINION, OTHER)
WORDING_MIN = 0.6
TIERS = ("rule+field+page", "rule+field", "rule+wording")
SAME_VERSION_LINE = "Same paper, same version: this is a consistency measure."
DIFFERENT_VERSION_LINE = "DIFFERENT VERSIONS, NOT A CONSISTENCY MEASURE: the differences below are the effect of the changes between the versions."


@dataclass
class Point:
    n: int
    rule: str
    field: str
    page: int | None
    label: str
    kind: str
    comment: str
    item: str
    topic: str = ""
    standard: str = ""
    clause: str = ""

    @property
    def field_key(self) -> str:
        return " ".join(self.field.casefold().split())


def kind_of(label: str | None) -> str:
    """The verdict class of a shown label: "Not met" / "Fail, compared by code" -> Not met; "Met" / "Pass, ..." -> Met; "Question" -> Question;
    anything with "opinion" -> AI opinion; else Other."""
    text = " ".join(str(label or "").casefold().split())
    if "opinion" in text:
        return OPINION
    if "not met" in text or text.startswith("fail"):
        return NOT_MET
    if "question" in text:
        return QUESTION
    if text.startswith("met") or text.startswith("pass") or " met" in f" {text}":
        return MET
    return OTHER


def _rule(standard: str, clause: str, topic: str, item: str) -> str:
    if standard:
        return f"{standard} §{clause}".strip() if clause else standard
    return "topic: " + (" ".join((topic or item or "").casefold().split()) or "unknown")


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _point(n, item, fld, page, label, comment, standard, clause, topic) -> Point:
    standard, clause = str(standard or "").strip(), str(clause or "").strip()
    return Point(
        n=_int(n) or 0, rule=_rule(standard, clause, str(topic or ""), str(item or "")), field=str(fld or "").strip(), page=_int(page),
        label=str(label or "").strip(), kind=kind_of(label), comment=str(comment or "").strip(), item=str(item or "").strip(),
        topic=str(topic or "").strip(), standard=standard, clause=clause,
    )  # fmt: skip


def load_sheet(path: str | Path) -> list[Point]:
    """The points of a team file: its "All points" sheet (the header row is the one that starts with "No.")."""
    import openpyxl

    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    try:
        if "All points" not in wb.sheetnames:
            raise ValueError("the file has no 'All points' sheet")
        rows = list(wb["All points"].iter_rows(values_only=True))
    finally:
        wb.close()
    head = next((i for i, r in enumerate(rows) if r and r[0] == "No."), None)
    if head is None:
        raise ValueError("the 'All points' sheet has no header row")
    cols = {str(h): i for i, h in enumerate(rows[head]) if h}
    out = []
    for r in rows[head + 1 :]:
        if not r or r[0] in (None, ""):
            continue

        def cell(name: str, r=r):
            i = cols.get(name)
            return r[i] if i is not None and i < len(r) else None

        out.append(_point(cell("No."), cell("Item"), cell("Field"), cell("Page"), cell("Shown label"), cell("Comment"),
                          cell("Standard"), cell("Clause"), cell("Topic")))  # fmt: skip
    return out


def load_page_json(data: dict) -> list[Point]:
    """The points of a general-review page JSON (`points`)."""
    return [
        _point(p.get("n"), p.get("item_id"), p.get("field"), p.get("page"), p.get("shown_label") or p.get("label"), p.get("comment"),
               p.get("standard"), p.get("clause"), p.get("topic"))
        for p in data.get("points") or []
    ]  # fmt: skip


def load(path: str | Path) -> list[Point]:
    path = Path(path)
    if path.suffix.lower() == ".json":
        import json

        return load_page_json(json.loads(path.read_text()))
    return load_sheet(path)


@dataclass
class Pair:
    a: Point
    b: Point
    tier: str

    @property
    def flip(self) -> bool:
        return (
            self.a.kind != self.b.kind
            and self.a.kind in VERDICTS
            and self.b.kind in VERDICTS
        )

    @property
    def other_change(self) -> bool:
        return self.a.kind != self.b.kind and not self.flip


@dataclass
class Result:
    pairs: list[Pair] = field(default_factory=list)
    only_a: list[Point] = field(default_factory=list)
    only_b: list[Point] = field(default_factory=list)
    a_total: int = 0
    b_total: int = 0


def _similar(x: Point, y: Point) -> float:
    return difflib.SequenceMatcher(
        None, x.comment.casefold(), y.comment.casefold()
    ).ratio()


def _pair_up(
    left: list[Point],
    right: list[Point],
    keyfn,
    tier: str,
    out: list[Pair],
    need_wording: bool = False,
) -> None:
    """Match `left` with `right` by `keyfn`; inside one key the best wording pairs first (the last tie-break). Matched points leave both lists."""
    groups: dict[Any, tuple[list[Point], list[Point]]] = {}
    for p in left:
        groups.setdefault(keyfn(p), ([], []))[0].append(p)
    for q in right:
        if keyfn(q) in groups:
            groups[keyfn(q)][1].append(q)
    for ls, rs in groups.values():
        scored = sorted(
            (
                (_similar(p, q), -i, -j, p, q)
                for i, p in enumerate(ls)
                for j, q in enumerate(rs)
            ),
            key=lambda t: t[:3],
            reverse=True,
        )
        used_l: set[int] = set()
        used_r: set[int] = set()
        for ratio, _i, _j, p, q in scored:
            if (
                id(p) in used_l
                or id(q) in used_r
                or (need_wording and ratio < WORDING_MIN)
            ):
                continue
            used_l.add(id(p))
            used_r.add(id(q))
            out.append(Pair(p, q, tier))
    gone_l = {id(p.a) for p in out if p.tier == tier}
    gone_r = {id(p.b) for p in out if p.tier == tier}
    left[:] = [p for p in left if id(p) not in gone_l]
    right[:] = [q for q in right if id(q) not in gone_r]


def compare(a: list[Point], b: list[Point]) -> Result:
    left, right = list(a), list(b)
    pairs: list[Pair] = []
    _pair_up(left, right, lambda p: (p.rule, p.field_key, p.page), TIERS[0], pairs)
    _pair_up(left, right, lambda p: (p.rule, p.field_key), TIERS[1], pairs)
    _pair_up(left, right, lambda p: p.rule, TIERS[2], pairs, need_wording=True)
    pairs.sort(key=lambda p: p.a.n)
    return Result(
        pairs=pairs, only_a=left, only_b=right, a_total=len(a), b_total=len(b)
    )


def pct(numerator: int, denominator: int) -> float | None:
    """A percentage, or None (never 0) when there is nothing to divide by. The caller always shows the denominator beside it."""
    return None if not denominator else round(100.0 * numerator / denominator, 1)


def pct_words(numerator: int, denominator: int) -> str:
    p = pct(numerator, denominator)
    return f"{numerator} of {denominator}" + (f" ({p:g}%)" if p is not None else "")


def counts(res: Result) -> dict[str, Any]:
    matched = len(res.pairs)
    flips = [p for p in res.pairs if p.flip]
    other = [p for p in res.pairs if p.other_change]
    by_tier = {t: sum(1 for p in res.pairs if p.tier == t) for t in TIERS}
    flip_types: dict[str, int] = {}
    for p in flips:
        key = (
            f"{p.a.kind} <-> {p.b.kind}"
            if VERDICTS.index(p.a.kind) < VERDICTS.index(p.b.kind)
            else f"{p.b.kind} <-> {p.a.kind}"
        )
        flip_types[key] = flip_types.get(key, 0) + 1
    union = matched + len(res.only_a) + len(res.only_b)
    per_kind: dict[str, dict[str, int]] = {}
    for kind in KINDS:
        in_a = [p for p in [x.a for x in res.pairs] + res.only_a if p.kind == kind]
        in_b = [p for p in [x.b for x in res.pairs] + res.only_b if p.kind == kind]
        per_kind[kind] = {
            "a_total": len(in_a),
            "a_matched": sum(1 for x in res.pairs if x.a.kind == kind),
            "a_same_verdict": sum(
                1 for x in res.pairs if x.a.kind == kind and x.b.kind == kind
            ),
            "b_total": len(in_b),
            "b_matched": sum(1 for x in res.pairs if x.b.kind == kind),
        }
    return {
        "a_total": res.a_total, "b_total": res.b_total, "matched": matched, "only_a": len(res.only_a), "only_b": len(res.only_b),
        "union": union, "flips": len(flips), "other_label_changes": len(other), "by_tier": by_tier, "flip_types": flip_types,
        "per_kind": per_kind,
    }  # fmt: skip


def summary_lines(
    res: Result, label_a: str, label_b: str, same_version: bool
) -> list[tuple[str, str]]:
    c = counts(res)
    lines = [
        (
            "Reading this file",
            SAME_VERSION_LINE if same_version else DIFFERENT_VERSION_LINE,
        ),
        ("Run A", f"{label_a}: {c['a_total']} points"),
        ("Run B", f"{label_b}: {c['b_total']} points"),
        (
            "Matched points",
            f"{pct_words(c['matched'], c['union'])} of all points in A or B",
        ),
        ("Matched, of A's points", pct_words(c["matched"], c["a_total"])),
        ("Matched, of B's points", pct_words(c["matched"], c["b_total"])),
        ("Only in A", pct_words(c["only_a"], c["a_total"]) + " of A's points"),
        ("Only in B", pct_words(c["only_b"], c["b_total"]) + " of B's points"),
        (
            "Same verdict, of the matched",
            pct_words(
                c["matched"] - c["flips"] - c["other_label_changes"], c["matched"]
            ),
        ),
        (
            "Verdict flips (Met / Not met / Question)",
            pct_words(c["flips"], c["matched"]) + " of the matched",
        ),
        (
            "Other label changes",
            pct_words(c["other_label_changes"], c["matched"]) + " of the matched",
        ),
    ]
    lines += [(f"  flip {k}", str(v)) for k, v in sorted(c["flip_types"].items())]
    lines += [
        (f"Matched by {t}", pct_words(n, c["matched"])) for t, n in c["by_tier"].items()
    ]
    return lines


def write_xlsx(
    res: Result, path: str | Path, label_a: str, label_b: str, same_version: bool
) -> Path:
    """The result as one team-readable workbook: Summary, By kind, Matched, Flips, Only in A, Only in B. No model, no document text beyond
    the comment lines the two sheets already hold."""
    import openpyxl
    from openpyxl.styles import Font

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws.append(["AI, to be checked"])
    for k, v in summary_lines(res, label_a, label_b, same_version):
        ws.append([k, v])
    ws["A1"].font = Font(bold=True)
    ws.column_dimensions["A"].width = 44
    ws.column_dimensions["B"].width = 110
    c = counts(res)
    kinds = wb.create_sheet("By kind")
    kinds.append(["Kind (the label in A, and in B)", "A: points", "A: matched", "A: matched, of A's points", "A: same verdict, of its matched",
                  "B: points", "B: matched", "B: matched, of B's points"])  # fmt: skip
    for kind, k in c["per_kind"].items():
        kinds.append([kind, k["a_total"], k["a_matched"], pct_words(k["a_matched"], k["a_total"]),
                      pct_words(k["a_same_verdict"], k["a_matched"]), k["b_total"], k["b_matched"], pct_words(k["b_matched"], k["b_total"])])  # fmt: skip
    for sheet in (kinds,):
        for col in "ABCDEFGH":
            sheet.column_dimensions[col].width = 26

    def head(sheet, names):
        sheet.append(names)
        for cell in sheet[1]:
            cell.font = Font(bold=True)

    matched = wb.create_sheet("Matched")
    head(
        matched,
        [
            "A No.",
            "B No.",
            "Matched by",
            "Rule",
            "Field (A)",
            "Page A",
            "Page B",
            "Label A",
            "Label B",
            "Verdict",
            "Wording A",
            "Wording B",
        ],
    )
    for p in res.pairs:
        verdict = (
            "FLIP" if p.flip else ("other label change" if p.other_change else "same")
        )
        matched.append(
            [
                p.a.n,
                p.b.n,
                p.tier,
                p.a.rule,
                p.a.field,
                p.a.page,
                p.b.page,
                p.a.label,
                p.b.label,
                verdict,
                p.a.comment,
                p.b.comment,
            ]
        )
    flips = wb.create_sheet("Flips")
    head(
        flips,
        [
            "A No.",
            "B No.",
            "Rule",
            "Field",
            "Page A",
            "Page B",
            "Label A",
            "Label B",
            "Wording A",
            "Wording B",
        ],
    )
    for p in res.pairs:
        if p.flip:
            flips.append(
                [
                    p.a.n,
                    p.b.n,
                    p.a.rule,
                    p.a.field,
                    p.a.page,
                    p.b.page,
                    p.a.label,
                    p.b.label,
                    p.a.comment,
                    p.b.comment,
                ]
            )
    for title, points in (("Only in A", res.only_a), ("Only in B", res.only_b)):
        sheet = wb.create_sheet(title)
        head(sheet, ["No.", "Rule", "Field", "Page", "Label", "Comment"])
        for p in points:
            sheet.append([p.n, p.rule, p.field, p.page, p.label, p.comment])
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(path))
    return path


def slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-") or "run"
