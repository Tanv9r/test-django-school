from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from core.models import TimeStampedModel


class MedicineCategory(models.Model):
    name = models.CharField(max_length=80, unique=True)
    description = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "medicine categories"

    def __str__(self):
        return self.name


class MedicineQuerySet(models.QuerySet):
    def low_stock(self):
        return self.filter(is_active=True, quantity__lte=F("reorder_level"))

    def out_of_stock(self):
        return self.filter(is_active=True, quantity=0)

    def expiring_within(self, days):
        today = timezone.localdate()
        return self.filter(is_active=True, quantity__gt=0, expiry_date__gte=today, expiry_date__lte=today + timedelta(days=days))

    def expired(self):
        return self.filter(is_active=True, quantity__gt=0, expiry_date__lt=timezone.localdate())


class Medicine(TimeStampedModel):
    name = models.CharField(max_length=150, db_index=True)
    generic_name = models.CharField(max_length=150, blank=True)
    category = models.ForeignKey(MedicineCategory, on_delete=models.PROTECT, related_name="medicines")
    manufacturer = models.CharField(max_length=150)
    batch_number = models.CharField(max_length=60)
    unit = models.CharField(max_length=30, default="tablets", help_text="e.g. tablets, vials, bottles")
    quantity = models.PositiveIntegerField(default=0, editable=False, help_text="Changed only through stock transactions.")
    reorder_level = models.PositiveIntegerField(default=20, help_text="Low-stock alert threshold.")
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0"))])
    expiry_date = models.DateField()
    is_active = models.BooleanField(default=True)

    objects = MedicineQuerySet.as_manager()

    class Meta:
        ordering = ["name", "expiry_date"]
        constraints = [
            models.UniqueConstraint(fields=["name", "batch_number"], name="unique_medicine_batch"),
            models.CheckConstraint(condition=Q(quantity__gte=0), name="medicine_quantity_non_negative"),
            models.CheckConstraint(condition=Q(unit_price__gte=0), name="medicine_price_non_negative"),
        ]

    def __str__(self):
        return f"{self.name} ({self.batch_number})"

    @property
    def is_low_stock(self):
        return self.quantity <= self.reorder_level

    @property
    def is_expired(self):
        return self.expiry_date < timezone.localdate()

    @property
    def days_to_expiry(self):
        return (self.expiry_date - timezone.localdate()).days

    @property
    def stock_value(self):
        return self.unit_price * self.quantity


class StockTransaction(models.Model):
    class Type(models.TextChoices):
        INITIAL = "initial", "Opening stock"
        ADDITION = "addition", "Stock received"
        ADJUSTMENT = "adjustment", "Adjustment"
        DISPENSE = "dispense", "Dispensed"
        EXPIRED = "expired", "Expired / damaged removal"

    medicine = models.ForeignKey(Medicine, on_delete=models.PROTECT, related_name="transactions")
    transaction_type = models.CharField(max_length=12, choices=Type.choices, db_index=True)
    quantity_change = models.IntegerField()
    balance_after = models.PositiveIntegerField()
    reference = models.CharField(max_length=60, blank=True, help_text="e.g. supplier invoice or prescription number")
    note = models.CharField(max_length=255, blank=True)
    performed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [models.CheckConstraint(condition=~Q(quantity_change=0), name="stock_change_not_zero")]

    def __str__(self):
        return f"{self.get_transaction_type_display()} {self.quantity_change:+d} {self.medicine.name}"
