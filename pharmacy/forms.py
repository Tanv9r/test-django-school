from django import forms
from django.db.models import Q
from django.utils import timezone

from core.forms import BootstrapForm, BootstrapModelForm, DateInput

from .models import Medicine, MedicineCategory, StockTransaction


class MedicineCategoryForm(BootstrapModelForm):
    class Meta:
        model = MedicineCategory
        fields = ["name", "description", "is_active"]


class MedicineForm(BootstrapModelForm):
    opening_stock = forms.IntegerField(min_value=0, initial=0, required=False, help_text="Initial quantity received.")

    class Meta:
        model = Medicine
        fields = [
            "name",
            "generic_name",
            "category",
            "manufacturer",
            "batch_number",
            "unit",
            "unit_price",
            "reorder_level",
            "expiry_date",
            "is_active",
        ]
        widgets = {"expiry_date": DateInput()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        category_filter = Q(is_active=True)
        if self.instance.pk:
            category_filter |= Q(pk=self.instance.category_id)
            # Stock on existing medicines changes only through stock adjustments.
            del self.fields["opening_stock"]
        self.fields["category"].queryset = MedicineCategory.objects.filter(category_filter)

    def clean_expiry_date(self):
        expiry = self.cleaned_data["expiry_date"]
        if not self.instance.pk and expiry <= timezone.localdate():
            raise forms.ValidationError("New stock must have an expiry date in the future.")
        return expiry


class StockAdjustmentForm(BootstrapForm):
    ACTIONS = {
        "addition": (StockTransaction.Type.ADDITION, 1, "Stock received (+)"),
        "increase": (StockTransaction.Type.ADJUSTMENT, 1, "Adjustment – increase (+)"),
        "decrease": (StockTransaction.Type.ADJUSTMENT, -1, "Adjustment – decrease (−)"),
        "expired": (StockTransaction.Type.EXPIRED, -1, "Remove expired / damaged (−)"),
    }

    action = forms.ChoiceField(choices=[(key, value[2]) for key, value in ACTIONS.items()])
    quantity = forms.IntegerField(min_value=1, max_value=1_000_000)
    reference = forms.CharField(required=False, max_length=60, help_text="Supplier invoice, GRN or other reference.")
    note = forms.CharField(required=False, max_length=255)

    def __init__(self, *args, medicine=None, **kwargs):
        self.medicine = medicine
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        action, quantity = cleaned.get("action"), cleaned.get("quantity")
        if action in ("increase", "decrease", "expired") and not cleaned.get("note", "").strip():
            self.add_error("note", "Please explain the reason for this adjustment.")
        if action and quantity and self.medicine is not None:
            _, sign, _ = self.ACTIONS[action]
            if sign < 0 and quantity > self.medicine.quantity:
                self.add_error("quantity", f"Only {self.medicine.quantity} {self.medicine.unit} in stock.")
        return cleaned

    @property
    def signed_change(self):
        transaction_type, sign, _ = self.ACTIONS[self.cleaned_data["action"]]
        return transaction_type, sign * self.cleaned_data["quantity"]


class MedicineFilterForm(BootstrapForm):
    STOCK_CHOICES = [
        ("", "All stock levels"),
        ("low", "Low stock"),
        ("out", "Out of stock"),
        ("expiring", "Expiring soon"),
        ("expired", "Expired"),
        ("inactive", "Inactive"),
    ]
    q = forms.CharField(required=False, label="Search", widget=forms.TextInput(attrs={"placeholder": "Name, generic name, batch or manufacturer"}))
    category = forms.ModelChoiceField(queryset=MedicineCategory.objects.all(), required=False, empty_label="All categories")
    stock = forms.ChoiceField(required=False, choices=STOCK_CHOICES)
