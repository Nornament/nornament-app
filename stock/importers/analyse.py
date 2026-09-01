"""What an import would do, worked out before it does any of it.

Nothing here writes. The review screen renders a Plan, the reviewer edits the
decisions that come out of it, and only then does ``commit`` run. Keeping the
diff pure is what makes the review screen safe to reload.
"""
import re
from dataclasses import dataclass, field

from stock.importers import guess
from stock.models import Category, Collection, Material, Piece, Style, Vendor


@dataclass
class Resolution:
    """One decision: what the sheet said, and what we propose doing about it."""
    key: str
    label: str = ""
    action: str = "create"          # map | create | skip | update
    target: object = None           # the existing row, when action is map
    fields: dict = field(default_factory=dict)
    problem: str = None             # non-None blocks the commit
    detail: str = ""                # human-readable extra, e.g. a diff


@dataclass
class Plan:
    materials: list = field(default_factory=list)
    categories: list = field(default_factory=list)
    collections: list = field(default_factory=list)
    vendors: list = field(default_factory=list)
    styles: list = field(default_factory=list)
    pieces: list = field(default_factory=list)

    @property
    def sections(self):
        return {
            "materials": self.materials,
            "categories": self.categories,
            "collections": self.collections,
            "vendors": self.vendors,
            "styles": self.styles,
            "pieces": self.pieces,
        }

    @property
    def blockers(self):
        """Every unresolved row, across every section."""
        return [r for rows in self.sections.values() for r in rows if r.problem]

    @property
    def counts(self):
        out = {}
        for name, rows in self.sections.items():
            out[name] = {
                "total": len(rows),
                "map": sum(1 for r in rows if r.action == "map"),
                "create": sum(1 for r in rows if r.action == "create"),
                "skip": sum(1 for r in rows if r.action == "skip"),
                "blocked": sum(1 for r in rows if r.problem),
            }
        return out


def _norm(name):
    """Loose enough that 'Earring' finds 'Earrings' and 'Ring' finds 'Rings'."""
    return re.sub(r"[^a-z]", "", (name or "").lower())


#: below this, a substring match means nothing — "ad" is inside half the words
MIN_CONTAINMENT = 4


def _match_score(target, candidate):
    """Lower is better. None means these two do not match at all.

    Plain containment is not enough on its own: ``ring`` is inside
    ``earrings``, so the sheet's "Ring" would silently file every ring under
    Earrings. Ranking exact above plural above containment — and preferring
    the closest containment by length — keeps "Ring" on "Rings" while still
    letting "Bracelet" reach "Bangles / Bracelets".
    """
    if target == candidate:
        return 0
    if target + "s" == candidate or candidate + "s" == target:
        return 1
    shorter, longer = sorted((target, candidate), key=len)
    if len(shorter) >= MIN_CONTAINMENT and shorter in longer:
        return 2 + (len(longer) - len(shorter))
    return None


def _fuzzy(name, existing):
    """The existing row this name most plausibly means, or None."""
    target = _norm(name)
    if not target:
        return None
    scored = []
    for row in existing:
        score = _match_score(target, _norm(row.name))
        if score is not None:
            scored.append((score, row))
    if not scored:
        return None
    return min(scored, key=lambda pair: pair[0])[1]


def _material_rows(pieces):
    seen, rows = {}, []
    known = {m.item_code: m for m in Material.objects.all()}
    for piece in pieces:
        for line in piece.lines:
            fields, problem = guess.material_fields(line)
            code = fields["item_code"]
            if code in seen:
                continue
            seen[code] = True
            existing = known.get(code)
            rows.append(Resolution(
                key=line.code,
                label=line.name or line.code,
                action="map" if existing else "create",
                target=existing,
                fields=fields,
                problem=None if existing else problem,
                detail=line.band,
            ))
    return sorted(rows, key=lambda r: (r.problem is None, r.detail, r.key))


def _named_rows(values, model, create_code=True):
    existing = list(model.objects.all())
    rows = []
    for value in sorted({v for v in values if v}):
        match = _fuzzy(value, existing)
        rows.append(Resolution(
            key=value,
            label=value,
            action="map" if match else "create",
            target=match,
            fields={"name": value, "code": _norm(value).upper()[:32]} if create_code else {"name": value},
            detail=f"→ {match.name}" if match else "",
        ))
    return rows


def _style_rows(pieces):
    known = set(Style.objects.values_list("style_code", flat=True))
    rows, seen = [], set()
    for piece in pieces:
        if piece.style_code in seen:
            continue
        seen.add(piece.style_code)
        rows.append(Resolution(
            key=piece.style_code,
            label=piece.style_code,
            action="map" if piece.style_code in known else "create",
            detail=piece.category,
        ))
    return rows


def _piece_diff(existing, parsed):
    """The fields an update would change, as one readable line."""
    changes = []
    for label, was, now in (
        ("purity", existing.metal_purity, parsed.metal_purity),
        ("sub-category", existing.sub_category, parsed.sub_category),
        ("cost", existing.src_cost_price, parsed.src_cost_price),
        ("sale", existing.src_sale_price, parsed.src_sale_price),
    ):
        if now and str(was or "") != str(now):
            changes.append(f"{label} {was or '—'} → {now}")
    return "; ".join(changes)


def _piece_rows(pieces):
    known = {p.jewel_code: p for p in Piece.objects.all()}
    rows = []
    for piece in pieces:
        existing = known.get(piece.jewel_code)
        rows.append(Resolution(
            key=piece.jewel_code,
            label=f"{piece.jewel_code} · {piece.style_code}",
            # an existing piece is offered, never ticked: see the spec
            action="skip" if existing else "create",
            target=existing,
            detail=_piece_diff(existing, piece) if existing else piece.category,
        ))
    return rows


def analyse(pieces):
    """Everything the import would touch, decided but not done."""
    return Plan(
        materials=_material_rows(pieces),
        categories=_named_rows({p.category for p in pieces}, Category),
        collections=_named_rows({p.collection for p in pieces}, Collection),
        vendors=_named_rows({p.vendor for p in pieces}, Vendor),
        styles=_style_rows(pieces),
        pieces=_piece_rows(pieces),
    )


def default_decisions(plan):
    """The plan's own proposals, in the shape the review form posts back."""
    return {
        section: {
            row.key: {
                "action": row.action,
                "target": getattr(row.target, "pk", None),
                "fields": row.fields,
            }
            for row in rows
        }
        for section, rows in plan.sections.items()
    }
