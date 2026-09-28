"""The prototype's rules, as pure functions.

Ported from ``build_ui.py`` and ``_script.html`` so the numbers here match the
ones the owner has already seen: the batch-code grammar, the size cell, the
colour family a free-text colour belongs to, and the silhouette each card draws
before a photo exists. Nothing here touches the database.
"""
import itertools
import re
from decimal import Decimal

BATCH_CODE = re.compile(r"^([A-Z])([A-Z])(\d+)([A-Z]+)$")


def parse_batch_code(code):
    """``SR01Y`` → ``("S", "R", "01", "Y")``: family, class, number, box colour."""
    match = BATCH_CODE.match((code or "").strip())
    return match.groups() if match else None


_LW = re.compile(r"^(\d+(?:\.\d+)?)\s*\*\s*(\d+(?:\.\d+)?)$")
_DIA = re.compile(r"^(\d+(?:\.\d+)?)$")
_NUMERIC = re.compile(r"^[\d.\s*,]+$")


def parse_size(text):
    """The ``Size Length * Width`` cell, in millimetres: (kind, display, length, width).

    Displays keep the digits as typed. The prototype printed parsed floats on
    multi-size cells, which is how "14" became "14.0".
    """
    value = (text or "").strip().rstrip(",*").strip()
    if not value:
        return ("none", "", None, None)
    match = _LW.match(value)
    if match:
        return ("lw", f"{match.group(1)} x {match.group(2)} mm", Decimal(match.group(1)), Decimal(match.group(2)))
    match = _DIA.match(value)
    if match:
        return ("dia", f"{match.group(1)} mm", Decimal(match.group(1)), None)
    if _NUMERIC.match(value):
        parts = []
        for piece in (p.strip() for p in value.split(",") if p.strip()):
            lw, dia = _LW.match(piece), _DIA.match(piece)
            if lw:
                parts.append((lw.group(1), lw.group(2)))
            elif dia:
                parts.append((dia.group(1), None))
        if parts:
            display = ", ".join(f"{a} x {b}" if b else a for a, b in parts) + " mm"
            length, width = parts[0]
            return ("multi", display, Decimal(length), Decimal(width) if width else None)
    return ("free", value, None, None)


#: first match wins, in this order — which is why "Pink Red" is Red
_FAMILY_WORDS = [
    ("feroza", "Turquoise / Feroza"), ("sea blue", "Sea Blue"), ("turq", "Turquoise / Feroza"),
    ("green", "Green"), ("maroon", "Red"), ("red", "Red"), ("pink", "Pink"), ("blue", "Blue"),
    ("purple", "Purple"), ("yellow", "Yellow"), ("golden", "Yellow"), ("orange", "Orange"),
    ("brown", "Brown"), ("white", "White"), ("black", "Black"), ("grey", "Grey"),
    ("multi", "Multi"), ("mix", "Multi"), ("peridot", "Green"),
]


def colour_family(colour):
    lowered = (colour or "").lower()
    for word, family in _FAMILY_WORDS:
        if word in lowered:
            return family
    return ""


def is_misfiled(colour, box_label):
    """A stone whose colour family is not its box's colour.

    Only a box whose label starts with ``?`` is exempt — the prototype's rule,
    and the one its 127 comes from. Sea Blue in a Blue box agrees.
    """
    got = colour_family(colour)
    expected = box_label or ""
    if not got or not expected or expected.startswith("?"):
        return False
    return got != expected and not (expected == "Blue" and got == "Sea Blue")


_COLOUR_HEX = {
    "green": "#2f9e6b", "light green": "#7bc79a", "dark green": "#1c6b47", "pale green": "#a8d8bd",
    "peridot green": "#8fbf3f", "yellowish green": "#9fbf45", "grey green": "#7f9686",
    "red": "#cf3b3b", "dark red": "#8f2222", "light red": "#e07070", "maroon": "#6f1f2a", "pink red": "#d9506e",
    "pink": "#e07ba0", "light pink": "#f0b3c7", "dark pink": "#c2436f", "pink light": "#f0b3c7",
    "blue": "#2f7fd0", "dark blue": "#1b4b8f", "light blue": "#7fb6e8", "blue light": "#7fb6e8",
    "sea blue": "#2f9ec4", "feroza": "#25b3b3",
    "purple": "#7a5bc4", "purple light": "#a894dd", "purple dark": "#4f3690",
    "yellow": "#e0a51e", "light yellow": "#f0d271", "yellow dark": "#b8801a", "yellow pale": "#f2e2a8",
    "golden yellow": "#d99a12", "yellow golden": "#d99a12",
    "orange": "#e07030", "light orange": "#f0a56f",
    "brown": "#8a5a3b", "brown light": "#b08560", "brown dark": "#5c3a24",
    "yellowish brown": "#a3762e", "brown yellowish": "#a3762e",
    "white": "#eceae2", "off white": "#e2ded1", "pale white": "#f2f0e9", "dull white": "#dedbd0",
    "steel white": "#d6d9db", "sparkle white": "#f4f2ea",
    "black": "#2e2e2b", "grey": "#9a9891",
    "multi": "#b06fc0", "mix": "#b06fc0", "red, pink": "#d9506e",
}
_FAMILY_HEX = {
    "Green": "#2f9e6b", "Red": "#cf3b3b", "Pink": "#e07ba0", "Blue": "#2f7fd0", "Sea Blue": "#2f9ec4",
    "Turquoise / Feroza": "#25b3b3", "Purple": "#7a5bc4", "Yellow": "#e0a51e", "Orange": "#e07030",
    "Brown": "#8a5a3b", "White": "#eceae2", "Black": "#2e2e2b", "Grey": "#9a9891", "Multi": "#b06fc0",
}


def colour_hex(colour):
    """The paint for a silhouette: the colour as recorded, else its family, else grey."""
    key = (colour or "").strip().lower()
    return _COLOUR_HEX.get(key) or _FAMILY_HEX.get(colour_family(colour), "#b9b6ad")


_ids = itertools.count(1)


def shape_svg(shape, hex_colour):
    """``shapeSVG`` from the prototype: the card is image-led before any photo exists.

    One fix: the prototype's first rule needed "bead" in the shape, so a plain
    "Round" fell through to the default ellipse. Round and mani are circles;
    beads (and mani, which is a bead) get the drill hole.
    """
    sh = (shape or "").lower()
    gid = f"g{next(_ids)}"
    c = hex_colour or "#b9b6ad"
    defs = (
        f'<defs><radialGradient id="{gid}" cx="34%" cy="28%">'
        '<stop offset="0%" stop-color="#fff" stop-opacity=".92"/>'
        f'<stop offset="38%" stop-color="{c}" stop-opacity="1"/>'
        f'<stop offset="100%" stop-color="{c}" stop-opacity="1"/></radialGradient></defs>'
    )
    st = f'fill="url(#{gid})" stroke="rgba(11,11,11,.18)" stroke-width="1.2"'
    if re.search(r"beads round|^round|^mani", sh):
        hole = '<circle cx="50" cy="50" r="6.5" fill="rgba(0,0,0,.35)"/>' if ("bead" in sh or sh.startswith("mani")) else ""
        body = f'<circle cx="50" cy="50" r="30" {st}/>{hole}'
    elif re.search(r"beads long|cylinder|drum", sh):
        body = f'<rect x="26" y="34" width="48" height="32" rx="15" {st}/><circle cx="50" cy="50" r="5" fill="rgba(0,0,0,.32)"/>'
    elif re.search(r"figurine|carv", sh):
        body = f'<path d="M50 16c11 0 15 9 12 16 8 3 14 11 14 21 0 16-12 27-26 27S24 69 24 53c0-10 6-18 14-21-3-7 1-16 12-16z" {st}/>'
    elif re.search(r"tear|drop|pear", sh):
        body = f'<path d="M50 14c9 14 22 24 22 40 0 15-10 26-22 26S28 69 28 54c0-16 13-26 22-40z" {st}/>'
    elif "marquise" in sh:
        body = f'<path d="M50 12c14 12 22 26 22 38S64 78 50 88C36 78 28 62 28 50S36 24 50 12z" {st}/>'
    elif "oval" in sh:
        body = f'<ellipse cx="50" cy="50" rx="27" ry="37" {st}/>'
    elif re.search(r"princess|square", sh):
        body = f'<rect x="20" y="20" width="60" height="60" rx="5" {st}/>'
    elif re.search(r"rect|bugutte|baguette", sh):
        body = f'<rect x="30" y="16" width="40" height="68" rx="4" {st}/>'
    elif "heart" in sh:
        body = f'<path d="M50 84C30 68 20 56 20 43c0-11 8-17 16-17 6 0 11 3 14 8 3-5 8-8 14-8 8 0 16 6 16 17 0 13-10 25-30 41z" {st}/>'
    elif re.search(r"triangle|trillion|kite", sh):
        body = f'<path d="M50 16 82 76H18z" {st}/>'
    elif "cushion" in sh:
        body = f'<rect x="19" y="19" width="62" height="62" rx="20" {st}/>'
    elif re.search(r"uneven|tumble|fancy|mix|free", sh):
        body = f'<path d="M32 24c14-7 34-5 43 6s9 30-2 41-33 14-44 4-11-44 3-51z" {st}/>'
    else:
        body = f'<ellipse cx="50" cy="50" rx="28" ry="36" {st}/>'
    highlight = '<ellipse cx="38" cy="30" rx="8" ry="11" fill="#fff" opacity=".5"/>'
    return f'<svg viewBox="0 0 100 100" aria-hidden="true">{defs}{body}{highlight}</svg>'
