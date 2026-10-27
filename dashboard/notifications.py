"""Role-aware notifications for the top bar bell, built from live data."""
from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from accounts.models import Role
from accounts.permissions import has_capability
from core.models import AuditLog, HospitalSettings


def build_notifications(user):
    from admissions.models import NursingTask
    from appointments.models import Appointment
    from billing.models import Invoice
    from medical_records.models import Prescription
    from pharmacy.models import Medicine

    from .stats import today_bounds

    items = []

    def add(count, icon, text, url, level="primary"):
        if count:
            items.append({"count": count, "icon": icon, "text": text, "url": url, "level": level})

    start, end = today_bounds()
    if has_capability(user, "pharmacy_manage"):
        add(Medicine.objects.low_stock().count(), "box-seam", "medicines at or below reorder level",
            f"{reverse('pharmacy:list')}?stock=low", "warning")
        days = HospitalSettings.load().expiry_warning_days
        add(Medicine.objects.expiring_within(days).count(), "calendar-x", f"medicines expiring within {days} days",
            f"{reverse('pharmacy:list')}?stock=expiring", "danger")
    if has_capability(user, "prescriptions_dispense"):
        add(Prescription.objects.filter(status=Prescription.Status.ACTIVE).count(), "capsule",
            "prescriptions awaiting dispensing", reverse("records:prescription_list"))
    if user.effective_role == Role.DOCTOR and getattr(user, "doctor_profile", None):
        add(Appointment.objects.filter(doctor=user.doctor_profile, start_at__gte=start, start_at__lt=end,
                                       status__in=Appointment.OPEN_STATUSES).count(),
            "calendar-check", "appointments with you today", f"{reverse('appointments:list')}?scope=today")
    if has_capability(user, "appointments_manage"):
        add(Appointment.objects.filter(start_at__gte=start, start_at__lt=end, status=Appointment.Status.SCHEDULED).count(),
            "telephone", "appointments today still awaiting confirmation", f"{reverse('appointments:list')}?scope=today&status=scheduled")
    if user.effective_role == Role.NURSE:
        add(NursingTask.objects.filter(assigned_to=user, admission__status="admitted").exclude(status="done").count(),
            "clipboard2-pulse", "open nursing tasks assigned to you", reverse("admissions:tasks"), "info")
    if has_capability(user, "billing_view"):
        add(Invoice.objects.filter(status__in=Invoice.OUTSTANDING_STATUSES, due_date__lt=timezone.localdate()).count(),
            "receipt", "overdue invoices", f"{reverse('billing:invoice_list')}?status=unpaid", "danger")
    if has_capability(user, "adminpanel_access"):
        add(AuditLog.objects.filter(action=AuditLog.Action.LOGIN_FAILED, created_at__gte=timezone.now() - timedelta(hours=24)).count(),
            "shield-exclamation", "failed sign-in attempts in the last 24 hours",
            f"{reverse('adminpanel:audit_log')}?action=login_failed", "danger")
    return items
