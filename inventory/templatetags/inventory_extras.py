"""Number formats the prototype used (``toLocaleString('en-IN')``), and its silhouettes."""
from decimal import Decimal

from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

from crm.templatetags import crm_extras
from inventory import rules

register = template.Library()


@register.filter
def rupees(value):
    """``₹1,72,49,719``, or ``—`` when there is no figure — never ``₹0`` for a missing one."""
    return "—" if value is None or value == "" else crm_extras.inr(value)


@register.filter
def grouped(value):
    return "—" if value is None or value == "" else crm_extras.inr(value).replace("₹", "")


@register.filter
def ct(value):
    """``10,56,315.10`` — carats to two places, Indian grouping."""
    if value is None or value == "":
        return "—"
    whole, frac = f"{Decimal(value):.2f}".split(".")
    return crm_extras.inr(whole).replace("₹", "") + "." + frac


@register.filter
def kg(value):
    """Carats as kilograms: a carat is 0.2 g."""
    return "—" if value is None else f"{Decimal(value) * Decimal('0.2') / 1000:.0f}"


@register.simple_tag
def joined(*parts, sep=" · "):
    """The non-blank parts, joined — "" and None skipped rather than leaving a stray separator."""
    return sep.join(part for part in parts if part)


@register.simple_tag
def silhouette(shape, hex_colour):
    # the shape only picks a branch in rules.shape_svg; the colour is escaped
    # because this tag cannot know every caller passes one from its own table
    return mark_safe(rules.shape_svg(shape, escape(hex_colour)))
