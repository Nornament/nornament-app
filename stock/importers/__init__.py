"""Reading the IVY Karigar stock export.

The workbook is not a table: products are blocks of rows, and five material
bands run down each block independently. Everything that knows that shape
lives here, so ``views.py`` never has to.

Submodules are imported directly (``from stock.importers import ivy``) rather
than re-exported here, so a broken module fails loudly at its own import site.
"""
