"""PR #1086 (order 79c, review path): comparison's exact catches and its
fallback log lines. backend/tests/test_79c_review_excepts_log.py must notice."""
from __future__ import annotations

from ._base import APP, Mutation

_C = APP / "comparison.py"
_T = "tests/test_79c_review_excepts_log.py"
_TAG = ("pr1086", "comparison")


def _m(n, desc, anchor, repl, kw):
    return Mutation(id=f"M1086-{n:02d}", phase=1086, description=desc, path=_C,
                    anchor=anchor, replacement=repl, target=_T, keyword=kw, tags=_TAG)


MUTATIONS: tuple[Mutation, ...] = (
    _m(1, "a malformed model choice is no longer caught",
       "    except ValueError:  # not JSON, or not this shape",
       "    except KeyError:  # not JSON, or not this shape", "malformed_model_choice"),
    _m(2, "any database error reads as 'no rejections' again",
       "    except sqlite3.OperationalError as exc:  # a database without the table yet\n",
       "    except Exception as exc:  # noqa: BLE001\n", "unexpected_database_error"),
    _m(3, "a missing rejections table is swallowed without a log line",
       '        return errors.fell_back("comparison: pair rejections could not be read; none are applied", exc, set())\n',
       "        return set()\n", "rejections_table"),
    _m(4, "a missing tag column is swallowed without a log line",
       '        return errors.fell_back("comparison: equipment tags could not be counted; not tag-scoped", exc, False)\n',
       "        return False\n", "rejections_table"),
    _m(5, "a failed local pair-choice call is swallowed without a log line",
       '        return errors.fell_back("comparison: the local pair-choice call failed; the pair stays unchosen", exc, (None, MODEL_UNAVAILABLE))\n',
       "        return None, MODEL_UNAVAILABLE\n", "local_pair_choice"),
)
