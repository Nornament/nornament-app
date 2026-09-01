"""Reading the IVY Karigar stock export.

The workbook is not a table: products are blocks of rows, and five material
bands run down each block independently. Everything that knows that shape
lives here, so ``views.py`` never has to.
"""
from .analyse import analyse
from .commit import commit
from .ivy import parse

__all__ = ["parse", "analyse", "commit"]
