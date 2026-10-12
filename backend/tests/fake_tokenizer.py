"""A word-level stand-in for the e5-small tokenizer, used ONLY when the real
one is not staged (a sandbox without model weights). Token counts are word
counts, which is enough for tests about structure; the real tokenizer is used
whenever it exists."""
from __future__ import annotations

from app import chunker


class _Encoding:
    def __init__(self, ids: list[int]) -> None:
        self.ids = ids


class FakeTokenizer:
    def __init__(self) -> None:
        self._words: list[str] = []
        self._index: dict[str, int] = {}

    def encode(self, text: str, add_special_tokens: bool = False) -> _Encoding:
        ids = []
        for word in text.split():
            if word not in self._index:
                self._index[word] = len(self._words)
                self._words.append(word)
            ids.append(self._index[word])
        return _Encoding(ids)

    def decode(self, ids: list[int]) -> str:
        return " ".join(self._words[i] for i in ids)


def install_if_missing(monkeypatch) -> bool:
    """Patch the chunker's tokenizer when the real one cannot load. True when
    the stand-in is in use."""
    try:
        chunker.get_tokenizer()
        return False
    except Exception:  # noqa: BLE001 - missing or unreadable weights: any failure means "not usable"
        fake = FakeTokenizer()
        monkeypatch.setattr(chunker, "get_tokenizer", lambda: fake)
        return True
