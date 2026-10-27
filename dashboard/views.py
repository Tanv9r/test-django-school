from django.db.models import Q
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role
from accounts.permissions import has_capability
from admissions.models import Admission, NursingTask
from admissions.views import visible_admissions
from appointments.models import Appointment
from appointments.views import visible_appointments
from billing.models import Invoice
from core.models import HospitalSettings
from doctors.models import Doctor
from medical_records.models import Prescription
from patients.selectors import visible_patients
from pharmacy.models import Medicine
from staff.models import StaffProfile

from . import stats


def home(request):
    if not request.user.is_authenticated:
        return redirect("accounts:login")
    if has_capability(request.user, "adminpanel_access"):
        return redirect("adminpanel:overview")
    return redirect("dashboard:index")


def _card(label, value, icon, color, url=None, hint="", is_money=False):
    return {"label": label, "value": value, "icon": icon, "color": color, "url": url, "hint": hint, "is_money": is_money}


def index(request):
    user = request.user
    can = lambda cap: has_capability(user, cap)  # noqa: E731
    role = user.effective_role
    start, end = stats.today_bounds()
    cards, context = [], {}

    if can("patients_view"):
        patients = visible_patients(user, include_archived=False)
        label = "Registered patients" if can("patients_view_all") else "My patients"
        cards.append(_card(label, patients.count(), "people", "primary", reverse("patients:list")))
        context["recent_patients"] = patients.order_by("-created_at")[:5]
    if can("doctors_view"):
        cards.append(_card("Active doctors", Doctor.objects.filter(is_active=True).count(), "person-badge", "info", reverse("doctors:list")))
    if can("appointments_view"):
        appointments = visible_appointments(user)
        today_count = appointments.filter(start_at__gte=start, start_at__lt=end).exclude(status=Appointment.Status.CANCELLED).count()
        cards.append(_card("Today's appointments", today_count, "calendar-check", "success", f"{reverse('appointments:list')}?scope=today"))
        context["upcoming_appointments"] = appointments.filter(
            start_at__gte=timezone.now(), status__in=Appointment.OPEN_STATUSES
        ).order_by("start_at")[:6]
        context["appointment_chart"] = stats.appointment_status_breakdown(appointments)
    if can("admissions_view"):
        admissions = visible_admissions(user)
        cards.append(_card("Currently admitted", admissions.filter(status=Admission.Status.ADMITTED).count(), "hospital", "warning", reverse("admissions:list")))
        context.update(stats.admission_movements(admissions))
    if can("beds_view"):
        occupancy = stats.bed_occupancy()
        cards.append(_card("Available beds", occupancy["available"], "door-open", "success", reverse("admissions:bed_board"), f"{occupancy['occupancy_rate']}% occupancy"))
        context["occupancy"] = occupancy
    if can("billing_view"):
        pending = stats.pending_invoices()
        cards.append(_card("Pending invoices", pending["count"], "receipt", "danger", f"{reverse('billing:invoice_list')}?status=unpaid"))
        cards.append(_card("Collected today", stats.todays_collections(), "cash-coin", "success", reverse("billing:payment_list"), is_money=True))
        context["revenue_chart"] = stats.monthly_revenue()
    if can("pharmacy_view"):
        days = HospitalSettings.load().expiry_warning_days
        cards.append(_card("Low-stock medicines", Medicine.objects.low_stock().count(), "box-seam", "warning", f"{reverse('pharmacy:list')}?stock=low"))
        cards.append(_card("Expiring soon", Medicine.objects.expiring_within(days).count(), "calendar-x", "danger", f"{reverse('pharmacy:list')}?stock=expiring", f"within {days} days"))
    if can("prescriptions_dispense"):
        cards.append(_card("Awaiting dispensing", Prescription.objects.filter(status=Prescription.Status.ACTIVE).count(), "capsule", "primary", reverse("records:prescription_list")))
        context["dispense_queue"] = Prescription.objects.filter(status=Prescription.Status.ACTIVE).select_related("patient", "doctor")[:6]
    if role == Role.NURSE:
        tasks = NursingTask.objects.filter(Q(assigned_to=user) | Q(admission__assigned_nurse=user), admission__status="admitted").exclude(status="done")
        cards.append(_card("My open tasks", tasks.count(), "clipboard2-pulse", "info", reverse("admissions:tasks")))
        context["my_tasks"] = tasks.select_related("admission__patient", "admission__bed__room")[:6]

    quick_actions = [
        (can("patients_manage"), "Register patient", "person-plus", reverse("patients:create")),
        (can("appointments_manage"), "Book appointment", "calendar-plus", reverse("appointments:create")),
        (can("admissions_manage"), "Admit patient", "hospital", reverse("admissions:create")),
        (can("records_manage"), "New medical record", "journal-medical", reverse("records:create")),
        (can("prescriptions_manage"), "Write prescription", "prescription2", reverse("records:prescription_create")),
        (can("billing_manage"), "Create invoice", "receipt-cutoff", reverse("billing:invoice_create")),
        (can("pharmacy_manage"), "Add medicine", "capsule-pill", reverse("pharmacy:create")),
        (can("nursing_view"), "Nursing tasks", "clipboard2-pulse", reverse("admissions:tasks")),
        (can("reports_operational") or can("reports_financial") or can("reports_pharmacy"), "View reports", "graph-up", reverse("dashboard:reports")),
    ]
    context.update(
        cards=cards,
        quick_actions=[{"label": label, "icon": icon, "url": url} for allowed, label, icon, url in quick_actions if allowed],
        greeting=_greeting(),
        today=timezone.localdate(),
    )
    return render(request, "dashboard/index.html", context)


def _greeting():
    hour = timezone.localtime().hour
    return "Good morning" if hour < 12 else "Good afternoon" if hour < 17 else "Good evening"


def search(request):
    q = request.GET.get("q", "").strip()
    user = request.user
    results = []
    if len(q) >= 2:
        if has_capability(user, "patients_view"):
            patients = visible_patients(user).filter(
                Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(patient_id__icontains=q) | Q(phone__icontains=q)
            )[:8]
            results.append(("Patients", "people", [(p.full_name, f"{p.patient_id} · {p.phone}", reverse("patients:detail", args=[p.pk])) for p in patients]))
        if has_capability(user, "doctors_view"):
            doctors = Doctor.objects.filter(
                Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(specialization__icontains=q) | Q(doctor_code__icontains=q)
            ).select_related("department")[:8]
            results.append(("Doctors", "person-badge", [(str(d), f"{d.specialization} · {d.department}", reverse("doctors:detail", args=[d.pk])) for d in doctors]))
        if has_capability(user, "appointments_view"):
            appts = visible_appointments(user).filter(Q(reference__icontains=q) | Q(patient__last_name__icontains=q) | Q(patient__first_name__icontains=q)).order_by("-start_at")[:8]
            results.append(("Appointments", "calendar-check", [(a.reference, f"{a.patient.full_name} · {timezone.localtime(a.start_at):%d %b %Y %H:%M}", reverse("appointments:detail", args=[a.pk])) for a in appts]))
        if has_capability(user, "billing_view"):
            invoices = Invoice.objects.filter(Q(invoice_number__icontains=q) | Q(patient__last_name__icontains=q) | Q(patient__first_name__icontains=q)).select_related("patient")[:8]
            results.append(("Invoices", "receipt", [(i.invoice_number, f"{i.patient.full_name} · {i.get_status_display()}", reverse("billing:invoice_detail", args=[i.pk])) for i in invoices]))
        if has_capability(user, "pharmacy_view"):
            meds = Medicine.objects.filter(Q(name__icontains=q) | Q(generic_name__icontains=q) | Q(batch_number__icontains=q))[:8]
            results.append(("Medicines", "capsule", [(m.name, f"Batch {m.batch_number} · {m.quantity} {m.unit}", reverse("pharmacy:detail", args=[m.pk])) for m in meds]))
        if has_capability(user, "staff_view"):
            members = StaffProfile.objects.filter(Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(employee_id__icontains=q) | Q(job_title__icontains=q))[:8]
            results.append(("Staff", "person-vcard", [(m.full_name, f"{m.employee_id} · {m.job_title}", reverse("staff:detail", args=[m.pk])) for m in members]))
    results = [group for group in results if group[2]]
    return render(request, "dashboard/search.html", {"q": q, "results": results, "too_short": 0 < len(q) < 2})
