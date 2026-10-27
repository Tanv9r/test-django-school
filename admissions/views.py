from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Prefetch, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.generic import ListView

from accounts.models import Role
from accounts.permissions import CapabilityRequiredMixin, capability_required, has_capability
from core.audit import form_changes, log_action
from core.models import AuditLog
from patients.models import Patient

from . import services
from .forms import (
    AdmissionFilterForm,
    AdmissionForm,
    AdmissionUpdateForm,
    BedForm,
    DischargeForm,
    NursingTaskForm,
    RoomForm,
)
from .models import Admission, Bed, NursingTask, Room, RoomType


def visible_admissions(user):
    qs = Admission.objects.select_related("patient", "bed__room__room_type", "attending_doctor", "assigned_nurse")
    if not has_capability(user, "admissions_view"):
        return qs.none()
    role = user.effective_role
    if role == Role.DOCTOR:
        doctor = getattr(user, "doctor_profile", None)
        return qs.filter(attending_doctor=doctor) if doctor else qs.none()
    if role == Role.NURSE:
        return qs.filter(assigned_nurse=user)
    return qs


def visible_tasks(user):
    qs = NursingTask.objects.select_related("admission__patient", "admission__bed__room", "assigned_to")
    if not has_capability(user, "nursing_view"):
        return qs.none()
    if user.effective_role == Role.NURSE:
        return qs.filter(Q(assigned_to=user) | Q(admission__assigned_nurse=user))
    return qs.filter(admission__in=visible_admissions(user))


class AdmissionListView(CapabilityRequiredMixin, ListView):
    required_capability = "admissions_view"
    template_name = "admissions/admission_list.html"
    context_object_name = "admissions"
    paginate_by = settings.HMS_PAGE_SIZE

    def get_queryset(self):
        self.filter_form = AdmissionFilterForm(self.request.GET or None)
        qs = visible_admissions(self.request.user)
        status = "admitted"
        if self.filter_form.is_valid():
            data = self.filter_form.cleaned_data
            status = data.get("status") or "admitted"
            if q := data.get("q"):
                qs = qs.filter(
                    Q(patient__first_name__icontains=q)
                    | Q(patient__last_name__icontains=q)
                    | Q(patient__patient_id__icontains=q)
                    | Q(admission_number__icontains=q)
                    | Q(bed__room__number__icontains=q)
                )
            if data.get("doctor"):
                qs = qs.filter(attending_doctor=data["doctor"])
            if data.get("room_type"):
                qs = qs.filter(bed__room__room_type=data["room_type"])
        if status in Admission.Status.values:
            qs = qs.filter(status=status)
        return qs.order_by("-admitted_at")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["filter_form"] = self.filter_form
        context["occupancy"] = services.occupancy_summary()
        return context


@capability_required("admissions_manage")
def admission_create(request):
    initial = {}
    if (patient_pk := request.GET.get("patient", "")).isdigit():
        initial["patient"] = Patient.objects.filter(pk=int(patient_pk)).first()
    if (bed_pk := request.GET.get("bed", "")).isdigit():
        initial["bed"] = Bed.objects.filter(pk=int(bed_pk)).first()
    form = AdmissionForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            admission = services.admit_patient(
                patient=data["patient"],
                bed=data["bed"],
                doctor=data["attending_doctor"],
                nurse=data.get("assigned_nurse"),
                reason=data["reason"],
                admitted_at=data["admitted_at"],
                user=request.user,
            )
        except services.AdmissionError as exc:
            form.add_error(None, str(exc))
        else:
            log_action(request.user, AuditLog.Action.CREATE, admission, f"Admitted to {admission.bed.label}", request=request)
            messages.success(request, f"{admission.patient.full_name} admitted to {admission.bed.label}.")
            return redirect("admissions:detail", pk=admission.pk)
    return render(request, "admissions/admission_form.html", {"form": form})


@capability_required("admissions_view")
def admission_detail(request, pk):
    admission = get_object_or_404(visible_admissions(request.user), pk=pk)
    user = request.user
    context = {
        "admission": admission,
        "room_charge_estimate": admission.bed.room.room_type.daily_rate * admission.length_of_stay_days,
        "can_discharge": has_capability(user, "admissions_discharge") and admission.status == Admission.Status.ADMITTED,
        "can_manage": has_capability(user, "admissions_manage") and admission.status == Admission.Status.ADMITTED,
    }
    if context["can_discharge"]:
        context["discharge_form"] = DischargeForm(admission=admission)
    if has_capability(user, "nursing_view"):
        context["tasks"] = admission.tasks.select_related("assigned_to", "completed_by")
        context["can_add_task"] = has_capability(user, "nursing_manage") and admission.status == Admission.Status.ADMITTED
    return render(request, "admissions/admission_detail.html", context)


@capability_required("admissions_manage")
def admission_update(request, pk):
    admission = get_object_or_404(visible_admissions(request.user), pk=pk, status=Admission.Status.ADMITTED)
    form = AdmissionUpdateForm(request.POST or None, instance=admission)
    if request.method == "POST" and form.is_valid():
        changes = form_changes(form)
        form.save()
        log_action(request.user, AuditLog.Action.UPDATE, admission, "Admission care team updated", changes, request)
        messages.success(request, "Admission updated.")
        return redirect("admissions:detail", pk=admission.pk)
    return render(request, "admissions/admission_update.html", {"form": form, "admission": admission})


@require_POST
@capability_required("admissions_discharge")
def admission_discharge(request, pk):
    admission = get_object_or_404(visible_admissions(request.user), pk=pk)
    form = DischargeForm(request.POST, admission=admission)
    if form.is_valid():
        try:
            services.discharge_patient(
                admission,
                summary=form.cleaned_data["discharge_summary"],
                discharged_at=form.cleaned_data["discharged_at"],
                user=request.user,
            )
        except services.AdmissionError as exc:
            messages.error(request, str(exc))
        else:
            log_action(request.user, AuditLog.Action.STATUS, admission, "Patient discharged; bed released", request=request)
            messages.success(request, f"{admission.patient.full_name} discharged. Bed {admission.bed} is now available.")
            return redirect("admissions:detail", pk=admission.pk)
    else:
        for field, errors in form.errors.items():
            messages.error(request, f"{form.fields[field].label if field in form.fields else 'Discharge'}: {' '.join(errors)}")
    return redirect("admissions:detail", pk=admission.pk)


@capability_required("beds_view")
def bed_board(request):
    active = Admission.objects.filter(status=Admission.Status.ADMITTED).select_related("patient", "attending_doctor")
    rooms = (
        Room.objects.filter(is_active=True)
        .select_related("room_type", "department")
        .prefetch_related(Prefetch("beds", queryset=Bed.objects.prefetch_related(Prefetch("admissions", queryset=active, to_attr="current"))))
    )
    status = request.GET.get("status", "")
    if room_type := request.GET.get("room_type", ""):
        rooms = rooms.filter(room_type_id=room_type) if room_type.isdigit() else rooms
    by_type = (
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
    context = {
        "rooms": rooms,
        "summary": services.occupancy_summary(),
        "by_type": by_type,
        "status_filter": status if status in Bed.Status.values else "",
        "room_types": RoomType.objects.filter(is_active=True),
        "selected_room_type": room_type,
    }
    return render(request, "admissions/bed_board.html", context)


@capability_required("beds_manage")
def room_list(request):
    rooms = Room.objects.select_related("room_type", "department").annotate(
        bed_total=Count("beds"),
        bed_occupied=Count("beds", filter=Q(beds__status=Bed.Status.OCCUPIED)),
    )
    return render(request, "admissions/room_list.html", {"rooms": rooms})


@capability_required("beds_manage")
def room_form(request, pk=None):
    room = get_object_or_404(Room, pk=pk) if pk else Room()
    form = RoomForm(request.POST or None, instance=room)
    if request.method == "POST" and form.is_valid():
        changes = form_changes(form) if pk else {}
        with transaction.atomic():
            room = form.save()
            for number in range(1, (form.cleaned_data.get("bed_count") or 0) + 1):
                Bed.objects.create(room=room, bed_number=str(number))
        log_action(request.user, AuditLog.Action.UPDATE if pk else AuditLog.Action.CREATE, room, "Room saved", changes, request)
        messages.success(request, f"Room {room.number} saved.")
        return redirect("admissions:room_detail", pk=room.pk)
    return render(request, "admissions/room_form.html", {"form": form, "room": room if pk else None})


@capability_required("beds_manage")
def room_detail(request, pk):
    room = get_object_or_404(Room.objects.select_related("room_type", "department"), pk=pk)
    return render(request, "admissions/room_detail.html", {"room": room, "beds": room.beds.all(), "bed_form": BedForm(room=room)})


@capability_required("beds_manage")
def bed_form(request, room_pk, pk=None):
    room = get_object_or_404(Room, pk=room_pk)
    bed = get_object_or_404(Bed, pk=pk, room=room) if pk else Bed(room=room)
    form = BedForm(request.POST or None, instance=bed, room=room)
    if request.method == "POST" and form.is_valid():
        changes = form_changes(form) if pk else {}
        bed = form.save()
        log_action(request.user, AuditLog.Action.UPDATE if pk else AuditLog.Action.CREATE, bed, "Bed saved", changes, request)
        messages.success(request, f"Bed {bed} saved.")
        return redirect("admissions:room_detail", pk=room.pk)
    return render(request, "admissions/bed_form.html", {"form": form, "room": room, "bed": bed if pk else None})


class TaskListView(CapabilityRequiredMixin, ListView):
    required_capability = "nursing_view"
    template_name = "admissions/task_list.html"
    context_object_name = "tasks"
    paginate_by = 20

    def get_queryset(self):
        qs = visible_tasks(self.request.user).filter(admission__status=Admission.Status.ADMITTED)
        self.status = self.request.GET.get("status", "open")
        if self.status == "open":
            qs = qs.exclude(status=NursingTask.Status.DONE)
        elif self.status in NursingTask.Status.values:
            qs = qs.filter(status=self.status)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["status"] = self.status
        context["statuses"] = NursingTask.Status.choices
        context["now"] = timezone.now()
        return context


@capability_required("nursing_manage")
def task_create(request, admission_pk):
    admission = get_object_or_404(visible_admissions(request.user), pk=admission_pk, status=Admission.Status.ADMITTED)
    form = NursingTaskForm(request.POST or None, initial={"assigned_to": admission.assigned_nurse})
    if request.method == "POST" and form.is_valid():
        task = form.save(commit=False)
        task.admission = admission
        task.created_by = request.user
        task.save()
        log_action(request.user, AuditLog.Action.CREATE, task, f"Nursing task for {admission.admission_number}", request=request)
        messages.success(request, "Nursing task added.")
        return redirect("admissions:detail", pk=admission.pk)
    return render(request, "admissions/task_form.html", {"form": form, "admission": admission})


@require_POST
@capability_required("nursing_manage")
def task_update_status(request, pk):
    task = get_object_or_404(visible_tasks(request.user), pk=pk)
    new_status = request.POST.get("status")
    if new_status not in NursingTask.Status.values:
        messages.error(request, "Invalid task status.")
    else:
        task.status = new_status
        if new_status == NursingTask.Status.DONE:
            task.completed_at, task.completed_by = timezone.now(), request.user
        else:
            task.completed_at, task.completed_by = None, None
        task.save(update_fields=["status", "completed_at", "completed_by", "updated_at"])
        log_action(request.user, AuditLog.Action.STATUS, task, f"Task marked {task.get_status_display()}", request=request)
        messages.success(request, f"Task “{task.title}” marked as {task.get_status_display().lower()}.")
    next_url = request.POST.get("next")
    if next_url == "tasks":
        return redirect("admissions:tasks")
    return redirect("admissions:detail", pk=task.admission_id)
