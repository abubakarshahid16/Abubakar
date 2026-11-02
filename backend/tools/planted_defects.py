"""#1607 (plan change 6 D): planted-defect sheets, and the score of the review on them.

    python scripts/planted_defects.py generate --out DIR
    python scripts/planted_defects.py score --db <COPY of the database> [--reader rules]

GENERATOR. A base datasheet (`eval/planted/<name>.json`: invented or public values
only) gives one clean PDF per control and one PDF per planted defect, each with ONE
known defect and an answer beside it: which field, which defect, the verdict wanted
(does not meet, or Query). The file names and the print say nothing of the plant.

SCORER. Each sheet goes through the review a real upload gets (`upload`, `extract`,
`chunker`, the role hooks, `review_jobs.run`), on a copy of the database passed in,
in a folder beside it. A row counts as caught only when the clean sheet does not
have that row with that status, so a Query the clean sheet has anyway catches
nothing. A planted defect with no such row and a Pass on its field is the headline.

RISK AND COVERAGE per equipment type: the sheets carry a known answer, so risk is
measured here, where the stored runs mostly say "not measured". Two sides, never added:
a planted defect (decided: Fail or Pass on its field; wrong: the Pass) and the clean
sheet's checklist rows (the counts of `coverage_pair`; wrong: a Fail). A review that
failed everything would have no wrong plant, so the clean side has to be printed.

Rule 13: nothing here names an equipment type, a field or a layout; a new kind of
equipment is a new base file. No verdict code changes. Nothing is sent to Claude
(`no_claude` in every reader mode). The output holds counts and sheet names of
invented sheets only, never a row from the database's own documents.
"""

from __future__ import annotations

import contextlib
import copy
import json
import os
import re
import tempfile
from pathlib import Path

import pymupdf

REPO = Path(__file__).resolve().parents[2]
BASES = REPO / "eval" / "planted"

#: The verdicts an answer may want, in the words of the owner's order.
WANTED = ("does_not_meet", "query")
DEFECTS = (
    "over_limit",
    "wrong_unit",
    "blank_required",
    "contradictory",
    "wrong_sign",
    "wrong_field",
    "missing_page",
)
#: rules: the rule readers, no model. fake: the rule readers plus a stand-in for
#: the AI reader that echoes what is printed (a perfect local reader, through the
#: real merge). local-model: the configured local engine (only when released).
READERS = ("rules", "fake", "local-model")

FAIL = "NON_COMPLIANT"
PASS = "COMPLIANT"
#: `review_audit.VERDICT`: what the CRS and the owner call a Query.
QUERY = ("MISSING_INFORMATION", "NEEDS_ENGINEER_REVIEW", "CONDITIONAL")
#: `presence_check.STATUS`, a test holds them together.
STATED = "STATED_NOT_CHECKED"

A4 = (595, 842)
FONT = 9
#: An invented revision table, as a real form carries one on every sheet.
REVISION_BLOCK = [
    ("Rev", "Date", "Description", "Prepared", "Checked", "Approved"),
    ("0", "01 Nov 2026", "Issued for review", "A. B.", "C. D.", "E. F."),
]


# ------------------------------------------------------------------ the base


def check_base(base: dict) -> dict:
    """The base, or ValueError: invented or public only (the repo is public)."""
    if base.get("source") not in ("invented", "public"):
        raise ValueError("a base datasheet must be marked invented or public")
    if base.get("format") != "planted-base/1":
        raise ValueError(f"unknown base format {base.get('format')!r}")
    return base


def load_base(path: Path) -> dict:
    return check_base(json.loads(Path(path).read_text(encoding="utf-8")))


def _rows(sheet: dict) -> list[dict]:
    return [row for page in sheet["pages"] for row in page["rows"]]


def _row(sheet: dict, role: str) -> dict:
    for row in _rows(sheet):
        if row["role"] == role:
            return row
    raise ValueError(f"no field {role!r} on this base")


def control_sheet(base: dict, control: dict) -> dict:
    sheet = copy.deepcopy(base)
    for role, value in control.get("set", {}).items():
        _row(sheet, role)["value"] = value
    return sheet


def _negated(value: str) -> str:
    return value[1:] if value.startswith("-") else f"-{value}"


def _other_page(sheet: dict, role: str) -> dict:
    """A page the field is not on, so a second value sits apart from the first."""
    for page in sheet["pages"]:
        if not any(r["role"] == role for r in page["rows"]):
            return page
    raise ValueError(f"field {role!r} is on every page")


def plant(base: dict, plant_spec: dict) -> tuple[dict, dict]:
    """One copy of the clean sheet with one defect, and its answer."""
    defect, wanted = plant_spec.get("defect"), plant_spec.get("wanted")
    if defect not in DEFECTS:
        raise ValueError(f"unknown defect {defect!r}")
    if wanted not in WANTED:
        raise ValueError(f"unknown wanted verdict {wanted!r}")
    sheet = control_sheet(base, base["controls"][0])
    field = plant_spec.get("field")
    fields, planted, original, page_no = [field], None, None, None
    if defect == "missing_page":
        page_no = plant_spec["page"]
        fields = [r["role"] for r in sheet["pages"][page_no - 1]["rows"]]
        planted, original = "page removed", f"page {page_no}"
        sheet["printed_sheets"] = len(sheet["pages"])
        sheet["sheet_numbers"] = [
            i for i in range(1, len(sheet["pages"]) + 1) if i != page_no
        ]
        del sheet["pages"][page_no - 1]
    else:
        row = _row(sheet, field)
        original = row["value"]
        if defect == "over_limit":
            row["value"] = planted = plant_spec["value"]
        elif defect == "wrong_unit":
            original = row.get("unit")
            row["unit"] = planted = plant_spec["unit"]
        elif defect == "blank_required":
            row["value"], planted = "", ""
        elif defect == "contradictory":
            planted = plant_spec["value"]
            _other_page(sheet, field)["rows"].append({**row, "value": planted})
        elif defect == "wrong_sign":
            row["value"] = planted = _negated(row["value"])
        elif defect == "wrong_field":
            other = _row(sheet, plant_spec["with"])
            fields = [field, plant_spec["with"]]
            for key in ("value", "unit"):
                row_value, other_value = row.get(key), other.get(key)
                _put(row, key, other_value)
                _put(other, key, row_value)
            planted = row["value"]
    answer = {
        "format": "planted-answer/1",
        "base": base["name"],
        "defect": defect,
        "fields": fields,
        "labels": [_row(base, role)["field"] for role in fields],
        "original": original,
        "planted": planted,
        "wanted": wanted,
    }
    if page_no is not None:
        answer["page"] = page_no
    return sheet, answer


def _put(row: dict, key: str, value) -> None:
    if value is None:
        row.pop(key, None)
    else:
        row[key] = value


# ------------------------------------------------------------------ the print


def render_pdf(sheet: dict, path: Path, *, doc_no: str) -> None:
    """A plain ruled three-column sheet: Item, Offered, Unit. The same bytes every run."""
    pdf = pymupdf.open()
    numbers = sheet.get("sheet_numbers") or range(1, len(sheet["pages"]) + 1)
    total = sheet.get("printed_sheets") or len(sheet["pages"])
    for number, page_data in zip(numbers, sheet["pages"], strict=True):
        page = pdf.new_page(width=A4[0], height=A4[1])
        page.insert_text((50, 50), sheet["title"], fontsize=13)
        page.insert_text((50, 68), f"Document no: {doc_no}", fontsize=FONT)
        page.insert_text(
            (50, 82), f"Revision: 0    Sheet {number} of {total}", fontsize=FONT
        )
        page.insert_text((50, 110), page_data["heading"], fontsize=11)
        rows = [("Item", "Offered", "Unit")] + [
            (r["field"], r["value"], r.get("unit", "")) for r in page_data["rows"]
        ]
        _grid(page, 50, 120, (240, 150, 80), rows)
        _grid(page, 50, 740, (50, 80, 170, 60, 60, 50), REVISION_BLOCK)
    pdf.set_metadata({})
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    pdf.save(str(path), garbage=4, deflate=True, no_new_id=True)
    pdf.close()


def _grid(page, x0: int, y0: int, widths: tuple, rows: list[tuple]) -> None:
    height = 20
    x1 = x0 + sum(widths)
    for i in range(len(rows) + 1):
        page.draw_line((x0, y0 + i * height), (x1, y0 + i * height), width=0.6)
    x = x0
    for width in (0, *widths):
        x += width
        page.draw_line((x, y0), (x, y0 + len(rows) * height), width=0.6)
    for r, cells in enumerate(rows):
        x = x0
        for width, text in zip(widths, cells, strict=True):
            if text:
                page.insert_text((x + 4, y0 + r * height + 14), text, fontsize=FONT)
            x += width


def write_set(base: dict, out: Path) -> dict:
    """Every control and every plant of one base, with neutral file names. Returns
    the manifest, also written as `manifest.json`."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    jobs = [
        (
            control_sheet(base, c),
            {
                "format": "planted-answer/1",
                "base": base["name"],
                "control": c["name"],
                "fields": [],
                "wanted": None,
            },
        )
        for c in base["controls"]
    ] + [plant(base, p) for p in base["plants"]]
    sheets = []
    for number, (sheet, answer) in enumerate(jobs, start=1):
        name = f"{base['name']}-{number:02d}"
        doc_no = f"{base['doc_prefix']}-{number:04d}"
        pdf, ans = f"{name}.pdf", f"{name}.answer.json"
        render_pdf(sheet, out / pdf, doc_no=doc_no)
        answer = {**answer, "sheet": pdf, "printed": _printed_rows(sheet)}
        (out / ans).write_bytes(
            (json.dumps(answer, indent=1, ensure_ascii=False) + "\n").encode("utf-8")
        )
        sheets.append(
            {
                "sheet": pdf,
                "answer": ans,
                "control": answer.get("control"),
                "defect": answer.get("defect"),
                "fields": answer["fields"],
                "wanted": answer["wanted"],
            }
        )
    manifest = {
        "format": "planted-set/1",
        "base": base["name"],
        "equipment_type": base["equipment_type"],
        "sheets": sheets,
    }
    (out / "manifest.json").write_bytes(
        (json.dumps(manifest, indent=1, ensure_ascii=False) + "\n").encode("utf-8")
    )
    return manifest


def _printed_rows(sheet: dict) -> list[dict]:
    """What each kept page prints, for the stand-in reader only."""
    numbers = range(1, len(sheet["pages"]) + 1)
    return [
        {
            "page": n,
            "role": r["role"],
            "field": r["field"],
            "value": r["value"],
            "unit": r.get("unit"),
        }
        for n, page in zip(numbers, sheet["pages"], strict=True)
        for r in page["rows"]
    ]


# ------------------------------------------------------------------ the judgement


def judge(answer: dict, rows: list[dict], clean: list[dict]) -> dict:
    """What the review made of one plant. `rows`: this sheet's findings; `clean`: the
    clean control's. Only a row the clean sheet lacks can catch the plant or be new."""
    wanted_fields = set(answer["fields"])
    seen = {(r["key"], r["status"]) for r in clean}
    fresh = [r for r in rows if (r["key"], r["status"]) not in seen]
    raised = [r for r in fresh if r["status"] == FAIL or r["status"] in QUERY]
    on_field = [r for r in raised if r["roles"] & wanted_fields]
    passes = [r for r in rows if r["status"] == PASS and r["roles"] & wanted_fields]
    if any(r["status"] == FAIL for r in on_field):
        got = "fail"
    elif on_field:
        got = "query"
    else:
        got = "wrongly_passed" if passes else "missed"
    as_wanted = got == {"does_not_meet": "fail", "query": "query"}.get(answer["wanted"])
    return {
        "got": got,
        "as_wanted": as_wanted,
        "false_new": len(raised) - len(on_field),
        "also_passed": len(passes) if on_field else 0,
        "caught_ids": [r["id"] for r in on_field if r.get("id")],
    }


def per_kind(sheets: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for sheet in sheets:
        slot = out.setdefault(
            sheet["defect"],
            {
                "planted": 0,
                "fail": 0,
                "query": 0,
                "missed": 0,
                "wrongly_passed": 0,
                "not_run": 0,
                "as_wanted": 0,
                "on_crs": 0,
                "false_new": 0,
            },
        )
        slot["planted"] += 1
        slot[sheet["got"]] += 1
        slot["as_wanted"] += int(bool(sheet.get("as_wanted")))
        slot["on_crs"] += int(bool(sheet.get("on_crs")))
        slot["false_new"] += sheet.get("false_new") or 0
    return out


def _type_of(item: dict) -> str:
    from app.coverage_pair import NO_TYPE

    return item.get("equipment_type") or NO_TYPE


def _one_pair(kind: str, applicable: int, decided: int, wrong: int) -> dict:
    """In the shape `coverage_pair.by_equipment_type` adds, so the one adder is used."""
    return {
        "equipment_type": kind,
        "applicable": applicable,
        "decided": decided,
        "risk": {"measured": True, "wrong": wrong, "decided": decided},
        "wrong_verdicts": {"all": wrong},
    }


def _add_pairs(pairs: list[dict], kind: str) -> dict | None:
    from app.coverage_pair import by_equipment_type

    mine = [p for p in pairs if p["equipment_type"] == kind]
    return by_equipment_type(mine)[kind] if mine else None


def _read_otherwise(item: dict) -> bool:
    return bool(item.get("equipment_type")) and item.get("typed_as") != item.get(
        "equipment_type"
    )


def _of_type(items: list[dict], kind: str) -> list[dict]:
    return [item for item in items if _type_of(item) == kind]


def per_type(sheets: list[dict], controls: list[dict]) -> dict[str, dict]:
    """Risk and coverage per equipment type: `planted` and `clean` stay apart. A sheet
    that did not run is in neither and is counted as not run; `None`: nothing to count."""
    ran = [s for s in sheets if s["got"] != "not_run"]
    read = [c for c in controls if not c.get("not_run")]
    planted = [
        _one_pair(
            _type_of(s),
            1,
            int(s["got"] in ("fail", "wrongly_passed")),
            int(s["got"] == "wrongly_passed"),
        )
        for s in ran
    ]
    clean = [
        _one_pair(
            _type_of(c),
            c["checklist"]["rows"],
            c["checklist"]["decided"],
            c["checklist"]["fail"],
        )
        for c in read
        if (c.get("checklist") or {}).get("rows")
    ]
    out: dict[str, dict] = {}
    for kind in dict.fromkeys(_type_of(item) for item in [*sheets, *controls]):
        out[kind] = {
            "planted": _add_pairs(planted, kind),
            "clean": _add_pairs(clean, kind),
            "not_run": len(_of_type(sheets, kind))
            - len(_of_type(ran, kind))
            + len(_of_type(controls, kind))
            - len(_of_type(read, kind)),
            "false_new": sum(s.get("false_new") or 0 for s in _of_type(ran, kind)),
            "typed_otherwise": sum(
                1 for item in _of_type([*ran, *read], kind) if _read_otherwise(item)
            ),
        }
    return out


def _pair_cells(slot: dict | None) -> tuple[str, str]:
    """(coverage, risk). Null renders as nothing; nothing decided is not 0 wrong."""
    from app.coverage_pair import NOT_MEASURED

    if slot is None:
        return "", NOT_MEASURED
    risk = slot["risk"]
    said = f"{risk['wrong']} of {risk['decided']}" if risk["decided"] else NOT_MEASURED
    return f"{slot['decided']} of {slot['applicable']}", said


def _type_table(sheets: list[dict], controls: list[dict]) -> list[str]:
    lines = [
        "### Risk and coverage per equipment type (planted sheets)",
        "",
        "Decided: a Fail or a Pass. A Query or no row is not decided, and a Query is often"
        " the answer wanted, so low coverage is not a defect by itself. Risk on a planted"
        " defect: read as a Pass, of those decided. Risk on a clean sheet: a checklist Fail,"
        " of its rows decided. The two sides are never added; library standard rows have no"
        " known answer and are not counted. Invented sheets, one layout per type: a first"
        " number, not a rate.",
        "",
        "| equipment type | planted: coverage | planted: risk | clean checklist: coverage"
        " | clean checklist: risk | not run | new rows on other fields"
        " | typed as something else |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for kind, row in per_type(sheets, controls).items():
        planted, clean = _pair_cells(row["planted"]), _pair_cells(row["clean"])
        lines.append(
            f"| {kind} | {planted[0]} | {planted[1]} | {clean[0]} | {clean[1]}"
            f" | {row['not_run']} | {row['false_new']} | {row['typed_otherwise']} |"
        )
    return lines


def _kind_table(kinds: dict[str, dict]) -> list[str]:
    lines = [
        "| defect kind | planted | caught as Fail | caught as Query | missed | read as a Pass"
        " | not run | as wanted | on the CRS | new rows on other fields |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for kind, k in kinds.items():
        lines.append(
            f"| {kind} | {k['planted']} | {k['fail']} | {k['query']} | {k['missed']}"
            f" | {k['wrongly_passed']} | {k['not_run']} | {k['as_wanted']} | {k['on_crs']}"
            f" | {k['false_new']} |"
        )
    return lines


def render(result: dict) -> str:
    """The table the bench and the script print: counts only."""
    sheets, controls = result["sheets"], result["controls"]
    kinds = per_kind(sheets)
    passed = sum(k["wrongly_passed"] for k in kinds.values())
    planted = sum(k["planted"] for k in kinds.values())
    not_run = sum(k["not_run"] for k in kinds.values())
    lines = [
        "## Planted defects (#1607)",
        "",
        f"reader: {result['reader']}; base: {result['base']}. Invented sheets on a database copy;"
        " a catch is a Fail or Query row on the planted field that the clean sheet does not have.",
        "",
        (
            f"**Planted defects read as a Pass: {passed} of {planted} planted defects"
            + (f"; {not_run} not run, so this count is not a result" if not_run else "")
            + ".**"
            if planted
            else "**Planted defects read as a Pass: not measured (no planted sheet was"
            " selected).**"
        ),
        "",
        *_type_table(sheets, controls),
    ]
    for kind in dict.fromkeys(_type_of(s) for s in sheets):
        lines += [
            "",
            f"### {kind}: per defect kind",
            "",
            *_kind_table(per_kind(_of_type(sheets, kind))),
        ]
    fails = sum(c["fail"] for c in controls)
    queries = sum(c["query"] for c in controls)
    library = sum(c["fail_library"] + c["query_library"] for c in controls)
    silent = sum(1 for c in controls if c.get("not_run"))
    lines += [
        "",
        f"Clean controls, false alarms: {fails} Fail and {queries} Query rows from the checklist"
        f" over {len(controls) - silent} clean sheets; {library} Fail or Query rows from the"
        " library standards, stated apart."
        + (f" {silent} clean sheets did not run." if silent else ""),
    ]
    return "\n".join(lines)


# ------------------------------------------------------------------ the real path


class ClaudeRefused(RuntimeError):
    """The planted-defect run sends nothing to Claude, in any reader mode."""


@contextlib.contextmanager
def no_claude(_reader: str):
    from app import reader_transport

    def refuse(*_a, **_k):
        raise ClaudeRefused("the planted-defect run sends nothing to Claude")

    saved = []
    for name in ("stream", "_gated", "batch_create", "list_models"):
        if hasattr(reader_transport, name):
            saved.append((name, getattr(reader_transport, name)))
            setattr(reader_transport, name, refuse)
    try:
        yield
    finally:
        for name, fn in saved:
            setattr(reader_transport, name, fn)


def echo_reader(printed: list[dict]):
    """A stand-in for the local AI reader: answers what the page prints, with a quote on
    the page, in the shape of whichever reader asked (the form reader's fixed field list,
    or the whole-page reading). Reads the printed rows, knows nothing of the plant."""

    def quote_of(row: dict, page: str) -> str | None:
        words = " ".join(x for x in (row["field"], row["value"], row.get("unit")) if x)
        found = re.search(r"\s+".join(re.escape(w) for w in words.split()), page)
        return found.group(0) if found else None

    def call(prompt: str) -> str:
        found = re.search(r"\nPAGE (\d+):\n", prompt)
        page_no = int(found.group(1)) if found else 0
        page = prompt[found.end() :] if found else ""
        rows = [r for r in printed if r["page"] == page_no and r["value"]]
        quoted = [(r, quote_of(r, page)) for r in rows]
        asked = re.findall(r"^  - (\w+): ", prompt, flags=re.MULTILINE)
        if not asked:
            return json.dumps(
                {
                    "facts": [
                        {
                            "field": r["field"],
                            "value": r["value"],
                            "unit": r.get("unit"),
                            "quote": q,
                            "kind": "offered",
                        }
                        for r, q in quoted
                        if q
                    ]
                }
            )
        by_role = {r["role"]: (r, q) for r, q in quoted if q}
        return json.dumps(
            {
                "fields": [
                    {
                        "field_key": key,
                        "value": by_role[key][0]["value"],
                        "unit": by_role[key][0].get("unit") or "",
                        "quote": by_role[key][1],
                        "status": "found",
                    }
                    if key in by_role
                    else {
                        "field_key": key,
                        "value": "",
                        "unit": "",
                        "quote": "",
                        "status": "not_on_page",
                    }
                    for key in asked
                ]
            }
        )

    call.engine = "fake"
    call.model = "fake"
    return call


def _check_id(source_text: str | None) -> str | None:
    """`Datasheet check PSV-24: words` -> `PSV-24`."""
    head = (source_text or "").split(":", 1)[0]
    return head.rsplit(" ", 1)[-1] if " " in head else None


def _item_roles(rules: dict) -> dict[str, set]:
    """The fields each checklist item and consistency rule reads, from the rule data."""
    out: dict[str, set] = {}
    entries = list(rules.get("consistency") or [])
    for key, checklist in (rules.get("checklists") or {}).items():
        if not key.startswith("_"):
            entries += [
                {**item, **item.get("rule", {})} for item in checklist.get("items", [])
            ]
    for entry in entries:
        out[entry["id"]] = {
            entry[k] for k in ("field", "left", "right") if entry.get(k)
        }
    return out


def _fold(text) -> str:
    return " ".join(str(text or "").lower().split())


def rows_of_run(conn, run_id: str, rules: dict, labels: dict[str, str]) -> list[dict]:
    """The run's findings as `judge` reads them. A row is on a field when its rule reads
    that field, its value is that field, or (checklist calculations) its words name it."""
    from app import datasheet_checks as dc
    from app import presence_check

    items = _item_roles(rules)
    facts = {
        r["id"]: r["field_name"]
        for r in conn.execute(
            "SELECT id, field_name FROM submittal_facts WHERE submittal_document_id ="
            " (SELECT submittal_document_id FROM review_runs WHERE id = ?)",
            (run_id,),
        )
    }
    out = []
    for f in conn.execute(
        "SELECT id, origin, compliance_status, requirement_id, requirement_source_text,"
        " contractor_section, fact_id, equipment_tag, finding, ai_rationale"
        " FROM review_findings WHERE review_run_id = ?",
        (run_id,),
    ):
        checklist = f["origin"] == dc.ORIGIN
        check = _check_id(f["requirement_source_text"]) if checklist else None
        roles = set(items.get(check, ()))
        for text in (f["contractor_section"], facts.get(f["fact_id"])):
            role = dc.role_of(text, rules) if text else None
            if role:
                roles.add(role)
        if checklist:
            words = _fold(f"{f['finding']} {f['ai_rationale']}")
            roles |= {r for r, label in labels.items() if _fold(label) in words}
        out.append(
            {
                "id": f["id"],
                "key": (
                    f["origin"],
                    check or f["requirement_id"] or f["requirement_source_text"],
                    f["equipment_tag"],
                ),
                # #1638, switch on: "is stated" read no value, so it is no Pass on the field
                "status": (
                    STATED
                    if presence_check.is_stated_only(dict(f))
                    else f["compliance_status"]
                ),
                "roles": roles,
                "tier": "checklist" if checklist else "library",
            }
        )
    return out


def _control_counts(sheet: str, rows: list[dict]) -> dict:
    def count(tier, wanted):
        return sum(1 for r in rows if r["tier"] == tier and r["status"] in wanted)

    return {
        "sheet": sheet,
        "fail": count("checklist", (FAIL,)),
        "query": count("checklist", QUERY),
        "fail_library": count("library", (FAIL,)),
        "query_library": count("library", QUERY),
    }


def _review(pdf: Path) -> tuple[str | None, str | None]:
    """One sheet through upload, the role hooks and the review job. (run id, why not)."""
    from app import classification, db, review_jobs
    from tools import datasheet_offline

    read = datasheet_offline._ingest(pdf, run_ocr=False)
    doc = read["document_id"]
    if read["status"] != datasheet_offline.READ or doc is None:
        return None, f"not read: {read['status']}"
    conn = db.connect()
    with (
        conn
    ):  # the keyword index and embedding are left out: neither feeds a review of facts
        conn.execute("UPDATE documents SET status = 'ready' WHERE id = ?", (doc,))
    classification.set_role(
        doc, "CONTRACTOR_SUBMITTAL"
    )  # runs the READY hooks: type, facts
    ids = frozenset(r["id"] for r in conn.execute("SELECT id FROM documents"))
    run_id, job_id = review_jobs.enqueue(
        doc, allowed_document_ids=ids, requested_by=None
    )
    # Claimed by id, never `claim_next`: a copy can hold queued jobs of other documents.
    with conn:
        conn.execute(
            "UPDATE jobs SET state = 'running', claimed_by = 'planted',"
            " claimed_at = updated_at WHERE id = ?",
            (job_id,),
        )
        conn.execute(
            "UPDATE review_runs SET status = 'running' WHERE id = ?", (run_id,)
        )
    state = review_jobs.run(job_id, "planted")
    return (run_id, None) if state == "done" else (run_id, f"review {state}")


@contextlib.contextmanager
def _reader_mode(reader: str, printed: list[dict], refused: list[int]):
    """The AI reader setting and what may answer it, for one sheet."""
    from app import datasheet_ai
    from app.config import settings
    from tools import crs_bench

    saved = settings.datasheet_ai_reader
    try:
        if reader == "local-model":
            yield  # the configured engine, whatever `.env` says: only when released
            return
        settings.datasheet_ai_reader = "ollama" if reader == "fake" else "off"
        override = (
            datasheet_ai.using_model_call(echo_reader(printed))
            if reader == "fake"
            else contextlib.nullcontext()
        )
        with crs_bench._models_refused(refused, (settings.ai_task_model,)), override:
            yield
    finally:
        settings.datasheet_ai_reader = saved


@contextlib.contextmanager
def _settings_for_copy(root: Path):
    """Every path a review writes goes under the copy's folder; sign-in off so the
    review's scope is the copy's documents. The paths go in the environment too: a
    spawned worker builds its own settings from it and must never reach the project's
    data folder."""
    from app import access
    from app.config import settings

    names = ("upload_dir", "auth_mode", "review_audit_dir", "claude_spend_log")
    saved = {n: getattr(settings, n) for n in names}
    settings.upload_dir = root / "uploads"
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    settings.auth_mode = access.AUTH_DISABLED
    settings.review_audit_dir = str(root / "audit")
    settings.claude_spend_log = root / "spend.jsonl"
    env = {
        "DATA_DIR": str(settings.data_dir),
        "DB_PATH": str(settings.db_path),
        "UPLOAD_DIR": str(settings.upload_dir),
    }
    saved_env = {name: os.environ.get(name) for name in env}
    os.environ.update(env)
    try:
        yield
    finally:
        for name, value in saved.items():
            setattr(settings, name, value)
        for name, value in saved_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _crs_finding_ids(run_id: str) -> set[str]:
    from app import access, main

    scope = access.unrestricted_scope()
    try:
        rows, *_ = main._crs_content(run_id, scope)
    except Exception:  # noqa: BLE001 - shown as not on the CRS, never as on it
        return set()
    ids: set[str] = set()
    for row in rows:
        if row.get("finding_id"):
            ids.add(row["finding_id"])
        ids.update(row.get("finding_ids") or [])
    return ids


def score(
    db_path: Path, bases: list[dict], *, reader: str, work: Path | None = None, log=None
) -> dict:
    """Plant, review on a throw-away copy of `db_path`, judge. `db_path` is not written;
    the copy lives in `work` (default: beside `db_path`) and is deleted at the end."""
    from app import coverage_pair, datasheet_ai, db, live_guard
    from app import datasheet_checks as dc
    from tools import crs_bench

    if reader not in READERS:
        raise ValueError(f"unknown reader {reader!r}; one of {', '.join(READERS)}")
    db_path = Path(db_path).resolve()
    if live_guard.is_live_shaped(db_path):
        raise PermissionError("the planted-defect run never opens the live database")
    work = Path(work) if work else db_path.parent
    work.mkdir(parents=True, exist_ok=True)
    rules = dc.load_rules()
    sheets, controls, ai_facts, refused = [], [], 0, [0]
    with (
        tempfile.TemporaryDirectory(prefix="planted-", dir=work) as folder,
        crs_bench._on_copy(db_path, under=work),
        _settings_for_copy(Path(folder)),
        no_claude(reader),
    ):
        for base in bases:
            out = Path(folder) / base["name"]
            manifest = write_set(base, out)
            labels = {r["role"]: r["field"] for r in _rows(base)}
            clean: list[dict] = []
            baseline_missing = True
            for entry in manifest["sheets"]:
                answer = json.loads((out / entry["answer"]).read_text(encoding="utf-8"))
                with _reader_mode(reader, answer["printed"], refused):
                    run_id, why = _review(out / entry["sheet"])
                conn = db.connect()
                rows = (
                    rows_of_run(conn, run_id, rules, labels)
                    if run_id and not why
                    else []
                )
                if log:
                    log(
                        f"{entry['sheet']}: {len(rows)} rows{f' ({why})' if why else ''}"
                    )
                # case=None: the one definition, without looking for a truth case
                pair = (
                    coverage_pair.for_run(conn, run_id, case=None)
                    if run_id and not why
                    else None
                )
                typed = {
                    "equipment_type": base["equipment_type"],
                    "typed_as": (pair or {}).get("equipment_type"),
                }
                if answer.get("control"):
                    if entry is manifest["sheets"][0]:
                        clean, baseline_missing = rows, bool(why)
                    controls.append(
                        {
                            **_control_counts(entry["sheet"], rows),
                            **typed,
                            **({"checklist": pair["checklist"]} if pair else {}),
                            **({"not_run": why} if why else {}),
                        }
                    )
                    continue
                if not why and baseline_missing:
                    why = "the clean control did not run: nothing to judge against"
                verdict = (
                    {
                        "got": "not_run",
                        "as_wanted": False,
                        "false_new": 0,
                        "also_passed": 0,
                        "caught_ids": [],
                        "why": why,
                    }
                    if why
                    else judge(answer, rows, clean)
                )
                on_crs = (
                    bool(set(verdict["caught_ids"]) & _crs_finding_ids(run_id))
                    if run_id
                    else False
                )
                caught = verdict.pop("caught_ids")
                sheets.append(
                    {
                        "sheet": entry["sheet"],
                        **typed,
                        "defect": answer["defect"],
                        "fields": answer["fields"],
                        "wanted": answer["wanted"],
                        **verdict,
                        "on_crs": on_crs,
                        "rows_on_field": len(caught),
                    }
                )
            ai_facts += (
                db.connect()
                .execute(
                    "SELECT COUNT(*) FROM submittal_facts"
                    " WHERE (extraction_method = ? OR confidence = ?)"
                    " AND submittal_document_id IN (SELECT id FROM documents WHERE filename LIKE ?)",
                    (
                        datasheet_ai.EXTRACTION_METHOD,
                        datasheet_ai.AGREED_CONFIDENCE,
                        f"{base['name']}-%",
                    ),
                )
                .fetchone()[0]
            )
    return {
        "reader": reader,
        "base": ", ".join(b["name"] for b in bases),
        "sheets": sheets,
        "controls": controls,
        "ai_facts": ai_facts,
        "model_calls_refused": refused[0],
    }


def all_bases() -> list[dict]:
    return [load_base(p) for p in sorted(BASES.glob("*.json"))]


def bench_section(db_path: Path) -> str:
    """The bench's section (switch on): the rule readers, no model, on its own copy."""
    return render(score(db_path, all_bases(), reader="rules"))
