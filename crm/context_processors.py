"""The open-item counts the legacy CRM printed on its sidebar and bottom nav.

Wrapped in a ``SimpleLazyObject`` so the four COUNTs only run when a template
actually reads them — which is ``crm_base.html`` and nothing else. Stock pages
pay nothing for this being installed globally.
"""
from django.utils.functional import SimpleLazyObject


def _counts():
    from .models import ClientMaterial, Enquiry, Order, Repair

    return {
        "enquiries": Enquiry.objects.exclude(status__in=["Order Confirmed", "Lost"]).count(),
        "orders": Order.objects.exclude(status__in=["Delivered", "Cancelled"]).count(),
        "materials": ClientMaterial.objects.exclude(
            status__in=["Moved to Order", "Moved to Repair", "Returned"]
        ).count(),
        "repairs": Repair.objects.exclude(status="Delivered").count(),
    }


def nav_counts(request):
    if not request.user.is_authenticated:
        return {}
    return {"crm_open": SimpleLazyObject(_counts)}
