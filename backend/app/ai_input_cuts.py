"""What the AI engineering check was NOT shown (#633 item 3).

The check cuts every page to a fixed number of characters (the local model: `LOCAL_PAGE_CHARS`,
the cloud model: `MAX_PAGE_CHARS`) and the cloud prompt as a whole to `MAX_PROMPT_CHARS`. The
run used to say it was "complete" whatever was cut, so a sheet the model saw only the start of
read as a sheet it had checked. This counts what was left out (page numbers and character counts
only, never text) so the run can say so. Pure functions.
"""

from __future__ import annotations


def report(
    pages: dict[int, str],
    page_chars: int,
    *,
    shown: list[int] | None = None,
    prompt_chars: int | None = None,
    prompt_length: int | None = None,
) -> dict | None:
    """{page_chars, pages_cut, pages_shown, characters_not_shown, prompt_chars_not_shown} for the
    pages the model was shown (`shown`, default all with text), or None when nothing was cut.

    `characters_not_shown` is what the per-page cut dropped; `prompt_chars_not_shown` is what the
    whole-prompt cut dropped (`prompt_length` over `prompt_chars`), 0 when there is no such cut."""
    wanted = [p for p, text in pages.items() if (text or "").strip()]
    seen = wanted if shown is None else [p for p in wanted if p in set(shown)]
    cut = [p for p in seen if len(pages[p]) > page_chars]
    over = max(0, (prompt_length or 0) - prompt_chars) if prompt_chars else 0
    if not cut and not over:
        return None
    return {
        "page_chars": page_chars,
        "pages_cut": sorted(cut),
        "page_lengths": {str(p): len(pages[p]) for p in sorted(cut)},
        "pages_shown": len(seen),
        "characters_not_shown": sum(len(pages[p]) - page_chars for p in cut),
        "prompt_chars_not_shown": over,
    }


def sentence(cut: dict | None) -> str:
    """The plain-words line for the run, or "" when nothing was cut."""
    if not cut:
        return ""
    parts = []
    if cut["pages_cut"]:
        parts.append(
            f"{len(cut['pages_cut'])} of {cut['pages_shown']} page(s) it was shown were longer than "
            f"{cut['page_chars']:,} characters and were cut ({cut['characters_not_shown']:,} "
            "characters not shown)"
        )
    if cut["prompt_chars_not_shown"]:
        parts.append(
            f"the whole prompt was cut ({cut['prompt_chars_not_shown']:,} characters not shown)"
        )
    return (
        " Input cut: "
        + "; ".join(parts)
        + ". What was cut was not checked by the model."
    )


def of_run(
    local_pages: dict | None, pages: dict[int, str], prompt_of_all
) -> dict | None:
    """What the lane that ran cut. The local model is asked page by page (`LOCAL_PAGE_CHARS`,
    only the pages it was asked); the cloud model gets the whole sheet in one prompt
    (`MAX_PAGE_CHARS` per page, `MAX_PROMPT_CHARS` overall); `prompt_of_all()` is that prompt
    before the overall cut."""
    from . import ai_engineering_check as aic  # late: it imports this module

    if local_pages is not None:
        asked = local_pages["done"] + local_pages["timed_out"] + local_pages["failed"]
        return report(pages, aic.LOCAL_PAGE_CHARS, shown=asked)
    return report(
        pages,
        aic.MAX_PAGE_CHARS,
        prompt_chars=aic.MAX_PROMPT_CHARS,
        prompt_length=len(prompt_of_all()),
    )


def settle(
    cut: dict | None, local_pages: dict | None, complete: bool, reason: str | None
):
    """(complete, reason) after the cut. The cloud model was given the whole sheet in one prompt: a
    prompt cut dropped whole pages off its end, so the sheet is not "complete". A page cut short on
    its own does not make the whole review incomplete (the planner's call, 19:26): it is named per
    page in the review notes (`page_lines`). The local lane keeps its own completeness (it is asked
    about blank fields page by page, and says so in its scope); its cut is recorded."""
    if cut and cut.get("prompt_chars_not_shown") and local_pages is None:
        return False, reason or "part of the sheet was cut before the model saw it"
    return complete, reason


def page_lines(cut: dict | None) -> list[str]:
    """One plain line per page the per-page cut shortened, for the internal review notes."""
    if not cut:
        return []
    return [
        f"Page {page}: the AI check read the first {cut['page_chars']:,} of {length:,} characters; "
        "the rest of the page was not read by the model."
        for page, length in sorted(
            (cut.get("page_lengths") or {}).items(), key=lambda kv: int(kv[0])
        )
    ]
