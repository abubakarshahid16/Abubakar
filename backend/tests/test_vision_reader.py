"""#193 plan B4 item 1: the vision reader - a page image read by the
reasoning model, KEPT only where code proves it against the page.

Synthetic PDFs and a fake provider only: no client document, no network
(CLAUDE.md rules 1 and 3). Mutation proofs: M630-M639
(scripts/mutations/vision_reader.py).
"""
from __future__ import annotations

import json

import pymupdf
import pytest

from app import vision_reader as vr
from app.reasoning_provider import ProviderRefused, Response

#: A two-column form as a datasheet prints it. "OC" is how these sheets'
#: text layers print the degree sign.
ITEMS = [
    (50, 100, "SPECIFIC GRAVITY:"), (220, 100, "0.85 @ 150 OF"),
    (50, 130, "VAPOR PRESSURE: bar a"), (220, 130, "0.35"),
    (50, 160, "PUMPING TEMPERATURE: OC"), (220, 160, "60.0 (140)"),
    (50, 190, "VOLTAGE"), (220, 190, "250"),
    (50, 220, "ZONE"), (220, 220, "2"),
    (50, 250, "HYDROTEST"), (220, 250, "________ bar g"),
    (50, 280, "PERFORMANCE CURVE"),
    (50, 292, "& DATA APPROVAL"), (220, 292, "YES"),
    (400, 400, "REMARKS"), (50, 500, "NO"),
]


@pytest.fixture
def page(tmp_path):
    pdf = pymupdf.open()
    p = pdf.new_page(width=595, height=842)
    for x, y, text in ITEMS:
        p.insert_text((x, y), text, fontsize=10)
    path = tmp_path / "form.pdf"
    pdf.save(str(path))
    pdf.close()
    doc = pymupdf.open(str(path))
    yield doc[0]
    doc.close()


def _verify(page, label, value, unit=None, geometry=None):
    return vr.verify({"label": label, "value": value, "unit": unit},
                     vr.PageText.of(page), float(page.rect.width), geometry)


# ---------------------------------------------------------------- the checks

def test_a_value_beside_its_label_is_kept(page):
    """THE MUTATION TARGET (M630): label and value on the text layer, the
    value on the label's line to its right."""
    kept, why = _verify(page, "VOLTAGE", "250")
    assert why is None and kept["value"] == "250" and kept["proof"].startswith("text layer")
    assert kept["value_bbox"] and kept["label_bbox"]


def test_a_value_that_is_not_on_the_page_is_dropped(page):
    """THE MUTATION TARGET (M631): the model's word is never stored."""
    assert _verify(page, "VOLTAGE", "440") == (None, vr.VALUE_NOT_ON_PAGE)


def test_a_label_that_is_not_on_the_page_is_dropped(page):
    """THE MUTATION TARGET (M632)."""
    assert _verify(page, "SUPPLY VOLTAGE", "250") == (None, vr.LABEL_NOT_ON_PAGE)
    # every part of a grouped label must be printed
    assert _verify(page, "ELECTRICITY - VOLTAGE", "250") == (None, vr.LABEL_NOT_ON_PAGE)


def test_a_value_printed_elsewhere_is_not_beside_its_label(page):
    """THE MUTATION TARGET (M633): "NO" is on the page, but nowhere near
    REMARKS - a real value under the wrong label is the failure this stops."""
    assert _verify(page, "REMARKS", "NO") == (None, vr.VALUE_NOT_BESIDE_LABEL)


def test_a_number_is_never_found_inside_another_number(page):
    """THE MUTATION TARGET (M634): "2" is printed beside ZONE and inside
    "250"; "25" only inside "250" - not a printed value."""
    assert _verify(page, "ZONE", "2")[0] is not None
    assert _verify(page, "VOLTAGE", "25") == (None, vr.VALUE_NOT_BESIDE_LABEL)


def test_a_unit_must_be_the_values(page):
    """THE MUTATION TARGET (M635): a unit not on the page drops the reading
    (a number with the wrong unit is a wrong value); a unit in the label
    column, on the value's line, is the value's."""
    assert _verify(page, "VOLTAGE", "250", "kV") == (None, vr.UNIT_NOT_PROVEN)
    kept, _ = _verify(page, "VAPOR PRESSURE", "0.35", "bar a")
    assert kept is not None and kept["unit"] == "bar a"


def test_the_degree_sign_matches_the_text_layers_O(page):
    """THE MUTATION TARGET (M636): the image shows °C, the text layer says OC."""
    kept, why = _verify(page, "PUMPING TEMPERATURE", "60.0 (140)", "°C (°F)")
    assert why is None and (kept["value"], kept["unit"]) == ("60.0", "°C")
    assert vr.unit_spellings("kPa") == ["kPa"]


def test_a_condition_is_cut_and_its_unit_is_not_the_values(page):
    """THE MUTATION TARGET (M637): '0.85 @ 150 °F' is a gravity of 0.85;
    °F belongs to the condition, so it is dropped - not the reading."""
    kept, why = _verify(page, "SPECIFIC GRAVITY", "0.85 @ 150", "°F")
    assert why is None and kept["value"] == "0.85" and kept["unit"] is None


def test_reduce_rules():
    assert vr.reduce("12.0 (53)", "m3/h (USGPM)") == ("12.0", "m3/h", False)
    assert vr.reduce("<85", "(dBA)") == ("<85", "dBA", False)
    assert vr.reduce("0.85 @ 150", "°F") == ("0.85", "°F", True)
    # a list-item number is the list's marker; a number after it is kept
    assert vr.reduce("1. PUMPS SHALL BE TESTED", "")[0] == "PUMPS SHALL BE TESTED"
    assert vr.reduce("1. 5", "")[0] == "1. 5"
    # a bracket that is not a second number is part of the value
    assert vr.reduce("OUTDOOR (under shelter)", "") == ("OUTDOOR (under shelter)", "", False)


def test_a_blank_is_never_recorded_from_an_image(page):
    """THE MUTATION TARGET (M638): the text layer cannot prove an absence."""
    assert _verify(page, "HYDROTEST", "________") == (None, vr.BLANK)
    assert _verify(page, "HYDROTEST", "*") == (None, vr.BLANK)


def test_a_wrapped_label_is_proved_line_by_line(page):
    kept, why = _verify(page, "PERFORMANCE CURVE & DATA APPROVAL", "YES")
    assert why is None and kept is not None
    # the two halves exist, but not one above the other: not a wrapped label
    assert _verify(page, "DATA APPROVAL PERFORMANCE", "YES")[0] is None


def test_a_geometry_cell_is_proof(page):
    """A value the text layer does not hold verbatim, already read by the
    geometry reader in a cell under that label."""
    cell = [{"label": "VOLTAGE", "value": "250 V", "value_text": "250 V", "is_blank": False,
             "bbox": [200, 180, 240, 192], "label_bbox": [50, 180, 90, 192]}]
    kept, why = _verify(page, "VOLTAGE", "250 V", geometry=cell)
    assert why is None and kept["proof"] == "geometry cell"
    assert _verify(page, "VOLTAGE", "250 V")[0] is None


# ------------------------------------------------------------- one page read

class FakeProvider:
    def __init__(self, text="", *, finish="stop", refuse=None):
        self.text, self.finish, self.refuse, self.packets = text, finish, refuse, []

    def reason(self, packet):
        self.packets.append(packet)
        if self.refuse:
            raise ProviderRefused(self.refuse)
        return Response(text=self.text, provider="claude", model_tag="claude-sonnet-5",
                        digest="d", finish_reason=self.finish, prompt_sha256=packet.sha256,
                        schema_errors=())


def _answer(fields, kind="datasheet"):
    return json.dumps({"page_kind": kind, "fields": fields})


def test_read_page_keeps_only_what_the_page_proves(page):
    """THE MUTATION TARGET (M639): a page image goes out on the vision step,
    at low effort; what comes back is kept only when proved, counted by
    reason otherwise, and never raised."""
    provider = FakeProvider(_answer([
        {"label": "VOLTAGE", "value": "250", "unit": None},
        {"label": "VOLTAGE", "value": "440", "unit": None},
        {"label": "MOTOR", "value": "YES", "unit": None},
        {"label": "VOLTAGE", "value": "250", "unit": None},
    ]))
    reading = vr.read_page(page, 1, provider)
    packet = provider.packets[0]
    assert packet.step == vr.VISION_STEP == "b4-vision" and packet.effort == "low"
    assert len(packet.images) == 1 and packet.images[0].media_type == "image/png"
    assert max(packet.images[0].width, packet.images[0].height) <= vr.MAX_EDGE_PX
    assert [k["value"] for k in reading.kept] == ["250"]
    assert reading.dropped == {vr.VALUE_NOT_ON_PAGE: 1, vr.LABEL_NOT_ON_PAGE: 1, "duplicate": 1}
    assert reading.page_kind == "datasheet" and reading.proposed == 4


def test_a_refusal_or_a_truncated_answer_is_recorded_not_raised(page):
    refused = vr.read_page(page, 1, FakeProvider(refuse="budget"))
    assert refused.refused and not refused.asked and not refused.kept
    cut = vr.read_page(page, 1, FakeProvider(_answer([{"label": "VOLTAGE", "value": "250"}]),
                                             finish="length"))
    assert cut.refused == "truncated answer" and not cut.kept


def test_the_images_packet_changes_the_digest(page):
    image = vr.render(page)
    one = vr.packet_for(image, 1)
    other = vr.packet_for(image.__class__(image.media_type, image.data + "AA", image.width,
                                          image.height), 1)
    assert one.sha256 != other.sha256


def test_no_provider_without_claude(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "reasoning_provider", "ollama")
    provider, why = vr.provider()
    assert provider is None and "REASONING_PROVIDER" in why
