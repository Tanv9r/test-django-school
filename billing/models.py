from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q, Sum
from django.utils import timezone

from core.models import SequentialCodeMixin, TimeStampedModel

ZERO = Decimal("0.00")
CENT = Decimal("0.01")


def money(value) -> Decimal:
    return Decimal(value or 0).quantize(CENT, rounding=ROUND_HALF_UP)


class PaymentMethod(models.Model):
    name = models.CharField(max_length=60, unique=True)
    description = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Invoice(SequentialCodeMixin, TimeStampedModel):
    code_field = "invoice_number"
    code_prefix = "INV-"

    class Status(models.TextChoices):
        UNPAID = "unpaid", "Unpaid"
        PARTIALLY_PAID = "partially_paid", "Partially paid"
        PAID = "paid", "Paid"
        CANCELLED = "cancelled", "Cancelled"

    OUTSTANDING_STATUSES = [Status.UNPAID, Status.PARTIALLY_PAID]

    invoice_number = models.CharField(max_length=16, unique=True, null=True, blank=True, editable=False)
    patient = models.ForeignKey("patients.Patient", on_delete=models.PROTECT, related_name="invoices")
    appointment = models.ForeignKey(
        "appointments.Appointment", null=True, blank=True, on_delete=models.SET_NULL, related_name="invoices"
    )
    admission = models.ForeignKey(
        "admissions.Admission", null=True, blank=True, on_delete=models.SET_NULL, related_name="invoices"
    )
    issue_date = models.DateField(default=timezone.localdate, db_index=True)
    due_date = models.DateField(null=True, blank=True)
    discount_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=ZERO, validators=[MinValueValidator(ZERO)]
    )
    # Derived totals are stored for fast reporting and recomputed by ``recalculate``.
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO, editable=False)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO, editable=False)
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO, editable=False)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.UNPAID, db_index=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-issue_date", "-pk"]
        indexes = [models.Index(fields=["status", "issue_date"])]
        constraints = [
            models.CheckConstraint(condition=Q(discount_amount__gte=0), name="invoice_discount_non_negative"),
            models.CheckConstraint(condition=Q(amount_paid__gte=0), name="invoice_paid_non_negative"),
            models.CheckConstraint(condition=Q(total__gte=0), name="invoice_total_non_negative"),
        ]

    def build_code(self):
        return f"INV-{self.issue_date:%Y}-{self.pk:05d}"

    def __str__(self):
        return f"{self.invoice_number} – {self.patient.full_name}"

    @property
    def balance_due(self) -> Decimal:
        return money(self.total - self.amount_paid)

    @property
    def is_editable(self) -> bool:
        return self.status == self.Status.UNPAID and self.amount_paid == ZERO

    @property
    def is_overdue(self) -> bool:
        return bool(self.due_date and self.status in self.OUTSTANDING_STATUSES and self.due_date < timezone.localdate())

    def recalculate(self, save=True):
        """Recompute totals and status from items and recorded payments."""
        subtotal = money(self.items.aggregate(s=Sum("line_total"))["s"])
        paid = money(self.payments.aggregate(s=Sum("amount"))["s"])
        self.subtotal = subtotal
        self.total = max(money(subtotal - money(self.discount_amount)), ZERO)
        self.amount_paid = paid
        if self.status != self.Status.CANCELLED:
            # "Paid" requires at least one recorded payment covering the total.
            if paid > ZERO and paid >= self.total:
                self.status = self.Status.PAID
            elif paid > ZERO:
                self.status = self.Status.PARTIALLY_PAID
            else:
                self.status = self.Status.UNPAID
        if save:
            self.save(update_fields=["subtotal", "total", "amount_paid", "status", "updated_at"])
        return self


class InvoiceItem(models.Model):
    class ItemType(models.TextChoices):
        CONSULTATION = "consultation", "Consultation"
        ADMISSION = "admission", "Admission"
        ROOM = "room", "Room charges"
        MEDICINE = "medicine", "Medicine"
        PROCEDURE = "procedure", "Procedure"
        LAB = "lab", "Laboratory"
        OTHER = "other", "Other service"

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="items")
    item_type = models.CharField(max_length=14, choices=ItemType.choices, default=ItemType.OTHER)
    description = models.CharField(max_length=200)
    quantity = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal("1"), validators=[MinValueValidator(CENT)])
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(ZERO)])
    line_total = models.DecimalField(max_digits=12, decimal_places=2, editable=False, default=ZERO)

    class Meta:
        ordering = ["pk"]
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gt=0), name="invoice_item_quantity_positive"),
            models.CheckConstraint(condition=Q(unit_price__gte=0), name="invoice_item_price_non_negative"),
        ]

    def save(self, *args, **kwargs):
        self.line_total = money(Decimal(self.quantity) * Decimal(self.unit_price))
        super().save(*args, **kwargs)

    def __str__(self):
        return self.description


class Payment(SequentialCodeMixin, models.Model):
    code_field = "payment_number"
    code_prefix = "PAY-"

    payment_number = models.CharField(max_length=12, unique=True, null=True, blank=True, editable=False)
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="payments")
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(CENT)])
    method = models.ForeignKey(PaymentMethod, on_delete=models.PROTECT, related_name="payments")
    paid_at = models.DateTimeField(default=timezone.now, db_index=True)
    reference = models.CharField(max_length=80, blank=True, help_text="Card slip, transfer ID or receipt number.")
    notes = models.CharField(max_length=255, blank=True)
    received_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-paid_at"]
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0), name="payment_amount_positive")]

    def __str__(self):
        return f"{self.payment_number} – {self.amount}"
