"""Build `backend/app/reference/english_words.txt.gz` - the vocabulary
`market_phrase` vouches for ordinary words with.

Source: SCOWL's en_US Hunspell dictionary (`en_US.dic` + `en_US.aff`, as
shipped by Debian/Ubuntu `hunspell-en-us`), expanded through its own affix
rules. Kept: words that are LOWER CASE in the dictionary (so proper nouns -
people, places, companies - are never vouched for), letters only, three or
more letters. The licence notice travels beside the output
(`english_words.LICENSE`), as SCOWL's permission requires.

Run once, offline, on any machine that has the two files:

    python scripts/build_english_words.py /usr/share/hunspell/en_US

The output is committed; nothing reads the Hunspell files at run time.
"""
from __future__ import annotations

import gzip
import re
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "backend" / "app" / "reference" / "english_words.txt.gz"
_WORD = re.compile(r"^[a-z]{3,}$")


def _affixes(aff: Path) -> dict[str, tuple[str, bool, list[tuple[str, str, re.Pattern]]]]:
    rules: dict = {}
    for line in aff.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[0] in ("PFX", "SFX"):
            kind, flag = parts[0], parts[1]
            if flag not in rules:
                rules[flag] = (kind, parts[2] == "Y", [])
                continue
            strip, add = parts[2], parts[3].split("/")[0]
            cond = parts[4] if len(parts) > 4 else "."
            strip = "" if strip == "0" else strip
            add = "" if add == "0" else add
            pattern = re.compile(("^" + cond) if kind == "PFX" else (cond + "$"))
            rules[flag][2].append((strip, add, pattern))
    return rules


def _apply(word: str, kind: str, entries) -> list[str]:
    out = []
    for strip, add, pattern in entries:
        if not pattern.search(word):
            continue
        if kind == "SFX":
            if strip and not word.endswith(strip):
                continue
            out.append((word[:-len(strip)] if strip else word) + add)
        else:
            if strip and not word.startswith(strip):
                continue
            out.append(add + (word[len(strip):] if strip else word))
    return out


def build(base: str) -> set[str]:
    rules = _affixes(Path(base + ".aff"))
    words: set[str] = set()
    lines = Path(base + ".dic").read_text(encoding="utf-8").splitlines()[1:]
    for line in lines:
        stem, _, flags = line.strip().partition("/")
        if not stem or stem != stem.lower():
            continue          # a proper noun or an acronym: never vouched for
        forms = {stem}
        prefixed = []
        for flag in flags:
            rule = rules.get(flag)
            if rule and rule[0] == "PFX":
                prefixed.append((rule, _apply(stem, "PFX", rule[2])))
                forms.update(prefixed[-1][1])
        for flag in flags:
            rule = rules.get(flag)
            if rule and rule[0] == "SFX":
                forms.update(_apply(stem, "SFX", rule[2]))
                if rule[1]:     # cross product with the prefixes
                    for prule, pforms in prefixed:
                        if prule[1]:
                            for pf in pforms:
                                forms.update(_apply(pf, "SFX", rule[2]))
        words.update(w for w in forms if _WORD.match(w))
    return words


def main(argv: list[str]) -> int:
    base = argv[1] if len(argv) > 1 else "/usr/share/hunspell/en_US"
    words = build(base)
    OUT.write_bytes(gzip.compress("\n".join(sorted(words)).encode("ascii") + b"\n", mtime=0))
    print(f"{len(words)} words -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
