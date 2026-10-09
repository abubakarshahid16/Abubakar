"""#528: the datasheet review playbook is a data file. Ids M5801-M5808."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_w5b_528_datasheet_playbook.py"
_P = APP / "datasheet_playbook.py"
_D = APP / "reference" / "datasheet_playbook.json"
_TAG = ("w5b", "playbook")


def _m(i, desc, path, anchor, repl, kw=None):
    return Mutation(id=f"M{i}", phase=i, description=desc, path=path, anchor=anchor,
                    replacement=repl, target=_T, keyword=kw, tags=_TAG)


MUTATIONS: tuple[Mutation, ...] = (
    _m(5801, "the data file drifts from the code it replaced (a derivation input dropped)", _D,
       '"mop", "maximum operating pressure", ', '"maximum operating pressure", ', "equals_the_code"),
    _m(5802, "the data file drifts (a flange class dropped)", _D,
       '"flange_classes": [150, 300, 400, 600, 900, 1500, 2500]', '"flange_classes": [150, 300, 400, 600, 900, 1500]',
       "equals_the_code or every_class"),
    _m(5803, "the class patterns stay literal, so a class added to the data is not read in text",
       APP / "field_links.py", '_CLASS_ALT = "|".join(str(c) for c in _CLASSES)',
       '_CLASS_ALT = "150|300|400|600|900|1500|2500"', "edit_to_the_file"),
    _m(5804, "the derivation rules stay a code copy", APP / "rule_eval.py",
       'KNOWN_RULES = datasheet_playbook.PLAYBOOK["derivation_rules"]',
       'KNOWN_RULES = tuple(dict(r) for r in datasheet_playbook.load()["derivation_rules"])',
       "read_the_data_file or edit_to_the_file"),
    _m(5805, "a missing file reads as an empty playbook", _P,
       "    except FileNotFoundError as exc:\n        raise DatasheetPlaybookError(f\"{target.name}: the datasheet playbook file is missing\") from exc\n",
       "    except FileNotFoundError:\n        data = {}\n",
       "missing_file"),
    _m(5806, "an empty input-name list is accepted", _P,
       "    if (not isinstance(value, list) or not value\n", "    if (not isinstance(value, list)\n",
       "wrong_shape"),
    _m(5807, "a flange class that is not a whole number is accepted", _P,
       "            or not all(isinstance(c, int) and not isinstance(c, bool) and c > 0 for c in classes)):",
       "            or False):", "wrong_shape"),
    _m(5808, "the format is not checked", _P,
       '    if not isinstance(data, dict) or data.get("format") != FORMAT:',
       "    if not isinstance(data, dict):", "wrong_shape"),
)
