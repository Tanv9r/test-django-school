from datetime import timedelta

from django import forms
from django.db.models import Q
from django.utils import timezone

from accounts.models import Role, User
from core.forms import BootstrapForm, BootstrapModelForm, DateInput
from doctors.models import Department

from .models import StaffProfile


class StaffProfileForm(BootstrapModelForm):
    class Meta:
        model = StaffProfile
        fields = [
            "first_name",
            "last_name",
            "email",
            "phone",
            "job_title",
            "department",
            "joining_date",
            "employment_status",
            "user",
            "address",
            "notes",
        ]
        widgets = {"joining_date": DateInput(), "address": forms.Textarea(attrs={"rows": 2}), "notes": forms.Textarea(attrs={"rows": 2})}
        labels = {"user": "Login account"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        user_filter = Q(staff_profile__isnull=True)
        if self.instance.pk and self.instance.user_id:
            user_filter |= Q(pk=self.instance.user_id)
        self.fields["user"].queryset = User.objects.filter(user_filter)
        self.fields["user"].required = False
        self.fields["user"].label_from_instance = lambda u: f"{u.username} · {u.get_role_display()}"
        self.fields["department"].queryset = Department.objects.filter(is_active=True)

    def clean_joining_date(self):
        value = self.cleaned_data["joining_date"]
        if value > timezone.localdate() + timedelta(days=365):
            raise forms.ValidationError("The joining date is too far in the future.")
        return value


class StaffFilterForm(BootstrapForm):
    q = forms.CharField(required=False, label="Search", widget=forms.TextInput(attrs={"placeholder": "Name, employee ID, title or email"}))
    department = forms.ModelChoiceField(queryset=Department.objects.all(), required=False, empty_label="All departments")
    status = forms.ChoiceField(required=False, choices=[("", "Any status"), *StaffProfile.EmploymentStatus.choices])
    role = forms.ChoiceField(required=False, choices=[("", "Any role"), *Role.choices, ("none", "No system access")])
