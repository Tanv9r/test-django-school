from datetime import time, timedelta

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import Role, User
from accounts.permissions import capability_required
from admissions.models import Admission
from appointments.models import Appointment
from appointments.services import local_dt
from billing.models import ZERO, Payment
from core.audit import form_changes, log_action
from core.models import AuditLog, HospitalSettings
from dashboard import stats
from doctors.models import Doctor
from patients.models import Patient
from pharmacy.models import Medicine
from staff.models import StaffProfile

from .config_registry import SECTIONS
from .forms import AuditFilterForm, HospitalSettingsForm, StyledSetPasswordForm, UserCreateForm, UserFilterForm, UserUpdateForm

admin_required = capability_required("adminpanel_access")


@admin_required
def overview(request):
    start, end = stats.today_bounds()
    month_start = local_dt(timezone.localdate().replace(day=1), time.min)
    pending = stats.pending_invoices()
    occupancy = stats.bed_occupancy()
    all_appointments = Appointment.objects.all()
    role_counts = dict(User.objects.filter(is_active=True).values_list("role").annotate(n=Count("id")).order_by())
    context = {
        "cards": [
            {"label": "Registered patients", "value": Patient.objects.filter(is_active=True).count(), "icon": "people"},
            {"label": "Active doctors", "value": Doctor.objects.filter(is_active=True).count(), "icon": "person-badge"},
            {"label": "Today's appointments", "value": all_appointments.filter(start_at__gte=start, start_at__lt=end).exclude(status="cancelled").count(), "icon": "calendar-check"},
            {"label": "Currently admitted", "value": Admission.objects.filter(status="admitted").count(), "icon": "hospital"},
            {"label": "Available beds", "value": occupancy["available"], "icon": "door-open", "hint": f"{occupancy['occupancy_rate']}% occupied"},
            {"label": "Pending invoices", "value": pending["count"], "icon": "receipt", "hint": "unpaid or partial"},
            {"label": "Collected today", "value": stats.todays_collections(), "icon": "cash-coin", "money": True},
            {"label": "Revenue this month", "value": Payment.objects.filter(paid_at__gte=month_start).aggregate(s=Sum("amount"))["s"] or ZERO, "icon": "graph-up-arrow", "money": True},
        ],
        "outstanding": stats.outstanding_balance(),
        "revenue_chart": stats.monthly_revenue(12),
        "appointment_chart": stats.appointment_status_breakdown(all_appointments),
        "daily_chart": stats.daily_appointments(all_appointments),
        "occupancy": occupancy,
        "role_chart": {"labels": [label for _, label in Role.choices], "values": [role_counts.get(v, 0) for v, _ in Role.choices]},
        "user_total": User.objects.count(),
        "staff_total": StaffProfile.objects.filter(employment_status="active").count(),
        "low_stock": Medicine.objects.low_stock().count(),
        "recent_activity": AuditLog.objects.select_related("user")[:8],
        "recent_patients": Patient.objects.order_by("-created_at")[:5],
        "failed_logins": AuditLog.objects.filter(action=AuditLog.Action.LOGIN_FAILED, created_at__gte=timezone.now() - timedelta(hours=24)).count(),
    }
    return render(request, "adminpanel/overview.html", context)


# ---------------------------------------------------------------- users


@admin_required
def user_list(request):
    form = UserFilterForm(request.GET or None)
    qs = User.objects.select_related("staff_profile", "doctor_profile").order_by("username")
    if form.is_valid():
        data = form.cleaned_data
        if q := data.get("q"):
            qs = qs.filter(Q(username__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(email__icontains=q))
        if data.get("role"):
            qs = qs.filter(role=data["role"])
        if data.get("status"):
            qs = qs.filter(is_active=data["status"] == "active")
    page = Paginator(qs, 15).get_page(request.GET.get("page"))
    return render(request, "adminpanel/user_list.html", {"page_obj": page, "users": page.object_list, "filter_form": form, "is_paginated": page.has_other_pages()})


def _link_profiles(request, user):
    """Optionally link a new login to an existing staff or doctor profile (``?staff=`` / ``?doctor=``)."""
    staff_pk, doctor_pk = request.GET.get("staff", ""), request.GET.get("doctor", "")
    if staff_pk.isdigit():
        StaffProfile.objects.filter(pk=int(staff_pk), user__isnull=True).update(user=user)
    if doctor_pk.isdigit() and user.role == Role.DOCTOR:
        Doctor.objects.filter(pk=int(doctor_pk), user__isnull=True).update(user=user)


@admin_required
def user_create(request):
    initial = {}
    staff = None
    if (staff_pk := request.GET.get("staff", "")).isdigit():
        staff = StaffProfile.objects.filter(pk=int(staff_pk), user__isnull=True).first()
        if staff:
            initial = {"first_name": staff.first_name, "last_name": staff.last_name, "email": staff.email, "phone": staff.phone}
    doctor = None
    if (doctor_pk := request.GET.get("doctor", "")).isdigit():
        doctor = Doctor.objects.filter(pk=int(doctor_pk), user__isnull=True).first()
        if doctor:
            initial = {"first_name": doctor.first_name, "last_name": doctor.last_name, "email": doctor.email, "phone": doctor.phone, "role": Role.DOCTOR}
    form = UserCreateForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        _link_profiles(request, user)
        log_action(request.user, AuditLog.Action.ACCESS, user, f"User account created with role {user.get_role_display()}", request=request)
        messages.success(request, f"User {user.username} created.")
        return redirect("adminpanel:user_edit", pk=user.pk)
    return render(request, "adminpanel/user_form.html", {"form": form, "link_staff": staff, "link_doctor": doctor})


def _would_remove_last_admin(user, new_role, new_active):
    if user.effective_role != Role.ADMIN or (new_role == Role.ADMIN and new_active):
        return False
    others = User.objects.filter(is_active=True).filter(Q(role=Role.ADMIN) | Q(is_superuser=True)).exclude(pk=user.pk)
    return not others.exists()


@admin_required
def user_edit(request, pk):
    target = get_object_or_404(User, pk=pk)
    form = UserUpdateForm(request.POST or None, instance=target, acting_user=request.user)
    if request.method == "POST" and form.is_valid():
        if _would_remove_last_admin(target, form.cleaned_data.get("role", target.role), form.cleaned_data["is_active"]):
            form.add_error(None, "At least one active administrator must remain.")
        else:
            changes = form_changes(form)
            form.save()
            log_action(request.user, AuditLog.Action.ACCESS, target, "User account updated", changes, request)
            messages.success(request, f"User {target.username} updated.")
            return redirect("adminpanel:user_edit", pk=target.pk)
    context = {
        "form": form,
        "target": target,
        "password_form": StyledSetPasswordForm(target),
        "activity": AuditLog.objects.filter(user=target)[:10],
    }
    return render(request, "adminpanel/user_edit.html", context)


@require_POST
@admin_required
def user_set_password(request, pk):
    target = get_object_or_404(User, pk=pk)
    form = StyledSetPasswordForm(target, request.POST)
    if form.is_valid():
        form.save()
        log_action(request.user, AuditLog.Action.ACCESS, target, "Password reset by administrator", request=request)
        messages.success(request, f"Password for {target.username} has been reset.")
    else:
        for errors in form.errors.values():
            messages.error(request, " ".join(errors))
    return redirect("adminpanel:user_edit", pk=target.pk)


@require_POST
@admin_required
def user_toggle_active(request, pk):
    target = get_object_or_404(User, pk=pk)
    if target.pk == request.user.pk:
        messages.error(request, "You cannot deactivate your own account.")
    elif target.is_active and _would_remove_last_admin(target, target.role, False):
        messages.error(request, "At least one active administrator must remain.")
    else:
        target.is_active = not target.is_active
        target.save(update_fields=["is_active"])
        state = "activated" if target.is_active else "deactivated"
        log_action(request.user, AuditLog.Action.ACCESS, target, f"Account {state}", request=request)
        messages.success(request, f"{target.username} {state}.")
    return redirect("adminpanel:user_list")


# ---------------------------------------------------------------- configuration tables


def _section(slug):
    section = SECTIONS.get(slug)
    if section is None:
        raise Http404
    return section


@admin_required
def config_list(request, slug):
    section = _section(slug)
    objects = section.model.objects.all()
    rows = [{"obj": obj, "cells": [getattr(obj, attr) for attr, _ in section.columns]} for obj in objects]
    return render(request, "adminpanel/config_list.html", {"section": section, "rows": rows, "sections": SECTIONS.values()})


@admin_required
def config_form(request, slug, pk=None):
    section = _section(slug)
    obj = get_object_or_404(section.model, pk=pk) if pk else section.model()
    form = section.form(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        changes = form_changes(form) if pk else {}
        obj = form.save()
        log_action(request.user, AuditLog.Action.UPDATE if pk else AuditLog.Action.CREATE, obj, f"{section.singular.capitalize()} saved", changes, request)
        messages.success(request, f"{section.singular.capitalize()} “{obj}” saved.")
        return redirect("adminpanel:config_list", slug=slug)
    return render(request, "adminpanel/config_form.html", {"section": section, "form": form, "obj": obj if pk else None})


@require_POST
@admin_required
def config_toggle(request, slug, pk):
    section = _section(slug)
    obj = get_object_or_404(section.model, pk=pk)
    obj.is_active = not obj.is_active
    obj.save()
    state = "activated" if obj.is_active else "deactivated"
    log_action(request.user, AuditLog.Action.STATUS, obj, f"{section.singular.capitalize()} {state}", request=request)
    messages.success(request, f"“{obj}” {state}.")
    return redirect("adminpanel:config_list", slug=slug)


# ---------------------------------------------------------------- settings & audit


@admin_required
def hospital_settings(request):
    settings_obj = HospitalSettings.load()
    form = HospitalSettingsForm(request.POST or None, instance=settings_obj)
    if request.method == "POST" and form.is_valid():
        changes = form_changes(form)
        form.save()
        log_action(request.user, AuditLog.Action.UPDATE, settings_obj, "Hospital settings updated", changes, request)
        messages.success(request, "Hospital settings saved.")
        return redirect("adminpanel:settings")
    return render(request, "adminpanel/settings.html", {"form": form})


@admin_required
def audit_log(request):
    form = AuditFilterForm(request.GET or None)
    qs = AuditLog.objects.select_related("user")
    if form.is_valid():
        data = form.cleaned_data
        if q := data.get("q"):
            qs = qs.filter(Q(object_repr__icontains=q) | Q(message__icontains=q) | Q(user__username__icontains=q))
        if data.get("action"):
            qs = qs.filter(action=data["action"])
        if data.get("date_from"):
            qs = qs.filter(created_at__gte=local_dt(data["date_from"], time.min))
        if data.get("date_to"):
            qs = qs.filter(created_at__lt=local_dt(data["date_to"], time.min) + timedelta(days=1))
    page = Paginator(qs, 25).get_page(request.GET.get("page"))
    return render(request, "adminpanel/audit_log.html", {"page_obj": page, "entries": page.object_list, "filter_form": form, "is_paginated": page.has_other_pages()})
