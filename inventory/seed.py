"""The prototype's code tables (``BOXCOL``, ``FAM``, ``CLS`` in build_ui.py), as data.

Kept out of the migration so a test can load the same rows the migration does.
Unconfirmed codes are the owner's open questions; they load as they are and are
corrected in Settings, not here.
"""
HATCH = "repeating-linear-gradient(45deg,#e2e0d7 0 6px,#f4f3f0 6px 12px)"

BOX_COLOURS = [
    # code, label, swatch (a CSS background), confirmed
    ("G", "Green", "#1baf7a", True),
    ("R", "Red", "#e34948", True),
    ("Y", "Yellow", "#eda100", True),
    ("W", "White", "#e8e6dd", True),
    ("M", "Multi", "linear-gradient(135deg,#e34948,#eda100,#1baf7a,#2a78d6)", True),
    ("B", "Blue", "#2a78d6", True),
    ("T", "Turquoise / Feroza", "#16b5b5", True),
    ("O", "Orange", "#eb6834", True),
    ("P", "Pink", "#e87ba4", True),
    ("SB", "Sea Blue", "#3f97d8", True),
    ("BK", "Black", "#4a4a46", True),
    ("PR", "Purple", "#7a63d8", True),
    ("BR", "Brown", "#a06a42", True),
    ("BY", "Brown-Yellow", "#b8912f", False),
    ("F", "? Fancy (pearl) — unconfirmed", "repeating-linear-gradient(45deg,#f0d9b0 0 6px,#faf3e6 6px 12px)", False),
    ("RG", "? unresolved", HATCH, False),
    ("RC", "? unresolved", HATCH, False),
    ("CM", "? unresolved", HATCH, False),
    ("C", "? unresolved", HATCH, False),
]

FAMILIES = [("S", "Stone", True), ("P", "Pearl", True), ("C", "CZ / American Diamond", True)]

CLASSES = [
    ("R", "Real", True),
    ("P", "Semi-Precious", True),
    ("L", "Lab / Man-made", True),
    ("S", "Shell or Synthetic ?", False),
    ("Z", "Zirconia", True),
]


def load(BoxColour, CodePart):
    """Idempotent: a code already there keeps whatever it has been corrected to."""
    for code, label, swatch, confirmed in BOX_COLOURS:
        BoxColour.objects.get_or_create(code=code, defaults={"label": label, "swatch": swatch, "confirmed": confirmed})
    for kind, rows in (("family", FAMILIES), ("class", CLASSES)):
        for code, label, confirmed in rows:
            CodePart.objects.get_or_create(kind=kind, code=code, defaults={"label": label, "confirmed": confirmed})
