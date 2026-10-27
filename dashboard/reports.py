"""Reports: each builder returns columns/rows/summary for a date range.

The same structure drives the HTML table, the print layout and CSV export.
"""
import csv
from dataclasses import dataclass
from datetime import time, timedelta
from typing import Callable

from django.db.models import Count, F, Q, Sum
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone

from accounts.permissions import has_capability, require_capability
from admissions.models import Admission, Bed
from admissions.views import visible_admissions
from appointments.models import Appointment
from appointments.services import local_dt
from appointments.views import visible_appointments
from billing.models import ZERO, Invoice, Payment
from core.forms import DateRangeForm
from core.models import HospitalSettings
from doctors.models import Doctor
from patients.selectors import visible_patients
from pharmacy.models import Medicine


def _fmt_dt(value):
    return timezone.localtime(value).strftime("%Y-%m-%d %H:%M") if value else ""


def _money(value):
    return f"{(value or ZERO):,.2f}"


def patients_report(user, start, end):
    qs = visible_patients(user).filter(created_at__gte=start, created_at__lt=end).order_by("created_at")
    gender = dict(qs.values_list("gender").annotate(n=Count("id")).order_by())
    rows = [(p.patient_id, p.full_name, p.get_gender_display(), p.age, p.blood_group, p.phone, _fmt_dt(p.created_at)) for p in qs]
    return {
        "columns": ["Patient ID", "Name", "Gender", "Age", "Blood group", "Phone", "Registered"],
        "rows": rows,
        "summary": [("New registrations", len(rows)), ("Female", gender.get("F", 0)), ("Male", gender.get("M", 0)), ("Other", gender.get("O", 0))],
    }


def appointments_report(user, start, end):
    qs = visible_appointments(user).filter(start_at__gte=start, start_at__lt=end).order_by("start_at")
    by_status = dict(qs.values_list("status").annotate(n=Count("id")).order_by())
    by_dept = list(qs.values("department__name").annotate(n=Count("id")).order_by("-n"))
    rows = [
        (a.reference, _fmt_dt(a.start_at), a.patient.full_name, str(a.doctor), a.department.name, a.get_status_display())
        for a in qs
    ]
    return {
        "columns": ["Reference", "Date & time", "Patient", "Doctor", "Department", "Status"],
        "rows": rows,
        "summary": [("Total", len(rows))] + [(label, by_status.get(value, 0)) for value, label in Appointment.Status.choices],
        "chart": {"type": "bar", "label": "Appointments by department", "labels": [d["department__name"] for d in by_dept], "values": [d["n"] for d in by_dept]},
    }


def workload_report(user, start, end):
    period = Q(appointments__start_at__gte=start, appointments__start_at__lt=end)
    doctors = Doctor.objects.select_related("department").annotate(
        total=Count("appointments", filter=period, distinct=True),
        completed=Count("appointments", filter=period & Q(appointments__status="completed"), distinct=True),
        cancelled=Count("appointments", filter=period & Q(appointments__status="cancelled"), distinct=True),
        no_show=Count("appointments", filter=period & Q(appointments__status="no_show"), distinct=True),
    ).order_by("-total")
    admissions = dict(
        Admission.objects.filter(admitted_at__gte=start, admitted_at__lt=end)
        .values_list("attending_doctor").annotate(n=Count("id")).order_by()
    )
    rows = [
        (str(d), d.department.name, d.total, d.completed, d.cancelled, d.no_show, admissions.get(d.pk, 0))
        for d in doctors
    ]
    return {
        "columns": ["Doctor", "Department", "Appointments", "Completed", "Cancelled", "No-show", "Admissions"],
        "rows": rows,
        "summary": [("Doctors", len(rows)), ("Appointments", sum(r[2] for r in rows)), ("Admissions", sum(r[6] for r in rows))],
        "chart": {"type": "bar", "label": "Appointments per doctor", "labels": [r[0] for r in rows[:12]], "values": [r[2] for r in rows[:12]]},
    }


def admissions_report(user, start, end):
    qs = visible_admissions(user)
    admitted = qs.filter(admitted_at__gte=start, admitted_at__lt=end)
    discharged = qs.filter(discharged_at__gte=start, discharged_at__lt=end)
    events = sorted(
        [(a.admitted_at, "Admitted", a) for a in admitted] + [(a.discharged_at, "Discharged", a) for a in discharged],
        key=lambda e: e[0],
    )
    rows = [
        (_fmt_dt(when), kind, a.admission_number, a.patient.full_name, a.bed.label, str(a.attending_doctor), a.length_of_stay_days if a.discharged_at else "")
        for when, kind, a in events
    ]
    stays = [a.length_of_stay_days for a in discharged]
    return {
        "columns": ["When", "Event", "Admission", "Patient", "Bed", "Attending doctor", "Stay (days)"],
        "rows": rows,
        "summary": [
            ("Admissions", admitted.count()),
            ("Discharges", discharged.count()),
            ("Average stay (days)", round(sum(stays) / len(stays), 1) if stays else "—"),
            ("Currently admitted", qs.filter(status=Admission.Status.ADMITTED).count()),
        ],
    }


def occupancy_report(user, start, end):
    rows_qs = (
        Bed.objects.filter(room__is_active=True)
        .values("room__room_type__name")
        .annotate(
            total=Count("id"),
            occupied=Count("id", filter=Q(status=Bed.Status.OCCUPIED)),
            available=Count("id", filter=Q(status=Bed.Status.AVAILABLE)),
            maintenance=Count("id", filter=Q(status=Bed.Status.MAINTENANCE)),
        )
        .order_by("room__room_type__name")
    )
    rows = []
    for r in rows_qs:
        usable = r["total"] - r["maintenance"]
        rate = f"{round(r['occupied'] * 100 / usable)}%" if usable else "—"
        rows.append((r["room__room_type__name"], r["total"], r["occupied"], r["available"], r["maintenance"], rate))
    total = sum(r[1] for r in rows)
    occupied = sum(r[2] for r in rows)
    maintenance = sum(r[4] for r in rows)
    bed_days = Admission.objects.filter(admitted_at__lt=end).filter(Q(discharged_at__isnull=True) | Q(discharged_at__gte=start)).count()
    return {
        "columns": ["Room type", "Beds", "Occupied", "Available", "Maintenance", "Occupancy"],
        "rows": rows,
        "summary": [
            ("Total beds", total),
            ("Occupied now", occupied),
            ("Occupancy now", f"{round(occupied * 100 / (total - maintenance))}%" if total - maintenance else "—"),
            ("Stays overlapping period", bed_days),
        ],
        "chart": {"type": "bar", "label": "Occupied beds by room type", "labels": [r[0] for r in rows], "values": [r[2] for r in rows]},
        "snapshot": True,
    }


def stock_report(user, start, end):
    days = HospitalSettings.load().expiry_warning_days
    today = timezone.localdate()
    meds = Medicine.objects.filter(is_active=True).select_related("category").order_by("name")
    rows = []
    for m in meds:
        if m.quantity == 0:
            status = "Out of stock"
        elif m.expiry_date < today:
            status = "Expired"
        elif m.expiry_date <= today + timedelta(days=days):
            status = "Expiring soon"
        elif m.is_low_stock:
            status = "Low stock"
        else:
            status = "OK"
        rows.append((m.name, m.category.name, m.batch_number, m.quantity, m.reorder_level, m.expiry_date.isoformat(), _money(m.stock_value), status))
    value = meds.aggregate(v=Sum(F("quantity") * F("unit_price")))["v"] or ZERO
    dispensed = Medicine.objects.filter(transactions__transaction_type="dispense", transactions__created_at__gte=start, transactions__created_at__lt=end).aggregate(n=Sum("transactions__quantity_change"))["n"] or 0
    return {
        "columns": ["Medicine", "Category", "Batch", "Quantity", "Reorder level", "Expiry", "Stock value", "Status"],
        "rows": rows,
        "summary": [
            ("Active items", len(rows)),
            ("Stock value", _money(value)),
            ("Low / out of stock", meds.low_stock().count()),
            ("Units dispensed in period", abs(dispensed)),
        ],
        "snapshot": True,
    }


def revenue_report(user, start, end):
    payments = Payment.objects.filter(paid_at__gte=start, paid_at__lt=end)
    by_method = list(payments.values("method__name").annotate(total=Sum("amount"), n=Count("id")).order_by("-total"))
    by_day = {}
    for p in payments.only("paid_at", "amount"):
        day = timezone.localtime(p.paid_at).date()
        count, amount = by_day.get(day, (0, ZERO))
        by_day[day] = (count + 1, amount + p.amount)
    rows = [(day.isoformat(), count, _money(amount)) for day, (count, amount) in sorted(by_day.items())]
    billed = Invoice.objects.filter(issue_date__gte=timezone.localtime(start).date(), issue_date__lt=timezone.localtime(end).date()).exclude(status=Invoice.Status.CANCELLED).aggregate(s=Sum("total"))["s"] or ZERO
    total = payments.aggregate(s=Sum("amount"))["s"] or ZERO
    return {
        "columns": ["Date", "Payments", "Amount collected"],
        "rows": rows,
        "summary": [("Collected", _money(total)), ("Invoiced in period", _money(billed)), ("Payments", payments.count())]
        + [(f"via {m['method__name']}", _money(m["total"])) for m in by_method],
        "chart": {"type": "line", "label": "Collections per day", "labels": [r[0] for r in rows], "values": [float(by_day[d][1]) for d in sorted(by_day)]},
    }


def outstanding_report(user, start, end):
    today = timezone.localdate()
    qs = Invoice.objects.filter(
        status__in=Invoice.OUTSTANDING_STATUSES,
        issue_date__gte=timezone.localtime(start).date(),
        issue_date__lt=timezone.localtime(end).date(),
    ).select_related("patient").order_by("issue_date")
    rows, total, overdue = [], ZERO, 0
    for inv in qs:
        days_overdue = (today - inv.due_date).days if inv.due_date and inv.due_date < today else 0
        overdue += 1 if days_overdue else 0
        total += inv.balance_due
        rows.append((inv.invoice_number, inv.patient.full_name, inv.issue_date.isoformat(), inv.due_date.isoformat() if inv.due_date else "", _money(inv.total), _money(inv.amount_paid), _money(inv.balance_due), days_overdue or ""))
    return {
        "columns": ["Invoice", "Patient", "Issued", "Due", "Total", "Paid", "Balance", "Days overdue"],
        "rows": rows,
        "summary": [("Outstanding invoices", len(rows)), ("Outstanding balance", _money(total)), ("Overdue", overdue)],
    }


@dataclass(frozen=True)
class Report:
    slug: str
    title: str
    description: str
    icon: str
    capability: str
    builder: Callable


REPORTS = {
    r.slug: r
    for r in [
        Report("patients", "Patient registrations", "New patients registered in the period.", "people", "reports_operational", patients_report),
        Report("appointments", "Appointments", "Appointments by status and department.", "calendar-check", "reports_operational", appointments_report),
        Report("doctor-workload", "Doctor workload", "Appointments and admissions per doctor.", "person-badge", "reports_clinical", workload_report),
        Report("admissions", "Admissions & discharges", "Patient movements and length of stay.", "hospital", "reports_clinical", admissions_report),
        Report("bed-occupancy", "Bed occupancy", "Current bed usage by room type.", "door-open", "reports_operational", occupancy_report),
        Report("medicine-stock", "Medicine stock", "Inventory levels, value and expiry.", "capsule", "reports_pharmacy", stock_report),
        Report("revenue", "Revenue & payments", "Collections by day and payment method.", "cash-coin", "reports_financial", revenue_report),
        Report("outstanding", "Outstanding invoices", "Unpaid balances and overdue invoices.", "receipt", "reports_financial", outstanding_report),
    ]
}

REPORT_CAPABILITIES = ("reports_operational", "reports_clinical", "reports_pharmacy", "reports_financial")


def report_index(request):
    require_capability(request.user, *REPORT_CAPABILITIES)
    reports = [r for r in REPORTS.values() if has_capability(request.user, r.capability)]
    return render(request, "dashboard/report_index.html", {"reports": reports})


def _csv_safe(value):
    text = str(value)
    # Prevent spreadsheet formula injection from user-entered text.
    return f"'{text}" if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def report_detail(request, slug):
    report = REPORTS.get(slug)
    if report is None:
        raise Http404
    require_capability(request.user, report.capability)
    today = timezone.localdate()
    form = DateRangeForm(request.GET or None, initial={"date_from": today - timedelta(days=29), "date_to": today})
    date_from, date_to = today - timedelta(days=29), today
    if form.is_valid():
        date_from = form.cleaned_data.get("date_from") or date_from
        date_to = form.cleaned_data.get("date_to") or date_to
    start, end = local_dt(date_from, time.min), local_dt(date_to, time.min) + timedelta(days=1)
    data = report.builder(request.user, start, end)

    if request.GET.get("export") == "csv":
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="{slug}-{date_from}-{date_to}.csv"'
        writer = csv.writer(response)
        writer.writerow([report.title, f"{date_from} to {date_to}"])
        writer.writerow([])
        writer.writerow(data["columns"])
        for row in data["rows"]:
            writer.writerow([_csv_safe(cell) for cell in row])
        return response

    query = request.GET.copy()
    query["export"] = "csv"
    context = {
        "report": report,
        "data": data,
        "form": form,
        "date_from": date_from,
        "date_to": date_to,
        "csv_url": f"{reverse('dashboard:report_detail', args=[slug])}?{query.urlencode()}",
        "generated_at": timezone.now(),
    }
    return render(request, "dashboard/report_detail.html", context)
