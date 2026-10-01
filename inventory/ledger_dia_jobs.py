"""Diamond job cards: diamonds issued to a karigar, or in-house, on a card that is a ledger.

An issue is a debit: out of the line, owed by the card. Received loose and
returned unused are credits that come back into the line; consumed / set, loss
in process and breakage are credits that settle what is out without returning
it. Each entry carries its own date and challan or reference, so one card spans
several challans. A card stays open — more may be issued to it — until someone
closes it, and only at zero (``ledger.close_document``).
"""
from django.db import transaction
from django.utils import timezone

from accounts.capabilities import INV_JOB
from stock.services import ServiceError, require

from . import dia_services, ledger, ledger_jobs
from .models import DiamondLine, Movement, StockDocument

Kind, Reason = StockDocument.Kind, Movement.Reason

#: the prototype's six stock-control entries, in its order: (label, reason, direction)
ENTRIES = {
    "issue": ("Issue to job card", Reason.JOB_WORK_OUT, Movement.OUT),
    "loose": ("Received loose", Reason.JOB_WORK_IN, Movement.IN),
    "set": ("Consumed / set", Reason.CONSUMED, Movement.SETTLE),
    "loss": ("Loss in process", Reason.WASTAGE, Movement.SETTLE),
    "unused": ("Returned unused", Reason.RETURNED_UNUSED, Movement.IN),
    "breakage": ("Breakage", Reason.BREAKAGE, Movement.SETTLE),
}
#: the entry a movement on a card was posted as, for the ledger's chip
ENTRY_LABEL = {reason: label for label, reason, _ in ENTRIES.values()}
#: the "Stock control" select, in the prototype's words: a debit goes out, a credit comes back or settles
ENTRY_CHOICES = [(key, f"{label} — {'debit' if direction == Movement.OUT else 'credit'}")
                 for key, (label, _, direction) in ENTRIES.items()]


@transaction.atomic
def open_card(user, karigar, opened_on=None, note=""):
    """A new open card, numbered ``JC-…``. ``karigar`` is ``None`` for In-house, else one of
    ``ledger_jobs.karigar_choices(user)``: the masked choice list is the rule, as on a stones
    challan, so the Karigar desk cannot name a supplier it has never been shown."""
    require(user, INV_JOB, "Only a role that posts job cards can open one.")
    if karigar is not None and karigar.pk not in {choice["pk"] for choice in ledger_jobs.karigar_choices(user)}:
        raise ServiceError("Choose the karigar, or In-house.")
    return ledger.open_document(user, Kind.DIA_JOB, occurred_on=opened_on or timezone.localdate(),
                                vendor=karigar, note=(note or "").strip())


@transaction.atomic
def post_entry(user, card, entry, line, ct, occurred_on=None, ref="", note=""):
    """One entry on an open card, dated and referenced on its own. A credit is checked against
    what that line has out on this card; an issue against what the line holds."""
    require(user, INV_JOB, "Only a role that posts job cards can post an entry.")
    if card.kind != Kind.DIA_JOB:
        raise ServiceError(f"{card} is not a job card.")
    if entry not in ENTRIES:
        raise ServiceError("Choose the stock-control entry.")
    if line is None:
        raise ServiceError("Choose the line.")
    _, reason, direction = ENTRIES[entry]
    move = ledger.Line(line, reason, direction, None, ct, note=(note or "").strip(), ref=(ref or "").strip())
    return ledger.post(user, card, [move], occurred_on)[0]


def credit_choices(card):
    """The lines this card still has out, each with what is outstanding on it: what a credit may name."""
    out = {pk: ct for pk, (_, ct) in ledger.outstanding(card).items() if ct > 0}
    lines = dia_services.stocked_lines(DiamondLine.objects.filter(pk__in=out))
    return [{"pk": line.pk, "label": dia_services.line_label(line), "ct": out[line.pk]} for line in lines]


def owed(card):
    """The carats the card still has out, all lines together."""
    return sum((ct for _, ct in ledger.outstanding(card).values()), ledger.ZERO)
