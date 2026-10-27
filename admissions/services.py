from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.utils import timezone

from .models import Admission, Bed


class AdmissionError(Exception):
    pass


def admit_patient(*, patient, bed, doctor, reason, user, nurse=None, admitted_at=None):
    """Create an admission and occupy the bed in a single transaction."""
    try:
        with transaction.atomic():
            bed = Bed.objects.select_for_update().select_related("room").get(pk=bed.pk)
            if bed.status != Bed.Status.AVAILABLE or not bed.room.is_active:
                raise AdmissionError(f"Bed {bed} is not available.")
            if Admission.objects.filter(patient=patient, status=Admission.Status.ADMITTED).exists():
                raise AdmissionError(f"{patient.full_name} is already admitted.")
            if not patient.is_active:
                raise AdmissionError("Archived patients cannot be admitted. Restore the record first.")
            # Conditional update: only succeeds if nobody occupied the bed in the meantime.
            if not Bed.objects.filter(pk=bed.pk, status=Bed.Status.AVAILABLE).update(status=Bed.Status.OCCUPIED):
                raise AdmissionError(f"Bed {bed} was just assigned to another patient.")
            admission = Admission.objects.create(
                patient=patient,
                bed=bed,
                attending_doctor=doctor,
                assigned_nurse=nurse,
                reason=reason,
                admitted_at=admitted_at or timezone.now(),
                admitted_by=user,
            )
    except IntegrityError as exc:
        raise AdmissionError("The bed or patient already has an active admission.") from exc
    return admission


def discharge_patient(admission, *, summary, user, discharged_at=None):
    """Close an admission and release its bed in a single transaction."""
    with transaction.atomic():
        admission = Admission.objects.select_for_update().get(pk=admission.pk)
        if admission.status != Admission.Status.ADMITTED:
            raise AdmissionError("This patient has already been discharged.")
        discharged_at = discharged_at or timezone.now()
        if discharged_at < admission.admitted_at:
            raise AdmissionError("The discharge time cannot be before the admission time.")
        admission.status = Admission.Status.DISCHARGED
        admission.discharged_at = discharged_at
        admission.discharge_summary = summary
        admission.discharged_by = user
        admission.save(update_fields=["status", "discharged_at", "discharge_summary", "discharged_by", "updated_at"])
        Bed.objects.filter(pk=admission.bed_id, status=Bed.Status.OCCUPIED).update(status=Bed.Status.AVAILABLE)
    return admission


def occupancy_summary():
    totals = Bed.objects.filter(room__is_active=True).aggregate(
        total=Count("id"),
        available=Count("id", filter=Q(status=Bed.Status.AVAILABLE)),
        occupied=Count("id", filter=Q(status=Bed.Status.OCCUPIED)),
        maintenance=Count("id", filter=Q(status=Bed.Status.MAINTENANCE)),
    )
    usable = totals["total"] - totals["maintenance"]
    totals["occupancy_rate"] = round(totals["occupied"] * 100 / usable) if usable else 0
    return totals
