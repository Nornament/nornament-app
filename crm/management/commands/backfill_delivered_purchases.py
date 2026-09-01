"""Delivered orders that never became a purchase, made into one.

The legacy CRM appended a ``purchases[]`` entry the moment an order reached
``Delivered``. Two things left holes in that: the guard only fired on the
*transition*, so an order that was already delivered when the rule arrived
never got one, and a device that moved an order while offline could flush the
order without the customer row that carried the purchase.

This finds those orders and records the purchase the delivery should have
made. It reports by default and writes only with ``--commit``, because it
creates revenue rows and that is not something to do by accident.

    manage.py backfill_delivered_purchases            # report only
    manage.py backfill_delivered_purchases --commit
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from crm import services
from crm.models import Order


class Command(BaseCommand):
    help = "Record the purchase a delivered order should have made, for orders missing one."

    def add_arguments(self, parser):
        parser.add_argument("--commit", action="store_true", help="Write the rows. Without it, nothing is created.")

    def handle(self, *args, **options):
        candidates = (
            Order.objects.filter(status="Delivered", customer__isnull=False, sales__isnull=True)
            .select_related("customer")
            .order_by("order_date", "order_code")
        )

        billable, unbillable = [], []
        for order in candidates:
            (billable if services.delivery_amount(order) is not None else unbillable).append(order)

        for order in billable:
            self.stdout.write(
                f"  {order.order_code:<12} {order.customer.name:<28} {services.delivery_amount(order)}"
            )
        for order in unbillable:
            self.stdout.write(
                self.style.WARNING(f"  {order.order_code:<12} {order.customer.name:<28} no bill amount — skipped")
            )

        if not options["commit"]:
            self.stdout.write(
                self.style.WARNING(
                    f"{len(billable)} purchase(s) would be recorded, {len(unbillable)} order(s) have no amount. "
                    "Re-run with --commit to write them."
                )
            )
            return

        written = 0
        with transaction.atomic():
            for order in billable:
                if services.record_order_delivery(order) is not None:
                    written += 1
        self.stdout.write(self.style.SUCCESS(f"{written} purchase(s) recorded, {len(unbillable)} skipped"))
