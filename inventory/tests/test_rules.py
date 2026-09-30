from decimal import Decimal

from inventory import rules


def test_a_batch_code_reads_as_family_class_number_box_colour():
    assert rules.parse_batch_code("SR01Y") == ("S", "R", "01", "Y")
    assert rules.parse_batch_code("SP25SB") == ("S", "P", "25", "SB")
    assert rules.parse_batch_code("Broken") is None
    assert rules.parse_batch_code("") is None


def test_size_kinds():
    assert rules.parse_size("14*10") == ("lw", "14 x 10 mm", Decimal("14"), Decimal("10"))
    assert rules.parse_size("6") == ("dia", "6 mm", Decimal("6"), None)
    assert rules.parse_size("2,3,4,") == ("multi", "2, 3, 4 mm", Decimal("2"), None)
    assert rules.parse_size("14*9.5, 6") == ("multi", "14 x 9.5, 6 mm", Decimal("14"), Decimal("9.5"))
    assert rules.parse_size("13*6*14") == ("multi", "13 x 6 x 14 mm", Decimal("13"), Decimal("6"))
    assert rules.parse_size("Free Far") == ("free", "Free Far", None, None)
    assert rules.parse_size("") == ("none", "", None, None)
    assert rules.parse_size(None) == ("none", "", None, None)


def test_colour_family_takes_the_first_word_that_matches():
    assert rules.colour_family("Light Green") == "Green"
    assert rules.colour_family("Pink Red") == "Red"          # red is checked before pink
    assert rules.colour_family("Feroza") == "Turquoise / Feroza"
    assert rules.colour_family("Sea Blue") == "Sea Blue"
    assert rules.colour_family("Maroon") == "Red"
    assert rules.colour_family("N.A") == ""


def test_misfiled_compares_family_with_the_box():
    assert rules.is_misfiled("Red", "Green")
    assert not rules.is_misfiled("Light Green", "Green")
    assert not rules.is_misfiled("Sea Blue", "Blue")          # the one pairing that agrees
    assert not rules.is_misfiled("Red", "? unresolved")        # an unreadable box is never judged
    assert not rules.is_misfiled("N.A", "Green")               # nor an unreadable colour
    assert rules.is_misfiled("Pink", "Brown-Yellow")           # unconfirmed but labelled: judged


def test_colour_hex_falls_back_to_the_family_then_grey():
    assert rules.colour_hex("Light Green") == "#7bc79a"
    assert rules.colour_hex("Greenish") == "#2f9e6b"
    assert rules.colour_hex("") == "#b9b6ad"


def test_round_stones_are_circles_and_beads_have_a_hole():
    round_stone = rules.shape_svg("Round", "#cf3b3b")
    bead = rules.shape_svg("Beads Round", "#cf3b3b")
    assert '<circle cx="50" cy="50" r="30"' in round_stone and 'r="6.5"' not in round_stone
    assert 'r="6.5"' in bead
    assert "<ellipse" in rules.shape_svg("Oval", "#cf3b3b")
    assert rules.shape_svg("Oval", "#cf3b3b") != rules.shape_svg("Oval", "#cf3b3b")  # unique gradient ids
