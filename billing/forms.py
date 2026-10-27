from datetime import timedelta
from decimal import Decimal

from django import forms
from django.utils import timezone

from admissions.models import Admission
from appointments.models import Appointment
from core.forms import BootstrapForm, BootstrapModelForm, DateInput, DateTimeInput
from patients.models import Patient

from .models import Invoice, InvoiceItem, PaymentMethod


class PaymentMethodForm(BootstrapModelForm):
    class Meta:
        model = PaymentMethod
        fields = ["name", "description", "is_active"]


class InvoiceForm(BootstrapModelForm):
    add_consultation = forms.BooleanField(
        required=False, label="Add consultation fee from the selected appointment"
    )
    add_room_charges = forms.BooleanField(
        required=False, label="Add room charges from the selected admission"
    )

    class Meta:
        model = Invoice
        fields = ["patient", "appointment", "admission", "issue_date", "due_date", "discount_amount", "notes"]
        widgets = {"issue_date": DateInput(), "due_date": DateInput(), "notes": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["patient"].queryset = Patient.objects.order_by("first_name", "last_name")
        self.fields["appointment"].queryset = Appointment.objects.select_related("patient", "doctor").filter(
            status__in=[Appointment.Status.COMPLETED, Appointment.Status.CONFIRMED, Appointment.Status.SCHEDULED]
        ).order_by("-start_at")
        self.fields["appointment"].label_from_instance = lambda a: (
            f"{a.reference} Â· {a.patient.full_name} Â· {a.doctor} Â· {timezone.localtime(a.start_at):%d %b %Y}"
        )
        self.fields["admission"].queryset = Admission.objects.select_related("patient", "bed__room__room_type").order_by("-admitted_at")
        self.fields["admission"].label_from_instance = lambda a: f"{a.admission_number} Â· {a.patient.full_name} Â· {a.get_status_display()}"
        self.fields["discount_amount"].label = "Discount"
        if self.instance.pk:
            self.fields["patient"].disabled = True

    def clean(self):
        cleaned = super().clean()
        patient = cleaned.get("patient")
        appointment, admission = cleaned.get("appointment"), cleaned.get("admission")
        if patient and appointment and appointment.patient_id != patient.pk:
            self.add_error("appointment", "This appointment belongs to a different patient.")
        if patient and admission and admission.patient_id != patient.pk:
            self.add_error("admission", "This admission belongs to a different patient.")
        if cleaned.get("add_consultation") and not appointment:
            self.add_error("appointment", "Select an appointment to bill its consultation fee.")
        if cleaned.get("add_room_charges") and not admission:
            self.add_error("admission", "Select an admission to bill its room charges.")
        issue, due = cleaned.get("issue_date"), cleaned.get("due_date")
        if issue and due and due < issue:
            self.add_error("due_date", "The due date cannot be before the issue date.")
        return cleaned


class InvoiceItemForm(BootstrapForm):
    item_type = forms.ChoiceField(choices=InvoiceItem.ItemType.choices, label="Type")
    description = forms.CharField(max_length=200)
    quantity = forms.DecimalField(min_value=Decimal("0.01"), max_digits=8, decimal_places=2, initial=1)
    unit_price = forms.DecimalField(min_value=Decimal("0"), max_digits=12, decimal_places=2, label="Unit price")


InvoiceItemFormSet = forms.formset_factory(InvoiceItemForm, extra=1, can_delete=True)


class PaymentForm(BootstrapForm):
    amount = forms.DecimalField(min_value=Decimal("0.01"), max_digits=12, decimal_places=2)
    method = forms.ModelChoiceField(queryset=PaymentMethod.objects.filter(is_active=True), label="Payment method")
    paid_at = forms.DateTimeField(widget=DateTimeInput(), label="Payment time")
    reference = forms.CharField(max_length=80, required=False, help_text="Card slip, transfer ID or receipt number.")
    notes = forms.CharField(max_length=255, required=False)

    def __init__(self, *args, invoice=None, **kwargs):
        self.invoice = invoice
        super().__init__(*args, **kwargs)
        self.initial.setdefault("paid_at", timezone.localtime().replace(second=0, microsecond=0))
        if invoice is not None:
            self.initial.setdefault("amount", invoice.balance_due)

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if self.invoice is not None and amount > self.invoice.balance_due:
            raise forms.ValidationError(f"The amount exceeds the outstanding balance ({self.invoice.balance_due}).")
        return amount

    def clean_paid_at(self):
        value = self.cleaned_data["paid_at"]
        if value > timezone.now() + timedelta(minutes=5):
            raise forms.ValidationError("The payment time cannot be in the future.")
        return value

    def clean(self):
        cleaned = super().clean()
        method = cleaned.get("method")
        if method and method.name.lower() != "cash" and not cleaned.get("reference", "").strip():
            self.add_error("reference", "A reference is required for non-cash payments.")
        return cleaned


class CancelInvoiceForm(BootstrapForm):
    reason = forms.CharField(max_length=255)


class InvoiceFilterForm(BootstrapForm):
    q = forms.CharField(required=False, label="Search", widget=forms.TextInput(attrs={"placeholder": "Invoice no., patient name or ID"}))
    status = forms.ChoiceField(required=False, choices=[("", "Any status"), *Invoice.Status.choices])
    date_from = forms.DateField(required=False, widget=DateInput(), label="Issued from")
    date_to = forms.DateField(required=False, widget=DateInput(), label="Issued to")


class PaymentFilterForm(BootstrapForm):
    q = forms.CharField(required=False, label="Search", widget=forms.TextInput(attrs={"placeholder": "Payment/invoice no. or patient"}))
    method = forms.ModelChoiceField(queryset=PaymentMethod.objects.all(), required=False, empty_label="All methods")
    date_from = forms.DateField(required=False, widget=DateInput(), label="From")
    date_to = forms.DateField(required=False, widget=DateInput(), label="To")
