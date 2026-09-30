"""Reading a diamond item code and a size, as pure functions.

The grammar is the prototype's (``build_dia.py``) with the IVY export's own
Shape/ShapeName columns as the correction: PC is Princess and PR is Pear (the
prototype had them swapped), PI is "pie cut" in front of a shape, RSC is Rose
Cut. Anything that does not read becomes a ``?`` value and leaves the code
unconfirmed, so it is visible in Settings rather than guessed.
"""
import re
from dataclasses import dataclass
from decimal import Decimal

from .dia_seed import COLOUR_LADDER

#: clarity suffix after a space; spaces inside become hyphens
CLARITIES = ["VVS-VS", "VVS VS", "VS-SI", "VS SI", "SI-I", "SI I", "I1-I2", "VVS1", "VVS2", "VS1", "VS2"]
#: origin prefix; the line's category comes from its sheet column, so this is only stripped
ORIGINS = ["HPHT", "LG", "SO", "FP", "D"]
#: longest first — RSC before R, OVL before OV
SHAPES = [("RSC", "Rose Cut"), ("EMR", "Emerald"), ("ASC", "Asscher"), ("HRT", "Heart"), ("RD8", "? RD8"),
          ("OVL", "Oval"), ("OV", "Oval"), ("PC", "Princess"), ("PR", "Pear"), ("TB", "Tapered Baguette"),
          ("TR", "Trillion"), ("M", "Marquise"), ("R", "Round"), ("F", "Fancy Colour")]
FANCY = {"Y": "Fancy Yellow", "P": "Fancy Pink", "O": "Fancy Orange", "G": "Fancy Green", "B": "Fancy Blue",
         "BR": "Fancy Brown", "BL": "Fancy Black", "GL": "Fancy Grey"}
COLOURS = [("FGH", "F-G-H"), ("EF", "E-F"), ("GH", "G-H"), ("IJ", "I-J"), ("KL", "K-L"), ("MN", "M-N"),
           ("LC", "? LC"), ("LB", "? LB")]


@dataclass
class Decoded:
    shape: str = ""
    colour: str = ""
    clarity: str = ""
    note: str = ""

    @property
    def confirmed(self):
        values = (self.shape, self.colour, self.clarity)
        return not self.note and bool(self.shape) and not any(v.startswith("?") for v in values)


def decode(item_code):
    out = Decoded()
    t = (item_code or "").strip()
    for clarity in CLARITIES:
        if t.endswith(" " + clarity):
            out.clarity = clarity.replace(" ", "-")
            t = t[: -(len(clarity) + 1)].strip()
            break
    origin = next((o for o in ORIGINS if t.startswith(o)), "")
    if origin:
        t = t[len(origin):]
    else:
        out.note = "origin prefix not recognised"
    pie = t.startswith("PI")
    if pie:
        t = t[2:]
    for token, name in SHAPES:
        if t.startswith(token):
            out.shape, t = name, t[len(token):]
            break
    if pie:
        out.shape = f"? PI {out.shape[2:]}" if out.shape.startswith("?") else (f"Pie Cut {out.shape}" if out.shape else "? PI")
    if out.shape == "Fancy Colour" and t:
        out.colour, t = FANCY.get(t, f"? {t}"), ""
        if out.colour.startswith("?"):
            out.note = "fancy colour letter not recognised"
    if origin == "FP":
        out.shape = out.shape or "Polki"
        if t:
            out.note, t = f"FP{t} — is the {t} part of the product name?", ""
    if t:
        for token, name in COLOURS:
            if t.startswith(token):
                out.colour, t = name, t[len(token):]
                break
        else:
            if t in COLOUR_LADDER:
                out.colour, out.note = t, "single colour grade — confirm"
            else:
                out.colour, out.note = f"? {t}", out.note or "colour token not recognised"
            t = ""
    if t:
        out.note = out.note or f"left over: {t}"
    if not out.shape:
        out.note = out.note or "no shape in the code"
    return out


SUB = re.compile(r"^(0+)-(0+)$|^0-1$")
SIEVE_SINGLE = re.compile(r"^\+(\d+)$")
SIEVE_RANGE = re.compile(r"^\+(\d+)-(\d+)$")
CARAT = re.compile(r"^([A-Z]{1,3})\s+([\d.]+)-([\d.]+)$")
#: size prefixes on carat-banded goods, read the IVY way (PR Pear, PC Princess)
CARAT_SHAPES = {"PR": "Pear", "PC": "Princess", "M": "Marquise", "AS": "Asscher", "OV": "Oval", "EM": "Emerald",
                "TR": "Trillion", "H": "Heart", "TB": "Tapered Baguette", "R": "Round"}


@dataclass
class Sized:
    band: str
    ct_lo: Decimal = None
    ct_hi: Decimal = None
    shape: str = ""


def _sieve(lower):
    # "+2-6" read as passes +2, held by 6 — so +6 is the next band. Open question 7.
    return "+2-6" if lower < 6 else "+6-11" if lower < 11 else "11-20" if lower < 20 else "20+"


def size_band(size_text):
    z = (size_text or "").strip()
    if SUB.match(z) or z == "+1" or z.startswith("-2"):
        return Sized("-2")
    match = SIEVE_SINGLE.match(z) or SIEVE_RANGE.match(z)
    if match:
        return Sized(_sieve(int(match.group(1))))
    match = CARAT.match(z)
    if match:
        prefix = match.group(1)
        return Sized("carat band", Decimal(match.group(2)), Decimal(match.group(3)),
                     CARAT_SHAPES.get(prefix, f"? {prefix}"))
    return Sized("?")
