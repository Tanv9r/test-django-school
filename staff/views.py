from django.conf import settings
from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import ListView

from accounts.permissions import CapabilityRequiredMixin, capability_required, has_capability
from core.audit import form_changes, log_action
from core.models import AuditLog

from .forms import StaffFilterForm, StaffProfileForm
from .models import StaffProfile


class StaffListView(CapabilityRequiredMixin, ListView):
    required_capability = "staff_view"
    template_name = "staff/staff_list.html"
    context_object_name = "staff_members"
    paginate_by = settings.HMS_PAGE_SIZE

    def get_queryset(self):
        self.filter_form = StaffFilterForm(self.request.GET or None)
        qs = StaffProfile.objects.select_related("department", "user")
        if self.filter_form.is_valid():
            data = self.filter_form.cleaned_data
            if q := data.get("q"):
                qs = qs.filter(
                    Q(first_name__icontains=q)
                    | Q(last_name__icontains=q)
                    | Q(employee_id__icontains=q)
                    | Q(job_title__icontains=q)
                    | Q(email__icontains=q)
                )
            if data.get("department"):
                qs = qs.filter(department=data["department"])
            if data.get("status"):
                qs = qs.filter(employment_status=data["status"])
            if role := data.get("role"):
                qs = qs.filter(user__isnull=True) if role == "none" else qs.filter(user__role=role)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["filter_form"] = self.filter_form
        return context


@capability_required("staff_view")
def staff_detail(request, pk):
    member = get_object_or_404(StaffProfile.objects.select_related("department", "user"), pk=pk)
    context = {"member": member, "show_private": has_capability(request.user, "staff_manage")}
    return render(request, "staff/staff_detail.html", context)


@capability_required("staff_manage")
def staff_form(request, pk=None):
    member = get_object_or_404(StaffProfile, pk=pk) if pk else StaffProfile()
    form = StaffProfileForm(request.POST or None, instance=member)
    if request.method == "POST" and form.is_valid():
        changes = form_changes(form) if pk else {}
        member = form.save()
        log_action(request.user, AuditLog.Action.UPDATE if pk else AuditLog.Action.CREATE, member, "Staff profile saved", changes, request)
        messages.success(request, f"Staff profile for {member.full_name} saved.")
        return redirect("staff:detail", pk=member.pk)
    return render(request, "staff/staff_form.html", {"form": form, "member": member if pk else None})
