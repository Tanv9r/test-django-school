from django.db import transaction
from django.utils import timezone

from accounts.permissions import has_capability
from patients.selectors import visible_patients
from pharmacy.models import StockTransaction
from pharmacy.services import StockError, adjust_stock

from .models import MedicalRecord, Prescription


def visible_records(user):
    if not has_capability(user, "records_view"):
        return MedicalRecord.objects.none()
    return MedicalRecord.objects.filter(patient__in=visible_patients(user)).select_related("patient", "doctor")


def visible_prescriptions(user):
    qs = Prescription.objects.select_related("patient", "doctor")
    if not has_capability(user, "prescriptions_view"):
        return qs.none()
    if has_capability(user, "prescriptions_dispense"):
        return qs  # the pharmacy works the whole dispensing queue
    return qs.filter(patient__in=visible_patients(user))


def dispense_prescription(prescription, user):
    """Deduct stock for every linked item and mark the prescription dispensed (all or nothing)."""
    with transaction.atomic():
        rx = Prescription.objects.select_for_update().select_related("patient").get(pk=prescription.pk)
        if rx.status != Prescription.Status.ACTIVE:
            raise StockError("Only prescriptions awaiting dispensing can be dispensed.")
        for item in rx.items.select_related("medicine"):
            if item.medicine_id and item.quantity:
                if item.medicine.is_expired:
                    raise StockError(f"{item.medicine} has expired and cannot be dispensed.")
                adjust_stock(
                    item.medicine,
                    -item.quantity,
                    StockTransaction.Type.DISPENSE,
                    user,
                    note=f"Dispensed for {rx.patient.full_name}",
                    reference=rx.prescription_number,
                )
        rx.status = Prescription.Status.DISPENSED
        rx.dispensed_at = timezone.now()
        rx.dispensed_by = user
        rx.save(update_fields=["status", "dispensed_at", "dispensed_by", "updated_at"])
    return rx
