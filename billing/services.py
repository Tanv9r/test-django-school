from django.db import transaction
from django.utils import timezone

from .models import ZERO, Invoice, InvoiceItem, Payment, money


class BillingError(Exception):
    pass


def consultation_charge(appointment):
    local = timezone.localtime(appointment.start_at)
    return {
        "item_type": InvoiceItem.ItemType.CONSULTATION,
        "description": f"Consultation – {appointment.doctor} ({local:%d %b %Y})",
        "quantity": 1,
        "unit_price": appointment.doctor.consultation_fee,
    }


def room_charge(admission):
    room_type = admission.bed.room.room_type
    days = admission.length_of_stay_days
    return {
        "item_type": InvoiceItem.ItemType.ROOM,
        "description": f"{room_type} – Room {admission.bed.room.number}, {days} day(s)",
        "quantity": days,
        "unit_price": room_type.daily_rate,
    }


def save_invoice(invoice, item_rows, user=None):
    """Create/replace an invoice's items atomically and recompute totals.

    ``item_rows`` is a list of dicts with item_type, description, quantity and unit_price.
    """
    if not item_rows:
        raise BillingError("An invoice needs at least one charge.")
    subtotal = sum((money(r["quantity"] * money(r["unit_price"])) for r in item_rows), ZERO)
    if money(invoice.discount_amount) > subtotal:
        raise BillingError("The discount cannot be larger than the subtotal.")
    with transaction.atomic():
        if invoice.pk is None:
            invoice.created_by = user
        elif not invoice.is_editable:
            raise BillingError("Only unpaid invoices without payments can be edited.")
        invoice.save()
        invoice.items.all().delete()
        for row in item_rows:
            InvoiceItem.objects.create(invoice=invoice, **row)
        invoice.recalculate()
    return invoice


def record_payment(invoice, *, amount, method, user, reference="", notes="", paid_at=None):
    amount = money(amount)
    if amount <= ZERO:
        raise BillingError("The payment amount must be greater than zero.")
    with transaction.atomic():
        invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
        invoice.recalculate(save=False)
        if invoice.status == Invoice.Status.CANCELLED:
            raise BillingError("Payments cannot be recorded against a cancelled invoice.")
        if invoice.total <= ZERO:
            raise BillingError("This invoice has no amount due.")
        if amount > invoice.balance_due:
            raise BillingError(f"The payment exceeds the outstanding balance of {invoice.balance_due}.")
        if not method.is_active:
            raise BillingError("This payment method is not active.")
        payment = Payment.objects.create(
            invoice=invoice,
            amount=amount,
            method=method,
            reference=reference,
            notes=notes,
            received_by=user,
            paid_at=paid_at or timezone.now(),
        )
        invoice.recalculate()
    return payment


def cancel_invoice(invoice, reason):
    with transaction.atomic():
        invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
        if invoice.status == Invoice.Status.CANCELLED:
            raise BillingError("This invoice is already cancelled.")
        if invoice.payments.exists():
            raise BillingError("Invoices with recorded payments cannot be cancelled.")
        invoice.status = Invoice.Status.CANCELLED
        invoice.cancelled_at = timezone.now()
        invoice.cancellation_reason = reason[:255]
        invoice.save(update_fields=["status", "cancelled_at", "cancellation_reason", "updated_at"])
    return invoice
