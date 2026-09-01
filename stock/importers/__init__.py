"""Reading the IVY Karigar stock export.

The workbook is not a table: products are blocks of rows, and five material
bands run down each block independently. Everything that knows that shape
lives here, so ``views.py`` never has to.
"""
from .ivy import parse

# analyse/commit land in later tasks; guarded so the package (and anything
# that already does ``from stock.importers import ivy``) works incrementally
# instead of failing on a sibling module that hasn't been written yet.
try:
    from .analyse import analyse
except ImportError:
    analyse = None
try:
    from .commit import commit
except ImportError:
    commit = None

__all__ = ["parse", "analyse", "commit"]
