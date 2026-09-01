"""Reading the IVY Karigar stock export.

The workbook is not a table: products are blocks of rows, and five material
bands run down each block independently. Everything that knows that shape
lives here, so ``views.py`` never has to.
"""
from .ivy import parse

# analyse/commit land in later tasks; guarded so the package (and anything
# that already does ``from stock.importers import ivy``) works incrementally
# instead of failing on a sibling module that hasn't been written yet. Scoped
# to exactly that missing-module case so a real ImportError from inside
# analyse.py/commit.py (bad third-party import, circular import, ...) still
# raises loudly instead of being downgraded to ``analyse = None``.
# ponytail: temporary scaffolding — Task 6 deletes this guard and restores
# plain eager imports once both analyse.py and commit.py exist.
try:
    from .analyse import analyse
except ImportError as exc:
    if exc.name != "stock.importers.analyse":
        raise
    analyse = None
try:
    from .commit import commit
except ImportError as exc:
    if exc.name != "stock.importers.commit":
        raise
    commit = None

__all__ = ["parse", "analyse", "commit"]
