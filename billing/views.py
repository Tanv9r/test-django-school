from datetime import time, timedelta

from django.conf import settings
from django.contrib import messages
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.generic import ListView

from accounts.permissions import CapabilityRequiredMixin, capability_required
from appointments.services import local_dt
from core.audit import log_action
from core.models import AuditLog
from patients.models import Patient

from . import services
from .forms import CancelInvoiceForm, InvoiceFilterForm, InvoiceForm, InvoiceItemFormSet, PaymentFilterForm, PaymentForm
from .models import ZERO, Invoice, Payment


class InvoiceListView(CapabilityRequiredMixin, ListView):
    required_capability = "billing_view"
    template_name = "billing/invoice_list.html"
    context_object_name = "invoices"
    paginate_by = settings.HMS_PAGE_SIZE

    def get_queryset(self):
        self.filter_form = InvoiceFilterForm(self.request.GET or None)
        qs = Invoice.objects.select_related("patient")
        if self.filter_form.is_valid():
            data = self.filter_form.cleaned_data
            if q := data.get("q"):
                qs = qs.filter(
                    Q(invoice_number__icontains=q)
                    | Q(patient__first_name__icontains=q)
                    | Q(patient__last_name__icontains=q)
                    | Q(patient__patient_id__icontains=q)
                )
            if data.get("status"):
                qs = qs.filter(status=data["status"])
            if data.get("date_from"):
                qs = qs.filter(issue_date__gte=data["date_from"])
            if data.get("date_to"):
                qs = qs.filter(issue_date__lte=data["date_to"])
        self.filtered = qs
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        totals = self.filtered.exclude(status=Invoice.Status.CANCELLED).aggregate(
            billed=Sum("total"), collected=Sum("amount_paid")
        )
        billed, collected = totals["billed"] or ZERO, totals["collected"] or ZERO
        context.update(
            filter_form=self.filter_form,
            summary={"billed": billed, "collected": collected, "outstanding": billed - collected},
        )
        return context


def _item_rows(formset):
    return [
        {k: f.cleaned_data[k] for k in ("item_type", "description", "quantity", "unit_price")}
        for f in formset.forms
        if f.cleaned_data and not f.cleaned_data.get("DELETE")
    ]


@capability_required("billing_manage")
def invoice_form(request, pk=None):
    invoice = get_object_or_404(Invoice, pk=pk) if pk else Invoice()
    if pk and not invoice.is_editable:
        messages.error(request, "Only unpaid invoices without payments can be edited.")
        return redirect("billing:invoice_detail", pk=pk)
    initial = {}
    if not pk and (patient_pk := request.GET.get("patient", "")).isdigit():
        initial["patient"] = Patient.objects.filter(pk=int(patient_pk)).first()
    form = InvoiceForm(request.POST or None, instance=invoice, initial=initial)
    item_initial = [
        {"item_type": i.item_type, "description": i.description, "quantity": i.quantity, "unit_price": i.unit_price}
        for i in invoice.items.all()
    ] if pk else None
    formset = InvoiceItemFormSet(request.POST or None, prefix="items", initial=item_initial)
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        rows = _item_rows(formset)
        if form.cleaned_data.get("add_consultation"):
            rows.insert(0, services.consultation_charge(form.cleaned_data["appointment"]))
        if form.cleaned_data.get("add_room_charges"):
            rows.append(services.room_charge(form.cleaned_data["admission"]))
        try:
            invoice = services.save_invoice(form.save(commit=False), rows, request.user)
        except services.BillingError as exc:
            form.add_error(None, str(exc))
        else:
            log_action(request.user, AuditLog.Action.UPDATE if pk else AuditLog.Action.CREATE, invoice, f"Invoice total {invoice.total}", request=request)
            messages.success(request, f"Invoice {invoice.invoice_number} saved. Total due: {invoice.total}.")
            return redirect("billing:invoice_detail", pk=invoice.pk)
    return render(request, "billing/invoice_form.html", {"form": form, "formset": formset, "invoice": invoice if pk else None})


@capability_required("billing_view")
def invoice_detail(request, pk):
    invoice = get_object_or_404(Invoice.objects.select_related("patient", "appointment", "admission", "created_by"), pk=pk)
    context = {
        "invoice": invoice,
        "items": invoice.items.all(),
        "payments": invoice.payments.select_related("method", "received_by"),
        "payment_form": PaymentForm(invoice=invoice) if invoice.balance_due > ZERO and invoice.status != Invoice.Status.CANCELLED else None,
        "cancel_form": CancelInvoiceForm() if invoice.status != Invoice.Status.CANCELLED and not invoice.payments.exists() else None,
    }
    return render(request, "billing/invoice_detail.html", context)


@capability_required("billing_view")
def invoice_print(request, pk):
    invoice = get_object_or_404(Invoice.objects.select_related("patient"), pk=pk)
    return render(
        request,
        "billing/invoice_print.html",
        {"invoice": invoice, "items": invoice.items.all(), "payments": invoice.payments.select_related("method"), "printed_at": timezone.now()},
    )


@capability_required("billing_manage")
def payment_create(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)
    form = PaymentForm(request.POST or None, invoice=invoice)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            payment = services.record_payment(
                invoice,
                amount=data["amount"],
                method=data["method"],
                reference=data["reference"],
                notes=data["notes"],
                paid_at=data["paid_at"],
                user=request.user,
            )
        except services.BillingError as exc:
            form.add_error(None, str(exc))
        else:
            invoice.refresh_from_db()
            log_action(request.user, AuditLog.Action.PAYMENT, invoice, f"Payment {payment.payment_number} of {payment.amount} via {payment.method}", request=request)
            messages.success(request, f"Payment {payment.payment_number} recorded. Invoice status: {invoice.get_status_display()}.")
            return redirect("billing:invoice_detail", pk=invoice.pk)
    return render(request, "billing/payment_form.html", {"form": form, "invoice": invoice})


@require_POST
@capability_required("billing_manage")
def invoice_cancel(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)
    form = CancelInvoiceForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Please give a reason for cancelling the invoice.")
        return redirect("billing:invoice_detail", pk=pk)
    try:
        services.cancel_invoice(invoice, form.cleaned_data["reason"])
    except services.BillingError as exc:
        messages.error(request, str(exc))
    else:
        log_action(request.user, AuditLog.Action.STATUS, invoice, f"Invoice cancelled: {form.cleaned_data['reason']}", request=request)
        messages.success(request, "Invoice cancelled.")
    return redirect("billing:invoice_detail", pk=pk)


class PaymentListView(CapabilityRequiredMixin, ListView):
    required_capability = "billing_view"
    template_name = "billing/payment_list.html"
    context_object_name = "payments"
    paginate_by = settings.HMS_PAGE_SIZE

    def get_queryset(self):
        self.filter_form = PaymentFilterForm(self.request.GET or None)
        qs = Payment.objects.select_related("invoice__patient", "method", "received_by")
        if self.filter_form.is_valid():
            data = self.filter_form.cleaned_data
            if q := data.get("q"):
                qs = qs.filter(
                    Q(payment_number__icontains=q)
                    | Q(invoice__invoice_number__icontains=q)
                    | Q(invoice__patient__first_name__icontains=q)
                    | Q(invoice__patient__last_name__icontains=q)
                )
            if data.get("method"):
                qs = qs.filter(method=data["method"])
            if data.get("date_from"):
                qs = qs.filter(paid_at__gte=local_dt(data["date_from"], time.min))
            if data.get("date_to"):
                qs = qs.filter(paid_at__lt=local_dt(data["date_to"], time.min) + timedelta(days=1))
        self.filtered = qs
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["filter_form"] = self.filter_form
        context["total_amount"] = self.filtered.aggregate(s=Sum("amount"))["s"] or ZERO
        return context
