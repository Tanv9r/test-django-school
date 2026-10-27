"""Row-level visibility rules for patient data."""
from django.db.models import Q

from accounts.models import Role
from accounts.permissions import has_capability

from .models import Patient


def visible_patients(user, include_archived=True):
    """Patients this user may see.

    Administrators, receptionists and accountants see every patient. Doctors
    see patients they have an appointment, admission or medical record with;
    nurses see patients on admissions assigned to them.
    """
    qs = Patient.objects.all()
    if not include_archived:
        qs = qs.filter(is_active=True)
    if not has_capability(user, "patients_view"):
        return qs.none()
    if has_capability(user, "patients_view_all"):
        return qs
    role = user.effective_role
    if role == Role.DOCTOR:
        doctor = getattr(user, "doctor_profile", None)
        if doctor is None:
            return qs.none()
        ids = Patient.objects.filter(
            Q(appointments__doctor=doctor) | Q(admissions__attending_doctor=doctor) | Q(medical_records__doctor=doctor)
        ).values("pk")
        return qs.filter(pk__in=ids)
    if role == Role.NURSE:
        ids = Patient.objects.filter(admissions__assigned_nurse=user, admissions__status="admitted").values("pk")
        return qs.filter(pk__in=ids)
    return qs.none()
