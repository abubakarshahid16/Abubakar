"""Mutations of `backend/app/keyword.py`."""

from __future__ import annotations

from ._base import APP, Mutation

#: The keyword-tokenizer tests (M1200-M1216).
T = "tests/test_keyword_tokenizer.py"


MUTATIONS: tuple[Mutation, ...] = (
    # ---- from B14_GLOSSARY_PHRASE -----------------------------------------
    #: B14: the glossary-phrase pass had no test that could fail - the existing one
    #: passed with the pass deleted, because two chunks can crowd nothing out.
    Mutation(
        id="M305", phase=32,
        description="delete the exact-phrase pass, so a glossary definition is "
                    "crowded out of the candidate list by scattered-word matches",
        path=APP / "keyword.py",
        anchor="    phrase = build_phrase_query(question)",
        replacement='    phrase = ""',
        target="tests/test_keyword.py",
        keyword="survives_a_crowd",
    ),
    # ---- from B12_SCOPED_CORRECTIONS --------------------------------------
    #: B12: a spelling correction named a word found only in a document the caller
    #: may not read, because fts5vocab is one term list for the whole index.
    Mutation(
        id="M306", phase=33,
        description="offer the closest corpus-wide word without checking the "
                    "caller's scope - the presence oracle B12 closed",
        path=APP / "keyword.py",
        anchor="        if term_occurrences(\n"
               "            candidate, document_id, allowed_document_ids=allowed_document_ids\n"
               "        ) > 0:",
        replacement="        if True:",
        target="tests/test_keyword.py",
        keyword="unreadable_document or closer_word",
        tags=("permission", "critical"),
    ),
    Mutation(
        id="M307", phase=33,
        description="scope REFUSES instead of filtering: an out-of-scope best "
                    "match hides the in-scope word the caller may be offered",
        path=APP / "keyword.py",
        anchor="        ) > 0:\n            return candidate\n    return None",
        replacement="        ) > 0:\n            return candidate\n        break\n    return None",
        target="tests/test_keyword.py",
        keyword="closer_word",
        tags=("permission",),
    ),

    # ---- from KEYWORD_TOKENIZER (audit R1/R2/R3/R4/R7, F3; 2026-09-27) ----
    #: The FTS tokenizer glued sentence-final punctuation onto tokens, so a
    #: standard that ends a sentence was reported absent from the corpus.
    Mutation(
        id="M1200", phase=97,
        description="index the RAW chunk text again, so 'NACE MR0175.' is "
                    "stored as mr0175. and the gate calls MR0175 absent",
        path=APP / "keyword.py",
        anchor='    body = strip_edge_punctuation(text or "")',
        replacement='    body = text or ""',
        target=T,
        keyword="sentence_final or refusal_path or keeps_identifiers_intact "
                "or older_code or startup",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M1201", phase=97,
        description="stop normalising query phrases, so 'system no. 1' asks "
                    "for the token no. the index no longer holds",
        path=APP / "keyword.py",
        anchor="    token = \" \".join(strip_edge_punctuation(token).split())\n",
        replacement="",
        target=T,
        keyword="builder_quotes",
    ),
    Mutation(
        id="M1202", phase=97,
        description="stop stripping the question's own edge punctuation, so "
                    "'pump.' is not a word and is never folded",
        path=APP / "keyword.py",
        anchor="    return \" \".join(strip_edge_punctuation(cleaned).split())",
        replacement="    return \" \".join(cleaned.split())",
        target=T,
        keyword="singular_and_plural",
    ),
    Mutation(
        id="M1203", phase=97,
        description="truncate a designator's number again: 'clause 5.3.2' "
                    "becomes the required phrase 'clause 5'",
        path=APP / "keyword.py",
        anchor='    r"(\\d+(?:\\.\\d+)*[A-Za-z]?)\\b",',
        replacement='    r"(\\d+[A-Za-z]?)\\b",',
        target=T,
        keyword="whole_dotted_number or clause_question or table_designator",
    ),
    Mutation(
        id="M1204", phase=97,
        description="require the phrase 'clause 5.3.2' instead of accepting "
                    "the number where the heading prints it",
        path=APP / "keyword.py",
        anchor="                    spelled.append(_escape(number))",
        replacement="                    pass",
        target=T,
        keyword="clause_question",
    ),
    Mutation(
        id="M1205", phase=97,
        description="require a bare 'section 4' phrase instead of preferring "
                    "it, emptying the keyword side",
        path=APP / "keyword.py",
        anchor="                    optional.extend(spelled)\n"
               "                    continue",
        replacement="                    pass",
        target=T,
        keyword="bare_section_number",
    ),
    Mutation(
        id="M1206", phase=97,
        description="ask for an identifier only as typed, so API 610 misses "
                    "API-610 and API610",
        path=APP / "keyword.py",
        anchor="    forms = [_escape(f) for f in identifier_forms(identifier)]",
        replacement="    forms = [_escape(identifier)]",
        target=T,
        keyword="identifier_spellings",
    ),
    Mutation(
        id="M1207", phase=97,
        description="drop the joined identifier alias from the index, so a "
                    "mixed-separator code (SAES H-101V) is unfindable",
        path=APP / "keyword.py",
        anchor="        if joined != m.group(0).lower():\n"
               "            aliases.append(joined)",
        replacement="        pass",
        target=T,
        keyword="mixed_separator",
    ),
    Mutation(
        id="M1208", phase=97,
        description="no singular/plural folding: 'pump' misses 'pumps'",
        path=APP / "keyword.py",
        anchor="    lower = word.lower()\n    if lower.endswith((\"ed\", \"ing\")):",
        replacement="    return [word]\n    lower = word.lower()\n"
                    "    if lower.endswith((\"ed\", \"ing\")):",
        target=T,
        keyword="singular_and_plural or never_folded",
    ),
    Mutation(
        id="M1209", phase=97,
        description="fold acronyms too, inventing ASMEs / NDFTs",
        path=APP / "keyword.py",
        anchor="    if (len(word) < 4 or not word.isalpha() or word.isupper()\n",
        replacement="    if (len(word) < 4 or not word.isalpha()\n",
        target=T,
        keyword="never_folded",
    ),
    Mutation(
        id="M1210", phase=97,
        description="drop the comma-free alias of 3,300 from the index",
        path=APP / "keyword.py",
        anchor='        aliases.append(m.group(0).replace(",", ""))',
        replacement="        pass",
        target=T,
        keyword="thousands",
    ),
    Mutation(
        id="M1211", phase=97,
        description="stop asking for the comma-free spelling of '3,300'",
        path=APP / "keyword.py",
        anchor='            elif _THOUSANDS.fullmatch(w.split(".")[0]):',
        replacement="            elif False:",
        target=T,
        keyword="thousands",
    ),
    Mutation(
        id="M1212", phase=97,
        description="strip the thousands comma from the question, splitting "
                    "3,300 into 3 and 300",
        path=APP / "keyword.py",
        anchor='        return ","\n    return " "',
        replacement='        return " "\n    return " "',
        target=T,
        keyword="thousands",
    ),
    Mutation(
        id="M1213", phase=97,
        description="drop the split halves of hyphenated compounds, so "
                    "'steel' misses 'carbon-steel'",
        path=APP / "keyword.py",
        anchor='        aliases.append(" ".join(re.split(r"[-/]", m.group(0))))',
        replacement="        pass",
        target=T,
        keyword="hyphenated_compound",
    ),
    Mutation(
        id="M1214", phase=97,
        description="never rebuild an index written by older code: every "
                    "existing database keeps its glued full stops",
        path=APP / "keyword.py",
        anchor="    if before == INDEX_VERSION:",
        replacement="    if True:",
        target=T,
        keyword="older_code or startup",
        tags=("honesty",),
    ),
    Mutation(
        id="M1216", phase=97,
        description="count term presence with the bare phrase again, so the "
                    "gate calls API 610 / Valves absent where search finds them",
        path=APP / "keyword.py",
        anchor="    params: list[object] = [term_expression(term)]",
        replacement="    params: list[object] = [_escape(term)]",
        target=T,
        keyword="identifier_spellings or singular_and_plural",
        tags=("honesty",),
    ),
)
