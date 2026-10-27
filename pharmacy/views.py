from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import ListView

from accounts.permissions import CapabilityRequiredMixin, capability_required
from core.audit import form_changes, log_action
from core.models import AuditLog, HospitalSettings

from . import services
from .forms import MedicineFilterForm, MedicineForm, StockAdjustmentForm
from .models import Medicine, StockTransaction


class MedicineListView(CapabilityRequiredMixin, ListView):
    required_capability = "pharmacy_view"
    template_name = "pharmacy/medicine_list.html"
    context_object_name = "medicines"
    paginate_by = settings.HMS_PAGE_SIZE

    def get_queryset(self):
        self.filter_form = MedicineFilterForm(self.request.GET or None)
        warning_days = HospitalSettings.load().expiry_warning_days
        qs = Medicine.objects.select_related("category")
        stock = ""
        if self.filter_form.is_valid():
            data = self.filter_form.cleaned_data
            stock = data.get("stock") or ""
            if q := data.get("q"):
                qs = qs.filter(
                    Q(name__icontains=q)
                    | Q(generic_name__icontains=q)
                    | Q(batch_number__icontains=q)
                    | Q(manufacturer__icontains=q)
                    | Q(category__name__icontains=q)
                )
            if data.get("category"):
                qs = qs.filter(category=data["category"])
        filters = {
            "low": lambda s: s.low_stock(),
            "out": lambda s: s.out_of_stock(),
            "expiring": lambda s: s.expiring_within(warning_days),
            "expired": lambda s: s.expired(),
            "inactive": lambda s: s.filter(is_active=False),
        }
        qs = filters[stock](qs) if stock in filters else qs.filter(is_active=True)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        warning_days = HospitalSettings.load().expiry_warning_days
        context.update(
            filter_form=self.filter_form,
            warning_days=warning_days,
            alerts={
                "low": Medicine.objects.low_stock().count(),
                "out": Medicine.objects.out_of_stock().count(),
                "expiring": Medicine.objects.expiring_within(warning_days).count(),
                "expired": Medicine.objects.expired().count(),
            },
        )
        return context


@capability_required("pharmacy_view")
def medicine_detail(request, pk):
    medicine = get_object_or_404(Medicine.objects.select_related("category"), pk=pk)
    context = {
        "medicine": medicine,
        "transactions": medicine.transactions.select_related("performed_by")[:25],
        "warning_days": HospitalSettings.load().expiry_warning_days,
    }
    return render(request, "pharmacy/medicine_detail.html", context)


@capability_required("pharmacy_manage")
def medicine_form(request, pk=None):
    medicine = get_object_or_404(Medicine, pk=pk) if pk else Medicine()
    form = MedicineForm(request.POST or None, instance=medicine)
    if request.method == "POST" and form.is_valid():
        changes = form_changes(form) if pk else {}
        with transaction.atomic():
            medicine = form.save()
            opening = form.cleaned_data.get("opening_stock") or 0
            if not pk and opening:
                services.adjust_stock(medicine, opening, StockTransaction.Type.INITIAL, request.user, "Opening stock")
        log_action(request.user, AuditLog.Action.UPDATE if pk else AuditLog.Action.CREATE, medicine, "Medicine saved", changes, request)
        messages.success(request, f"{medicine.name} has been {'updated' if pk else 'added to inventory'}.")
        return redirect("pharmacy:detail", pk=medicine.pk)
    return render(request, "pharmacy/medicine_form.html", {"form": form, "medicine": medicine if pk else None})


@capability_required("pharmacy_manage")
def stock_adjust(request, pk):
    medicine = get_object_or_404(Medicine, pk=pk)
    form = StockAdjustmentForm(request.POST or None, medicine=medicine)
    if request.method == "POST" and form.is_valid():
        transaction_type, change = form.signed_change
        try:
            entry = services.adjust_stock(
                medicine, change, transaction_type, request.user, form.cleaned_data["note"], form.cleaned_data["reference"]
            )
        except services.StockError as exc:
            form.add_error(None, str(exc))
        else:
            log_action(request.user, AuditLog.Action.STOCK, medicine, str(entry), {"quantity": [str(entry.balance_after - change), str(entry.balance_after)]}, request)
            messages.success(request, f"Stock updated. New balance: {entry.balance_after} {medicine.unit}.")
            return redirect("pharmacy:detail", pk=medicine.pk)
    return render(request, "pharmacy/stock_adjust.html", {"form": form, "medicine": medicine})


class TransactionListView(CapabilityRequiredMixin, ListView):
    required_capability = "pharmacy_view"
    template_name = "pharmacy/transaction_list.html"
    context_object_name = "transactions"
    paginate_by = 25

    def get_queryset(self):
        qs = StockTransaction.objects.select_related("medicine", "performed_by")
        if t := self.request.GET.get("type"):
            qs = qs.filter(transaction_type=t)
        if q := self.request.GET.get("q", "").strip():
            qs = qs.filter(Q(medicine__name__icontains=q) | Q(reference__icontains=q))
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["types"] = StockTransaction.Type.choices
        return context
