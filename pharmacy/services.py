from django.db import transaction

from .models import Medicine, StockTransaction


class StockError(Exception):
    pass


def adjust_stock(medicine, change: int, transaction_type: str, user=None, note: str = "", reference: str = ""):
    """Apply a signed stock change atomically and record it. Never allows negative stock."""
    if change == 0:
        raise StockError("The quantity change cannot be zero.")
    with transaction.atomic():
        current = Medicine.objects.select_for_update().get(pk=medicine.pk)
        new_quantity = current.quantity + change
        if new_quantity < 0:
            raise StockError(
                f"Insufficient stock for {current.name}: {current.quantity} {current.unit} available, "
                f"{-change} requested."
            )
        # Conditional update guards against a concurrent change between read and write.
        updated = Medicine.objects.filter(pk=current.pk, quantity=current.quantity).update(quantity=new_quantity)
        if updated != 1:
            raise StockError("Stock was changed by another user. Please try again.")
        entry = StockTransaction.objects.create(
            medicine=current,
            transaction_type=transaction_type,
            quantity_change=change,
            balance_after=new_quantity,
            reference=reference[:60],
            note=note[:255],
            performed_by=user,
        )
    medicine.quantity = new_quantity
    return entry
