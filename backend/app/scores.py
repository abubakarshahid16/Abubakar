"""Scores that know which scale they are on.

FOUR defects in this project have been the same error: a value from one scale
used against another.

  1. rerank_max_tokens = 256 against a chunk ceiling of 480, so the
     cross-encoder rated passages it had only half read.
  2. MIN_RERANK_SCORE = -3.0 as a fixed cut on a scale that moves by 16 points
     with nothing but the wording of the question.
  3. The second-passage gap, an absolute bar that admitted a pair scoring
     -1.19/-1.50 on the real corpus and rejected the same correct pair scoring
     -2.04/-5.78 on a smaller one.
  4. The heading-authority boost: IDENTIFIER_BOOST * top_rrf * 2 = 0.0313,
     computed on the RRF scale (~0.03) and added to the rerank scale (~+-10).
     It fired on every query and could never change an outcome. A rule that
     runs and cannot affect the result is a sibling of a check that cannot
     fail - it is counted as protection and provides none.

Fixing the fourth does not prevent a fifth, so the scales are separated here.
An RRF score and a rerank score are different quantities in different units;
adding them is as wrong as adding metres to seconds, and it now raises instead
of quietly producing a number.

NOT EVERY SCORE IN THE CODEBASE IS WRAPPED YET. These types are used at the
site the fourth defect lived and for every new relative computation. Wrapping
the whole pipeline would be a large rewrite of working retrieval code; the
value here is that the next person reaching for a cross-scale arithmetic has
to write it deliberately.
"""

from __future__ import annotations

from typing import ClassVar


class ScaleMismatch(TypeError):
    """Raised when two different score scales are combined."""


class Score:
    """A number that carries its scale.

    Arithmetic is permitted only between the same scale, and only where it
    means something: two scores of one scale may be subtracted to give a
    DIFFERENCE on that scale, and a score may be compared with another of its
    own scale. Multiplying two scores, or adding across scales, raises.
    """

    scale: ClassVar[str] = "abstract"
    __slots__ = ("value",)

    def __init__(self, value: float) -> None:
        self.value = float(value)

    # ---------------------------------------------------------------- guards

    def _same(self, other: object) -> Score:
        if not isinstance(other, Score):
            raise ScaleMismatch(
                f"cannot combine a {self.scale} score with {type(other).__name__}; "
                f"wrap it in the matching type first"
            )
        if other.scale != self.scale:
            raise ScaleMismatch(
                f"cannot combine a {self.scale} score with a {other.scale} score. "
                f"These are different units. This is the error that made the "
                f"heading-authority boost 0.0313 on a scale spanning about 20 "
                f"points, where it could never change an outcome."
            )
        return other

    # ------------------------------------------------------------ arithmetic

    def __add__(self, other: object) -> Score:
        return type(self)(self.value + self._same(other).value)

    def __sub__(self, other: object) -> Score:
        return type(self)(self.value - self._same(other).value)

    def __lt__(self, other: object) -> bool:
        return self.value < self._same(other).value

    def __le__(self, other: object) -> bool:
        return self.value <= self._same(other).value

    def __gt__(self, other: object) -> bool:
        return self.value > self._same(other).value

    def __ge__(self, other: object) -> bool:
        return self.value >= self._same(other).value

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Score) and other.scale == self.scale:
            return self.value == other.value
        return NotImplemented

    def __hash__(self) -> int:
        return hash((self.scale, self.value))

    def __mul__(self, other: object) -> Score:
        # Scaling by a dimensionless number is fine; multiplying two scores is
        # not - that is what produced IDENTIFIER_BOOST * top_rrf.
        if isinstance(other, Score):
            raise ScaleMismatch(
                f"cannot multiply a {self.scale} score by a {other.scale} score - "
                f"the result has no scale. IDENTIFIER_BOOST * top_rrf did exactly "
                f"this and produced a value 300 times too small to matter."
            )
        if isinstance(other, (int, float)):
            return type(self)(self.value * float(other))
        return NotImplemented

    __rmul__ = __mul__

    def __float__(self) -> float:
        return self.value

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.value:.4f})"


class RrfScore(Score):
    """Reciprocal rank fusion. Small positive values, roughly 0.01 to 0.05."""

    scale = "rrf"


class RerankScore(Score):
    """Cross-encoder output. Roughly -11 to +10 on this corpus, and the range
    MOVES with the wording of the question - measured at 16 points of swing
    for one passage across two phrasings of one fact."""

    scale = "rerank"


class RelativeScore(Score):
    """Dimensionless, derived from a candidate set: how far apart two members
    of that set are, expressed against the spread of that same set.

    This is the scale a threshold may safely live on, because it is defined by
    the query's own candidates rather than by a corpus we happened to tune on.
    """

    scale = "relative"


def spread(values: list[float]) -> float:
    """The usable range of a candidate set: top minus median.

    Median rather than minimum, because the bottom of a rerank field is a long
    flat tail of unrelated passages and its position says nothing about how
    decisive the winner is. Measured over 35 queries with known ground truth,
    this "lift" is 3.26 to 17.02 where the answer is present and 1.02 to 4.58
    where it is not - overlapping, which is why it cannot be a gate, but a
    sound denominator for judging whether two candidates are distinguishable.
    """
    if not values:
        return 0.0
    ordered = sorted(values, reverse=True)
    mid = ordered[len(ordered) // 2]
    return max(ordered[0] - mid, 1e-9)


def separation(top: float, other: float, field: list[float]) -> RelativeScore:
    """How far `other` sits below `top`, as a fraction of the field's spread.

    0.0 means indistinguishable; 1.0 means a whole field-spread apart. This is
    the only scale on which a constant is defensible, because it is normalised
    per query.
    """
    return RelativeScore((top - other) / spread(field))
