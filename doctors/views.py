from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.generic import DetailView, ListView

from accounts.permissions import CapabilityRequiredMixin, capability_required, has_capability
from core.audit import form_changes, log_action
from core.models import AuditLog

from .forms import AvailabilityFormSet, DoctorFilterForm, DoctorForm
from .models import Department, Doctor


class DoctorListView(CapabilityRequiredMixin, ListView):
    required_capability = "doctors_view"
    template_name = "doctors/doctor_list.html"
    context_object_name = "doctors"
    paginate_by = settings.HMS_PAGE_SIZE

    def get_queryset(self):
        self.filter_form = DoctorFilterForm(self.request.GET or None)
        qs = Doctor.objects.select_related("department", "user")
        status = "active"
        if self.filter_form.is_valid():
            data = self.filter_form.cleaned_data
            status = data.get("status") or "active"
            if q := data.get("q"):
                qs = qs.filter(
                    Q(first_name__icontains=q)
                    | Q(last_name__icontains=q)
                    | Q(doctor_code__icontains=q)
                    | Q(specialization__icontains=q)
                )
            if data.get("department"):
                qs = qs.filter(department=data["department"])
        if status == "active":
            qs = qs.filter(is_active=True)
        elif status == "inactive":
            qs = qs.filter(is_active=False)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["filter_form"] = self.filter_form
        return context


class DoctorDetailView(CapabilityRequiredMixin, DetailView):
    required_capability = "doctors_view"
    model = Doctor
    template_name = "doctors/doctor_detail.html"
    context_object_name = "doctor"

    def get_queryset(self):
        return Doctor.objects.select_related("department", "user").prefetch_related("availability")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        doctor = self.object
        user = self.request.user
        can_see_schedule = has_capability(user, "appointments_view") and (
            has_capability(user, "appointments_manage") or getattr(user, "doctor_profile", None) == doctor
        )
        if can_see_schedule:
            context["upcoming_appointments"] = (
                doctor.appointments.filter(start_at__gte=timezone.now(), status__in=["scheduled", "confirmed"])
                .select_related("patient")
                .order_by("start_at")[:8]
            )
        context["can_see_schedule"] = can_see_schedule
        context["stats"] = doctor.appointments.aggregate(
            total=Count("id"),
            completed=Count("id", filter=Q(status="completed")),
            upcoming=Count("id", filter=Q(status__in=["scheduled", "confirmed"], start_at__gte=timezone.now())),
        )
        return context


@capability_required("doctors_manage")
def doctor_form(request, pk=None):
    doctor = get_object_or_404(Doctor, pk=pk) if pk else Doctor()
    form = DoctorForm(request.POST or None, instance=doctor)
    formset = AvailabilityFormSet(request.POST or None, instance=doctor, prefix="availability")
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        changes = form_changes(form) if pk else {}
        with transaction.atomic():
            doctor = form.save()
            formset.instance = doctor
            formset.save()
        action = AuditLog.Action.UPDATE if pk else AuditLog.Action.CREATE
        log_action(request.user, action, doctor, "Doctor profile saved", changes, request)
        messages.success(request, f"{doctor} has been {'updated' if pk else 'registered'}.")
        return redirect("doctors:detail", pk=doctor.pk)
    return render(request, "doctors/doctor_form.html", {"form": form, "formset": formset, "doctor": doctor if pk else None})


@require_POST
@capability_required("doctors_manage")
def doctor_toggle_active(request, pk):
    doctor = get_object_or_404(Doctor, pk=pk)
    doctor.is_active = not doctor.is_active
    doctor.save(update_fields=["is_active", "updated_at"])
    state = "activated" if doctor.is_active else "deactivated"
    log_action(request.user, AuditLog.Action.STATUS, doctor, f"Doctor {state}", request=request)
    messages.success(request, f"{doctor} has been {state}.")
    return redirect("doctors:detail", pk=doctor.pk)


class DepartmentListView(CapabilityRequiredMixin, ListView):
    required_capability = "departments_view"
    template_name = "doctors/department_list.html"
    context_object_name = "departments"

    def get_queryset(self):
        qs = Department.objects.annotate(doctor_count=Count("doctors", filter=Q(doctors__is_active=True)))
        if not self.request.GET.get("show") == "all":
            qs = qs.filter(is_active=True)
        return qs


class DepartmentDetailView(CapabilityRequiredMixin, DetailView):
    required_capability = "departments_view"
    model = Department
    template_name = "doctors/department_detail.html"
    context_object_name = "department"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["doctors"] = self.object.doctors.filter(is_active=True)
        context["upcoming_count"] = self.object.appointments.filter(
            start_at__gte=timezone.now(), status__in=["scheduled", "confirmed"]
        ).count()
        return context
