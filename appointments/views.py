import calendar
from collections import defaultdict
from datetime import date, datetime, time, timedelta

from django.conf import settings
from django.contrib import messages
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from django.views.generic import ListView

from accounts.models import Role
from accounts.permissions import CapabilityRequiredMixin, capability_required, has_capability
from core.audit import form_changes, log_action
from core.models import AuditLog
from doctors.models import Doctor
from patients.models import Patient

from . import services
from .forms import AppointmentFilterForm, AppointmentForm, StatusChangeForm
from .models import Appointment


def visible_appointments(user):
    qs = Appointment.objects.select_related("patient", "doctor", "department")
    if not has_capability(user, "appointments_view"):
        return qs.none()
    if user.effective_role == Role.DOCTOR:
        doctor = getattr(user, "doctor_profile", None)
        return qs.filter(doctor=doctor) if doctor else qs.none()
    return qs


def _local_day_bounds(day_from, day_to):
    start = services.local_dt(day_from, time.min)
    end = services.local_dt(day_to, time.min) + timedelta(days=1)
    return start, end


class AppointmentListView(CapabilityRequiredMixin, ListView):
    required_capability = "appointments_view"
    template_name = "appointments/appointment_list.html"
    context_object_name = "appointments"
    paginate_by = settings.HMS_PAGE_SIZE

    def get_queryset(self):
        self.filter_form = AppointmentFilterForm(self.request.GET or None)
        qs = visible_appointments(self.request.user)
        self.scope = self.request.GET.get("scope", "upcoming")
        today = timezone.localdate()
        if self.filter_form.is_valid():
            data = self.filter_form.cleaned_data
            if q := data.get("q"):
                qs = qs.filter(
                    Q(patient__first_name__icontains=q)
                    | Q(patient__last_name__icontains=q)
                    | Q(patient__patient_id__icontains=q)
                    | Q(reference__icontains=q)
                )
            for field in ("doctor", "department", "status"):
                if data.get(field):
                    qs = qs.filter(**{field: data[field]})
            if data.get("date_from") or data.get("date_to"):
                self.scope = "range"
                start, end = _local_day_bounds(data.get("date_from") or date(2000, 1, 1), data.get("date_to") or date(2100, 1, 1))
                qs = qs.filter(start_at__gte=start, start_at__lt=end)
        if self.scope == "today":
            start, end = _local_day_bounds(today, today)
            qs = qs.filter(start_at__gte=start, start_at__lt=end).order_by("start_at")
        elif self.scope == "upcoming":
            qs = qs.filter(start_at__gte=timezone.now()).order_by("start_at")
        elif self.scope == "past":
            qs = qs.filter(start_at__lt=timezone.now()).order_by("-start_at")
        else:
            qs = qs.order_by("-start_at")
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["filter_form"] = self.filter_form
        context["scope"] = self.scope
        return context


@capability_required("appointments_view")
def appointment_calendar(request):
    today = timezone.localdate()
    try:
        year = int(request.GET.get("year", today.year))
        month = int(request.GET.get("month", today.month))
        current = date(year, month, 1)
    except ValueError:
        current = today.replace(day=1)
    qs = visible_appointments(request.user).exclude(status=Appointment.Status.CANCELLED)
    doctor_id = request.GET.get("doctor")
    if doctor_id and doctor_id.isdigit():
        qs = qs.filter(doctor_id=int(doctor_id))
    weeks = calendar.Calendar(firstweekday=0).monthdatescalendar(current.year, current.month)
    start, end = _local_day_bounds(weeks[0][0], weeks[-1][-1])
    by_day = defaultdict(list)
    for appt in qs.filter(start_at__gte=start, start_at__lt=end).order_by("start_at"):
        by_day[timezone.localtime(appt.start_at).date()].append(appt)
    prev_month = (current - timedelta(days=1)).replace(day=1)
    next_month = (current + timedelta(days=32)).replace(day=1)
    context = {
        "current": current,
        "today": today,
        "weeks": [[(day, by_day.get(day, [])) for day in week] for week in weeks],
        "prev_month": prev_month,
        "next_month": next_month,
        "doctors": Doctor.objects.filter(is_active=True) if request.user.effective_role != Role.DOCTOR else [],
        "selected_doctor": doctor_id or "",
        "weekday_names": [calendar.day_abbr[i] for i in range(7)],
    }
    return render(request, "appointments/appointment_calendar.html", context)


@capability_required("appointments_manage")
def appointment_create(request):
    initial = {}
    if (patient_pk := request.GET.get("patient", "")).isdigit():
        initial["patient"] = Patient.objects.filter(pk=int(patient_pk), is_active=True).first()
    if (doctor_pk := request.GET.get("doctor", "")).isdigit():
        initial["doctor"] = Doctor.objects.filter(pk=int(doctor_pk), is_active=True).first()
    form = AppointmentForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        try:
            appointment = services.save_appointment(form.save(commit=False), request.user)
        except services.SchedulingError as exc:
            form.add_error(None, str(exc))
        else:
            log_action(request.user, AuditLog.Action.CREATE, appointment, "Appointment booked", request=request)
            local = timezone.localtime(appointment.start_at)
            messages.success(request, f"Appointment {appointment.reference} booked for {local:%d %b %Y at %H:%M}.")
            return redirect("appointments:detail", pk=appointment.pk)
    return render(request, "appointments/appointment_form.html", {"form": form})


@capability_required("appointments_manage")
def appointment_edit(request, pk):
    appointment = get_object_or_404(visible_appointments(request.user), pk=pk)
    if not appointment.is_open:
        messages.error(request, "Only scheduled or confirmed appointments can be rescheduled.")
        return redirect("appointments:detail", pk=pk)
    old_start = appointment.start_at
    form = AppointmentForm(request.POST or None, instance=appointment)
    if request.method == "POST" and form.is_valid():
        changes = form_changes(form)
        try:
            appointment = services.save_appointment(form.save(commit=False))
        except services.SchedulingError as exc:
            form.add_error(None, str(exc))
        else:
            if appointment.start_at != old_start:
                changes["start_at"] = [
                    f"{timezone.localtime(old_start):%Y-%m-%d %H:%M}",
                    f"{timezone.localtime(appointment.start_at):%Y-%m-%d %H:%M}",
                ]
            log_action(request.user, AuditLog.Action.UPDATE, appointment, "Appointment updated", changes, request)
            messages.success(request, "Appointment updated.")
            return redirect("appointments:detail", pk=appointment.pk)
    return render(request, "appointments/appointment_form.html", {"form": form, "appointment": appointment})


@capability_required("appointments_view")
def appointment_detail(request, pk):
    appointment = get_object_or_404(visible_appointments(request.user), pk=pk)
    context = {
        "appointment": appointment,
        "status_form": StatusChangeForm(),
        "can_change_status": has_capability(request.user, "appointments_change_status"),
        "records": appointment.medical_records.all() if has_capability(request.user, "records_view") else None,
    }
    return render(request, "appointments/appointment_detail.html", context)


@require_POST
@capability_required("appointments_change_status")
def appointment_change_status(request, pk):
    appointment = get_object_or_404(visible_appointments(request.user), pk=pk)
    form = StatusChangeForm(request.POST)
    if form.is_valid():
        old = appointment.get_status_display()
        try:
            services.change_status(appointment, form.cleaned_data["status"], form.cleaned_data.get("reason", ""))
        except services.SchedulingError as exc:
            messages.error(request, str(exc))
        else:
            log_action(
                request.user,
                AuditLog.Action.STATUS,
                appointment,
                f"Status changed from {old} to {appointment.get_status_display()}",
                {"status": [old, appointment.get_status_display()]},
                request,
            )
            messages.success(request, f"Appointment marked as {appointment.get_status_display().lower()}.")
    else:
        for errors in form.errors.values():
            messages.error(request, " ".join(errors))
    return redirect("appointments:detail", pk=appointment.pk)


@require_GET
@capability_required("appointments_manage")
def available_slots_api(request):
    try:
        doctor = Doctor.objects.get(pk=int(request.GET.get("doctor", "")), is_active=True)
        day = datetime.strptime(request.GET.get("date", ""), "%Y-%m-%d").date()
    except (ValueError, Doctor.DoesNotExist):
        return JsonResponse({"error": "Choose a doctor and a valid date."}, status=400)
    exclude = request.GET.get("exclude")
    slots = services.available_slots(doctor, day, exclude_pk=int(exclude) if exclude and exclude.isdigit() else None)
    windows = [str(w) for w in doctor.availability.filter(weekday=day.weekday())]
    return JsonResponse(
        {
            "doctor": str(doctor),
            "slot_minutes": doctor.slot_minutes,
            "working_hours": windows,
            "slots": [timezone.localtime(s).strftime("%H:%M") for s in slots],
        }
    )
