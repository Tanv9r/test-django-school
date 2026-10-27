from django.conf import settings
from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.generic import ListView

from accounts.permissions import CapabilityRequiredMixin, capability_required, has_capability
from core.audit import form_changes, log_action
from core.models import AuditLog

from .forms import PatientForm, PatientFilterForm
from .models import Patient
from .selectors import visible_patients


class PatientListView(CapabilityRequiredMixin, ListView):
    required_capability = "patients_view"
    template_name = "patients/patient_list.html"
    context_object_name = "patients"
    paginate_by = settings.HMS_PAGE_SIZE

    def get_queryset(self):
        self.filter_form = PatientFilterForm(self.request.GET or None)
        qs = visible_patients(self.request.user)
        status = "active"
        if self.filter_form.is_valid():
            data = self.filter_form.cleaned_data
            status = data.get("status") or "active"
            if q := data.get("q"):
                qs = qs.filter(
                    Q(first_name__icontains=q)
                    | Q(last_name__icontains=q)
                    | Q(patient_id__icontains=q)
                    | Q(phone__icontains=q)
                    | Q(email__icontains=q)
                )
            if data.get("gender"):
                qs = qs.filter(gender=data["gender"])
            if data.get("blood_group"):
                qs = qs.filter(blood_group=data["blood_group"])
        if status == "active":
            qs = qs.filter(is_active=True)
        elif status == "archived":
            qs = qs.filter(is_active=False)
        return qs.order_by("-created_at")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["filter_form"] = self.filter_form
        return context


def _get_visible_patient(request, pk):
    return get_object_or_404(visible_patients(request.user), pk=pk)


@capability_required("patients_view")
def patient_detail(request, pk):
    patient = _get_visible_patient(request, pk)
    user = request.user
    context = {"patient": patient, "show_clinical": has_capability(user, "patients_view_clinical")}
    if has_capability(user, "appointments_view"):
        context["appointments"] = patient.appointments.select_related("doctor", "department").order_by("-start_at")[:20]
    if has_capability(user, "admissions_view"):
        context["admissions"] = patient.admissions.select_related("bed__room", "attending_doctor").order_by("-admitted_at")
    if has_capability(user, "records_view"):
        context["records"] = patient.medical_records.select_related("doctor").order_by("-visit_date")
    if has_capability(user, "prescriptions_view"):
        context["prescriptions"] = patient.prescriptions.select_related("doctor").prefetch_related("items").order_by("-created_at")
    if has_capability(user, "billing_view"):
        context["invoices"] = patient.invoices.order_by("-issue_date", "-pk")[:20]
    return render(request, "patients/patient_detail.html", context)


@capability_required("patients_manage")
def patient_create(request):
    form = PatientForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        patient = form.save(commit=False)
        patient.registered_by = request.user
        patient.save()
        log_action(request.user, AuditLog.Action.CREATE, patient, "Patient registered", request=request)
        messages.success(request, f"Patient {patient.full_name} registered with ID {patient.patient_id}.")
        return redirect("patients:detail", pk=patient.pk)
    return render(request, "patients/patient_form.html", {"form": form})


@capability_required("patients_manage")
def patient_edit(request, pk):
    patient = _get_visible_patient(request, pk)
    form = PatientForm(request.POST or None, instance=patient)
    if request.method == "POST" and form.is_valid():
        changes = form_changes(form)
        form.save()
        log_action(request.user, AuditLog.Action.UPDATE, patient, "Patient details updated", changes, request)
        messages.success(request, "Patient details updated.")
        return redirect("patients:detail", pk=patient.pk)
    return render(request, "patients/patient_form.html", {"form": form, "patient": patient})


@require_POST
@capability_required("patients_manage")
def patient_toggle_archive(request, pk):
    patient = _get_visible_patient(request, pk)
    if patient.is_active:
        if patient.admissions.filter(status="admitted").exists():
            messages.error(request, "This patient is currently admitted and cannot be archived until discharge.")
            return redirect("patients:detail", pk=patient.pk)
        patient.is_active = False
        patient.archived_at = timezone.now()
        action, text = AuditLog.Action.ARCHIVE, "archived"
    else:
        patient.is_active = True
        patient.archived_at = None
        action, text = AuditLog.Action.RESTORE, "restored"
    patient.save(update_fields=["is_active", "archived_at", "updated_at"])
    log_action(request.user, action, patient, f"Patient {text}", request=request)
    messages.success(request, f"Patient record {text}.")
    return redirect("patients:detail", pk=patient.pk)
