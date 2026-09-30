from decimal import Decimal

from django.http import QueryDict

from inventory.dia_search import Filters, bubbles, category_bubbles, col_bucket, select


def _row(category, shape, colour, cols, clarity, clars, band, ct, batch="B1", lo=None, hi=None):
    return {"category": category, "shape": shape, "colour": colour, "cols": cols, "clarity": clarity,
            "clars": clars, "band": band, "ct": Decimal(ct), "batch": batch, "ct_lo": lo, "ct_hi": hi}


ROWS = [
    _row("Natural Diamond", "Round", "F-G-H", ["F", "G", "H"], "VS-SI", ["VS1", "VS2", "SI1", "SI2"], "+6-11", "3.40"),
    _row("Natural Diamond", "Princess", "E-F", ["E", "F"], "VVS-VS", ["VVS1", "VVS2", "VS1", "VS2"], "+2-6", "1.15", batch="B2"),
    _row("Natural Diamond", "Fancy Colour", "Fancy Yellow", [], "", [], "-2", "20.13"),
    _row("Foil Polki", "Polki", "", [], "", [], "20+", "43.21"),
    _row("Natural Diamond", "Trillion", "? LC", [], "VS-SI", ["VS1", "VS2", "SI1", "SI2"], "carat band", "0.93",
         lo=Decimal("0.20"), hi=Decimal("0.24")),
]


def _f(query=""):
    return Filters.from_query(QueryDict(query))


def test_a_range_grade_counts_under_each_grade():
    found = {b["value"]: b["n"] for b in bubbles(ROWS, _f(), "col", order=["D", "E", "F", "G", "H"])}
    assert found["F"] == 2 and found["G"] == 1 and found["E"] == 1


def test_colour_buckets():
    assert col_bucket(ROWS[2]) == ["Fancy Yellow"]
    assert col_bucket(ROWS[3]) == ["(no colour stated)"]
    assert col_bucket(ROWS[4]) == ["? unresolved token"]


def test_each_row_ignores_its_own_filter():
    f = _f("shape=Round")
    shapes = {b["value"] for b in bubbles(ROWS, f, "shape")}
    assert {"Round", "Princess", "Polki"} <= shapes            # the shape row is not narrowed by itself
    assert {b["value"] for b in bubbles(ROWS, f, "band")} == {"+6-11"}


def test_filters_and_across_rows_or_within():
    assert len(select(ROWS, _f("col=E&col=G"))) == 2
    assert len(select(ROWS, _f("col=E&band=%2B6-11"))) == 0


def test_choosing_a_category_clears_the_rest_but_not_carats():
    f = _f("shape=Round&batch=B1&ct_from=0.1").with_cat("Foil Polki")
    assert (f.cat, f.shape, f.batch, f.ct_from) == ("Foil Polki", (), "", Decimal("0.1"))


def test_carats_overlap_and_exclude_unbanded_lines():
    assert [r["shape"] for r in select(ROWS, _f("ct_from=0.22"))] == ["Trillion"]
    assert select(ROWS, _f("ct_from=0.3")) == []
    assert select(ROWS, _f("ct_from=nonsense")) == ROWS        # an unreadable number is ignored


def test_batch_filter_and_category_bubbles():
    assert len(select(ROWS, _f("batch=B2"))) == 1
    cats = category_bubbles(ROWS, _f())
    assert cats[0]["value"] == "Foil Polki"                    # heaviest first
    assert cats[0]["href"].startswith("?cat=Foil+Polki")


def test_toggling_builds_links():
    f = _f("shape=Round")
    assert "shape=Round" not in f.toggled("shape", "Round").href()
    assert "shape=Princess" in f.toggled("shape", "Princess").href()
    assert _f("as=SALES").toggled("band", "-2").href().endswith("&as=SALES")
