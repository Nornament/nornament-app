from decimal import Decimal

import pytest

from inventory.dia_rules import decode, size_band


@pytest.mark.parametrize("code, shape, colour, clarity", [
    ("DRFGH VS-SI", "Round", "F-G-H", "VS-SI"),
    ("DRKL SI-I", "Round", "K-L", "SI-I"),              # R is Round, not "Rejection K-L"
    ("DTBFGH VS-SI", "Tapered Baguette", "F-G-H", "VS-SI"),
    ("DMMN VVS-VS", "Marquise", "M-N", "VVS-VS"),
    ("DPCEF VVS-VS", "Princess", "E-F", "VVS-VS"),       # the IVY export: PC is Princess
    ("DPRGH", "Pear", "G-H", ""),                        # and PR is Pear
    ("DRSCIJ", "Rose Cut", "I-J", ""),
    ("DPIOVL", "Pie Cut Oval", "", ""),
    ("DPIPCEF VVS-VS", "Pie Cut Princess", "E-F", "VVS-VS"),
    ("DFY", "Fancy Colour", "Fancy Yellow", ""),
    ("DFBR", "Fancy Colour", "Fancy Brown", ""),
    ("HPHTRGH VS-SI", "Round", "G-H", "VS-SI"),
])
def test_codes_that_read_cleanly(code, shape, colour, clarity):
    out = decode(code)
    assert (out.shape, out.colour, out.clarity) == (shape, colour, clarity)
    assert out.confirmed, out.note


@pytest.mark.parametrize("code, shape, colour", [
    ("DRLC VS-SI", "Round", "? LC"),
    ("DASCLB", "Asscher", "? LB"),
    ("DTBBL", "Tapered Baguette", "? BL"),
    ("DPIRD8", "? PI RD8", ""),
])
def test_unresolved_tokens_stay_visible_and_unconfirmed(code, shape, colour):
    out = decode(code)
    assert (out.shape, out.colour) == (shape, colour)
    assert not out.confirmed


def test_a_single_grade_letter_is_read_but_not_confirmed():
    out = decode("SOMG VS1")
    assert (out.shape, out.colour, out.clarity) == ("Marquise", "G", "VS1")
    assert not out.confirmed


def test_foil_polki_and_the_bare_code():
    polki = decode("FPL")
    assert polki.shape == "Polki" and not polki.confirmed and "FPL" in polki.note
    bare = decode("D")
    assert bare.shape == "" and not bare.confirmed


@pytest.mark.parametrize("size, band", [
    ("0000-000", "-2"), ("0-1", "-2"), ("+1", "-2"), ("-2BG", "-2"),
    ("+2", "+2-6"), ("+5", "+2-6"), ("+6", "+6-11"), ("+6-12", "+6-11"),
    ("+11", "11-20"), ("+80-100", "20+"), ("", "?"), ("mixed", "?"),
])
def test_sizes_fall_into_the_prototype_bands(size, band):
    assert size_band(size).band == band


def test_a_carat_band_carries_its_range_and_shape():
    sized = size_band("TR 0.20-0.24")
    assert (sized.band, sized.ct_lo, sized.ct_hi, sized.shape) == ("carat band", Decimal("0.20"), Decimal("0.24"), "Trillion")
    assert size_band("PR 0.10-0.12").shape == "Pear"
    assert size_band("PC 0.16-0.19").shape == "Princess"
