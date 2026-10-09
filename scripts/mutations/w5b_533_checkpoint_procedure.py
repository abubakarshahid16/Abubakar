"""#533: the checkpoint reviews one invented procedure. Ids M5901-M5907."""
from __future__ import annotations

from ._base import REPO, Mutation

_T = "tests/test_w5b_533_checkpoint_procedure.py"
_S = REPO / "scripts" / "checkpoint_procedure.py"
_K = REPO / "eval" / "checkpoint" / "procedure.json"
_TAG = ("w5b", "checkpoint")


def _m(i, desc, path, anchor, repl, kw=None):
    return Mutation(id=f"M{i}", phase=i, description=desc, path=path, anchor=anchor,
                    replacement=repl, target=_T, keyword=kw, tags=_TAG)


MUTATIONS: tuple[Mutation, ...] = (
    _m(5901, "the planted gap is dropped from the answer key", _K,
       '"H06": "present", "H07": "missing", ', '"H06": "present", ', "records_every_element"),
    _m(5902, "an element the review did not report counts as a pass", _S,
       '"pass": read and state is not None and state == want})', '"pass": read and state in (None, want)})',
       "did_not_report"),
    _m(5903, "a document not read in full still passes", _S,
       '"pass": read and state is not None and state == want})', '"pass": state is not None and state == want})',
       "not_read_in_full"),
    _m(5904, "an unread run is called fail or pass, not incomplete", _S,
       '            "status": ("incomplete" if not read else "pass" if passed == len(rows) else "fail"),',
       '            "status": ("pass" if passed == len(rows) else "fail"),', "not_read_in_full"),
    _m(5905, "a missing key is not a named error", _S,
       "    except FileNotFoundError as exc:\n        raise CheckpointError(f\"{Path(path).name}: the checkpoint answer key is missing\") from exc\n",
       "    except FileNotFoundError:\n        key = {}\n", "missing_key"),
    _m(5906, "the document is never marked read, so nothing is checked", _S,
       "        conn.execute(\"UPDATE documents SET status = 'ready' WHERE id = ? AND status = 'indexing_keyword'\",",
       "        conn.execute(\"UPDATE documents SET status = status WHERE id = ? AND ? = 'x'\",",
       "records_every_element or exits_zero"),
    _m(5907, "the boundary does not say the sample is invented", _S,
       "\"keyword index only (no embeddings); invented sample, not the client's documents\")",
       "\"keyword index only (no embeddings)\")", "records_every_element"),
)
