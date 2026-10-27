"""Dashboard statistics. Every number is computed from database records."""
from datetime import date, time, timedelta

from django.db.models import Count, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone

from admissions.models import Admission
from admissions.services import occupancy_summary
from appointments.models import Appointment
from appointments.services import local_dt
from billing.models import ZERO, Invoice, Payment


def today_bounds():
    today = timezone.localdate()
    start = local_dt(today, time.min)
    return start, start + timedelta(days=1)


def month_starts(count: int) -> list[date]:
    first = timezone.localdate().replace(day=1)
    months = []
    for _ in range(count):
        months.append(first)
        first = (first - timedelta(days=1)).replace(day=1)
    return list(reversed(months))


def todays_collections():
    start, end = today_bounds()
    return Payment.objects.filter(paid_at__gte=start, paid_at__lt=end).aggregate(s=Sum("amount"))["s"] or ZERO


def pending_invoices():
    return Invoice.objects.filter(status__in=Invoice.OUTSTANDING_STATUSES).aggregate(
        count=Count("id"), total=Sum("total"), paid=Sum("amount_paid")
    )


def monthly_revenue(months: int = 6):
    starts = month_starts(months)
    since = local_dt(starts[0], time.min)
    rows = (
        Payment.objects.filter(paid_at__gte=since)
        .annotate(month=TruncMonth("paid_at", tzinfo=timezone.get_current_timezone()))
        .values("month")
        .annotate(total=Sum("amount"))
    )
    by_month = {(r["month"].year, r["month"].month): r["total"] for r in rows}
    # Floats are used only for chart rendering, never for financial arithmetic.
    values = [float(by_month.get((m.year, m.month), 0)) for m in starts]
    return {"labels": [m.strftime("%b %Y") for m in starts], "values": values, "has_data": any(values)}


def appointment_status_breakdown(appointments_qs, days: int = 30):
    since = timezone.now() - timedelta(days=days)
    counts = dict(
        appointments_qs.filter(start_at__gte=since).values_list("status").annotate(n=Count("id")).order_by()
    )
    return {
        "labels": [label for _, label in Appointment.Status.choices],
        "values": [counts.get(value, 0) for value, _ in Appointment.Status.choices],
        "total": sum(counts.values()),
    }


def bed_occupancy():
    data = occupancy_summary()
    data["chart"] = {
        "labels": ["Occupied", "Available", "Maintenance"],
        "values": [data["occupied"], data["available"], data["maintenance"]],
    }
    return data


def admission_movements(admissions_qs, limit: int = 5):
    return {
        "recent_admissions": admissions_qs.order_by("-admitted_at")[:limit],
        "recent_discharges": admissions_qs.filter(status=Admission.Status.DISCHARGED).order_by("-discharged_at")[:limit],
    }


def daily_appointments(appointments_qs, days: int = 14):
    today = timezone.localdate()
    days_list = [today - timedelta(days=i) for i in range(days - 1, -1, -1)]
    start = local_dt(days_list[0], time.min)
    counts = {}
    for start_at in appointments_qs.filter(start_at__gte=start, start_at__lt=local_dt(today, time.min) + timedelta(days=1)).values_list("start_at", flat=True):
        day = timezone.localtime(start_at).date()
        counts[day] = counts.get(day, 0) + 1
    return {"labels": [d.strftime("%d %b") for d in days_list], "values": [counts.get(d, 0) for d in days_list]}


def outstanding_balance():
    data = Invoice.objects.filter(status__in=Invoice.OUTSTANDING_STATUSES).aggregate(total=Sum("total"), paid=Sum("amount_paid"))
    return (data["total"] or ZERO) - (data["paid"] or ZERO)
