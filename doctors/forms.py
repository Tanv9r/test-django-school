from django import forms
from django.db.models import Q
from django.forms import BaseInlineFormSet, inlineformset_factory

from accounts.models import Role, User
from core.forms import BootstrapForm, BootstrapModelForm, TimeInput

from .models import Department, Doctor, DoctorAvailability


class DoctorSelect(forms.Select):
    """Select widget that exposes each doctor's department and slot length to JavaScript."""

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        instance = getattr(value, "instance", None)
        if instance is not None:
            option["attrs"]["data-department"] = instance.department_id
            option["attrs"]["data-fee"] = str(instance.consultation_fee)
        return option


class DepartmentForm(BootstrapModelForm):
    class Meta:
        model = Department
        fields = ["name", "description", "location", "is_active"]

    def clean_name(self):
        name = " ".join(self.cleaned_data["name"].split())
        clash = Department.objects.filter(name__iexact=name).exclude(pk=self.instance.pk)
        if clash.exists():
            raise forms.ValidationError("A department with this name already exists.")
        return name


class DoctorForm(BootstrapModelForm):
    class Meta:
        model = Doctor
        fields = [
            "first_name",
            "last_name",
            "email",
            "phone",
            "department",
            "specialization",
            "qualifications",
            "consultation_fee",
            "slot_minutes",
            "user",
            "bio",
            "is_active",
        ]
        labels = {"user": "Login account"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        dept_filter = Q(is_active=True)
        if self.instance.pk:
            dept_filter |= Q(pk=self.instance.department_id)
        self.fields["department"].queryset = Department.objects.filter(dept_filter)
        user_filter = Q(doctor_profile__isnull=True)
        if self.instance.pk and self.instance.user_id:
            user_filter |= Q(pk=self.instance.user_id)
        self.fields["user"].queryset = User.objects.filter(role=Role.DOCTOR, is_active=True).filter(user_filter)
        self.fields["user"].required = False


class AvailabilityForm(BootstrapModelForm):
    class Meta:
        model = DoctorAvailability
        fields = ["weekday", "start_time", "end_time"]
        widgets = {"start_time": TimeInput(), "end_time": TimeInput()}

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("start_time"), cleaned.get("end_time")
        if start and end and end <= start:
            raise forms.ValidationError("End time must be after start time.")
        return cleaned


class BaseAvailabilityFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        windows: dict[int, list[tuple]] = {}
        for form in self.forms:
            if not hasattr(form, "cleaned_data") or not form.cleaned_data or form.cleaned_data.get("DELETE"):
                continue
            day = form.cleaned_data.get("weekday")
            start, end = form.cleaned_data.get("start_time"), form.cleaned_data.get("end_time")
            if day is None or not start or not end:
                continue
            for other_start, other_end in windows.get(day, []):
                if start < other_end and other_start < end:
                    raise forms.ValidationError(
                        f"Working hours overlap on {DoctorAvailability.Weekday(day).label}."
                    )
            windows.setdefault(day, []).append((start, end))


AvailabilityFormSet = inlineformset_factory(
    Doctor,
    DoctorAvailability,
    form=AvailabilityForm,
    formset=BaseAvailabilityFormSet,
    extra=1,
    can_delete=True,
)


class DoctorFilterForm(BootstrapForm):
    q = forms.CharField(required=False, label="Search", widget=forms.TextInput(attrs={"placeholder": "Name, code or specialization"}))
    department = forms.ModelChoiceField(queryset=Department.objects.all(), required=False, empty_label="All departments")
    status = forms.ChoiceField(
        required=False, choices=[("active", "Active"), ("inactive", "Inactive"), ("all", "All")], initial="active"
    )
