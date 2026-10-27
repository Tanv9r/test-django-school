from datetime import time, timedelta

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.generic import ListView

from accounts.permissions import CapabilityRequiredMixin, capability_required, doctor_profile_for, has_capability
from appointments.services import local_dt
from core.audit import form_changes, history_for, log_action
from core.models import AuditLog
from patients.selectors import visible_patients
from pharmacy.services import StockError

from .forms import MedicalRecordForm, PrescriptionForm, PrescriptionItemFormSet, RecordFilterForm
from .models import MedicalRecord, Prescription
from .services import dispense_prescription, visible_prescriptions, visible_records


def _require_doctor_profile(request):
    doctor = doctor_profile_for(request.user)
    if doctor is None:
        messages.error(request, "Your login is not linked to a doctor profile. Ask an administrator to link it.")
        raise PermissionDenied
    return doctor


class RecordListView(CapabilityRequiredMixin, ListView):
    required_capability = "records_view"
    template_name = "medical_records/record_list.html"
    context_object_name = "records"
    paginate_by = settings.HMS_PAGE_SIZE

    def get_queryset(self):
        self.filter_form = RecordFilterForm(self.request.GET or None)
        qs = visible_records(self.request.user)
        if self.filter_form.is_valid():
            data = self.filter_form.cleaned_data
            if q := data.get("q"):
                qs = qs.filter(
                    Q(patient__first_name__icontains=q)
                    | Q(patient__last_name__icontains=q)
                    | Q(patient__patient_id__icontains=q)
                    | Q(diagnosis__icontains=q)
                )
            if data.get("doctor"):
                qs = qs.filter(doctor=data["doctor"])
            if data.get("date_from"):
                qs = qs.filter(visit_date__gte=local_dt(data["date_from"], time.min))
            if data.get("date_to"):
                qs = qs.filter(visit_date__lt=local_dt(data["date_to"], time.min) + timedelta(days=1))
        return qs.order_by("-visit_date")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["filter_form"] = self.filter_form
        return context


@capability_required("records_view")
def record_detail(request, pk):
    record = get_object_or_404(visible_records(request.user), pk=pk)
    doctor = doctor_profile_for(request.user)
    context = {
        "record": record,
        "prescriptions": record.prescriptions.prefetch_related("items"),
        "can_edit": has_capability(request.user, "records_manage") and doctor is not None and record.doctor_id == doctor.pk,
        "history": history_for(record),
    }
    return render(request, "medical_records/record_detail.html", context)


@capability_required("records_manage")
def record_create(request):
    doctor = _require_doctor_profile(request)
    initial = {}
    if (patient_pk := request.GET.get("patient", "")).isdigit():
        initial["patient"] = visible_patients(request.user).filter(pk=int(patient_pk)).first()
    if (appt_pk := request.GET.get("appointment", "")).isdigit():
        appointment = doctor.appointments.filter(pk=int(appt_pk)).select_related("patient").first()
        if appointment:
            initial.update(appointment=appointment, patient=appointment.patient, symptoms=appointment.reason)
    form = MedicalRecordForm(request.POST or None, user=request.user, doctor=doctor, initial=initial)
    if request.method == "POST" and form.is_valid():
        record = form.save(commit=False)
        record.doctor = doctor
        record.created_by = record.updated_by = request.user
        record.save()
        log_action(request.user, AuditLog.Action.CREATE, record, "Medical record created", request=request)
        messages.success(request, "Medical record saved.")
        return redirect("records:detail", pk=record.pk)
    return render(request, "medical_records/record_form.html", {"form": form})


@capability_required("records_manage")
def record_edit(request, pk):
    doctor = _require_doctor_profile(request)
    record = get_object_or_404(visible_records(request.user), pk=pk)
    if record.doctor_id != doctor.pk:
        raise PermissionDenied("Only the authoring doctor can edit this record.")
    form = MedicalRecordForm(request.POST or None, instance=record, user=request.user, doctor=doctor)
    if request.method == "POST" and form.is_valid():
        changes = form_changes(form)
        record = form.save(commit=False)
        record.updated_by = request.user
        record.save()
        log_action(request.user, AuditLog.Action.UPDATE, record, "Medical record amended", changes, request)
        messages.success(request, "Medical record updated. The change has been logged.")
        return redirect("records:detail", pk=record.pk)
    return render(request, "medical_records/record_form.html", {"form": form, "record": record})


class PrescriptionListView(CapabilityRequiredMixin, ListView):
    required_capability = "prescriptions_view"
    template_name = "medical_records/prescription_list.html"
    context_object_name = "prescriptions"
    paginate_by = settings.HMS_PAGE_SIZE

    def get_queryset(self):
        qs = visible_prescriptions(self.request.user).prefetch_related("items")
        self.status = self.request.GET.get("status", "active" if has_capability(self.request.user, "prescriptions_dispense") else "")
        if self.status in Prescription.Status.values:
            qs = qs.filter(status=self.status)
        if q := self.request.GET.get("q", "").strip():
            qs = qs.filter(
                Q(prescription_number__icontains=q)
                | Q(patient__first_name__icontains=q)
                | Q(patient__last_name__icontains=q)
                | Q(patient__patient_id__icontains=q)
            )
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["statuses"] = Prescription.Status.choices
        context["status"] = self.status
        return context


@capability_required("prescriptions_view")
def prescription_detail(request, pk):
    rx = get_object_or_404(visible_prescriptions(request.user).prefetch_related("items__medicine"), pk=pk)
    doctor = doctor_profile_for(request.user)
    context = {
        "rx": rx,
        "can_dispense": has_capability(request.user, "prescriptions_dispense") and rx.status == Prescription.Status.ACTIVE,
        "can_cancel": (
            has_capability(request.user, "prescriptions_manage")
            and doctor is not None
            and rx.doctor_id == doctor.pk
            and rx.status == Prescription.Status.ACTIVE
        ),
    }
    return render(request, "medical_records/prescription_detail.html", context)


@capability_required("prescriptions_manage")
def prescription_create(request):
    doctor = _require_doctor_profile(request)
    initial = {}
    if (record_pk := request.GET.get("record", "")).isdigit():
        record = MedicalRecord.objects.filter(pk=int(record_pk), doctor=doctor).first()
        if record:
            initial.update(medical_record=record, patient=record.patient)
    elif (patient_pk := request.GET.get("patient", "")).isdigit():
        initial["patient"] = visible_patients(request.user).filter(pk=int(patient_pk)).first()
    form = PrescriptionForm(request.POST or None, user=request.user, doctor=doctor, initial=initial)
    formset = PrescriptionItemFormSet(request.POST or None, prefix="items")
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        with transaction.atomic():
            rx = form.save(commit=False)
            rx.doctor = doctor
            rx.save()
            formset.instance = rx
            formset.save()
        log_action(request.user, AuditLog.Action.CREATE, rx, "Prescription issued", request=request)
        messages.success(request, f"Prescription {rx.prescription_number} issued.")
        return redirect("records:prescription_detail", pk=rx.pk)
    return render(request, "medical_records/prescription_form.html", {"form": form, "formset": formset})


@require_POST
@capability_required("prescriptions_dispense")
def prescription_dispense(request, pk):
    rx = get_object_or_404(visible_prescriptions(request.user), pk=pk)
    try:
        dispense_prescription(rx, request.user)
    except StockError as exc:
        messages.error(request, f"Could not dispense: {exc}")
    else:
        log_action(request.user, AuditLog.Action.STATUS, rx, "Prescription dispensed", request=request)
        messages.success(request, f"Prescription {rx.prescription_number} dispensed and stock updated.")
    return redirect("records:prescription_detail", pk=rx.pk)


@require_POST
@capability_required("prescriptions_manage")
def prescription_cancel(request, pk):
    doctor = _require_doctor_profile(request)
    rx = get_object_or_404(visible_prescriptions(request.user), pk=pk, doctor=doctor)
    if rx.status != Prescription.Status.ACTIVE:
        messages.error(request, "Only prescriptions awaiting dispensing can be cancelled.")
    else:
        rx.status = Prescription.Status.CANCELLED
        rx.save(update_fields=["status", "updated_at"])
        log_action(request.user, AuditLog.Action.STATUS, rx, "Prescription cancelled", request=request)
        messages.success(request, "Prescription cancelled.")
    return redirect("records:prescription_detail", pk=rx.pk)


@capability_required("prescriptions_view")
def prescription_print(request, pk):
    rx = get_object_or_404(visible_prescriptions(request.user).prefetch_related("items"), pk=pk)
    return render(request, "medical_records/prescription_print.html", {"rx": rx, "printed_at": timezone.now()})
