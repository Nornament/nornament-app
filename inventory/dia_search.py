"""Search stock's filtering, as pure functions over row dicts (``dMatch``/``bubbles``).

Rows AND across filter rows and OR within one; each row of bubbles is counted
from every filter except its own, so choosing Round still shows Princess as an
option. A range grade answers for every grade it spans. Filters live in the
URL, so a search is a link.
"""
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

LIST_KEYS = ("shape", "col", "clar", "band")


def _number(raw):
    try:
        value = Decimal(raw)
    except (InvalidOperation, TypeError):
        return None
    return value if value.is_finite() else None


@dataclass(frozen=True)
class Filters:
    cat: str = ""
    shape: tuple = ()
    col: tuple = ()
    clar: tuple = ()
    band: tuple = ()
    batch: str = ""
    ct_from: Decimal = None
    ct_to: Decimal = None
    as_role: str = ""

    @classmethod
    def from_query(cls, query):
        return cls(
            cat=query.get("cat", ""), batch=query.get("batch", ""),
            ct_from=_number(query.get("ct_from")), ct_to=_number(query.get("ct_to")),
            as_role=query.get("as", ""),
            **{key: tuple(query.getlist(key)) for key in LIST_KEYS},
        )

    @property
    def active(self):
        return bool(self.cat or self.batch or self.ct_from is not None or self.ct_to is not None
                    or any(getattr(self, key) for key in LIST_KEYS))

    def href(self):
        pairs = [("cat", self.cat)] + [(key, v) for key in LIST_KEYS for v in getattr(self, key)]
        pairs += [("batch", self.batch), ("ct_from", self.ct_from), ("ct_to", self.ct_to), ("as", self.as_role)]
        return "?" + urlencode([(k, v) for k, v in pairs if v not in ("", None)])

    def toggled(self, key, value):
        values = getattr(self, key)
        return replace(self, **{key: tuple(v for v in values if v != value) if value in values else values + (value,)})

    def with_cat(self, value):
        return replace(self, cat=value, shape=(), col=(), clar=(), band=(), batch="")

    def cleared(self):
        return Filters(as_role=self.as_role)


def col_bucket(row):
    if row["cols"]:
        return row["cols"]
    colour = row["colour"] or ""
    if not colour:
        return ["(no colour stated)"]
    if colour.startswith("Fancy"):
        return [colour]
    if colour.startswith("?"):
        return ["? unresolved token"]
    return ["? misread from the item code"]


def clar_bucket(row):
    if row["clars"]:
        return row["clars"]
    return [f"? {row['clarity']}" if row["clarity"] else "(no clarity stated)"]


def _values(row, key):
    if key == "col":
        return col_bucket(row)
    if key == "clar":
        return clar_bucket(row)
    return [row[key]]


def matches(row, f, skip=None):
    if skip != "cat" and f.cat and row["category"] != f.cat:
        return False
    for key in LIST_KEYS:
        chosen = getattr(f, key)
        if skip != key and chosen and not set(chosen) & set(_values(row, key)):
            return False
    if skip != "batch" and f.batch and row["batch"] != f.batch:
        return False
    if skip != "ct" and (f.ct_from is not None or f.ct_to is not None):
        if row["ct_lo"] is None:
            return False
        if f.ct_from is not None and row["ct_hi"] < f.ct_from:
            return False
        if f.ct_to is not None and row["ct_lo"] > f.ct_to:
            return False
    return True


def select(rows, f, skip=None):
    return [row for row in rows if matches(row, f, skip)]


def bubbles(rows, f, key, order=None):
    """Only values that exist in the current selection, with carats and line counts."""
    tally = {}
    for row in select(rows, f, skip=key):
        for value in _values(row, key):
            n, ct = tally.get(value, (0, Decimal("0")))
            tally[value] = (n + 1, ct + (row["ct"] or 0))
    if order is not None:
        keys = [v for v in order if v in tally] + sorted(v for v in tally if v not in order)
    else:
        keys = sorted(tally, key=lambda v: -tally[v][1])
    chosen = getattr(f, key)
    return [{"value": v, "n": tally[v][0], "ct": tally[v][1], "on": v in chosen, "href": f.toggled(key, v).href()}
            for v in keys]


def category_bubbles(rows, f):
    tally = {}
    for row in select(rows, f, skip="cat"):
        n, ct = tally.get(row["category"], (0, Decimal("0")))
        tally[row["category"]] = (n + 1, ct + (row["ct"] or 0))
    return [{"value": c, "n": tally[c][0], "ct": tally[c][1], "on": f.cat == c, "href": f.with_cat(c).href()}
            for c in sorted(tally, key=lambda c: -tally[c][1])]
