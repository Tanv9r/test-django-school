from datetime import timedelta

from django import forms
from django.db.models import Q
from django.utils import timezone

from accounts.models import Role, User
from core.forms import BootstrapForm, BootstrapModelForm, DateTimeInput
from doctors.models import Doctor
from patients.models import Patient

from .models import Admission, Bed, NursingTask, Room, RoomType


def _not_future(value, label):
    if value and value > timezone.now() + timedelta(minutes=5):
        raise forms.ValidationError(f"The {label} time cannot be in the future.")
    return value


def nurse_queryset():
    return User.objects.filter(role=Role.NURSE, is_active=True)


class AdmissionForm(BootstrapForm):
    patient = forms.ModelChoiceField(queryset=Patient.objects.none())
    bed = forms.ModelChoiceField(queryset=Bed.objects.none(), help_text="Only available beds are listed.")
    attending_doctor = forms.ModelChoiceField(queryset=Doctor.objects.filter(is_active=True))
    assigned_nurse = forms.ModelChoiceField(queryset=User.objects.none(), required=False)
    admitted_at = forms.DateTimeField(widget=DateTimeInput(), label="Admission time")
    reason = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), label="Reason for admission")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["patient"].queryset = (
            Patient.objects.filter(is_active=True).exclude(admissions__status=Admission.Status.ADMITTED).order_by("first_name")
        )
        self.fields["bed"].queryset = Bed.objects.filter(
            status=Bed.Status.AVAILABLE, room__is_active=True
        ).select_related("room__room_type")
        self.fields["bed"].label_from_instance = lambda b: f"{b.label} · {b.room.room_type} ({b.room.room_type.daily_rate}/day)"
        self.fields["assigned_nurse"].queryset = nurse_queryset()
        self.fields["assigned_nurse"].label_from_instance = lambda u: u.get_full_name() or u.username
        self.initial.setdefault("admitted_at", timezone.localtime().replace(second=0, microsecond=0))

    def clean_admitted_at(self):
        return _not_future(self.cleaned_data["admitted_at"], "admission")


class AdmissionUpdateForm(BootstrapModelForm):
    class Meta:
        model = Admission
        fields = ["attending_doctor", "assigned_nurse", "reason"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["attending_doctor"].queryset = Doctor.objects.filter(is_active=True)
        self.fields["assigned_nurse"].queryset = nurse_queryset()
        self.fields["assigned_nurse"].label_from_instance = lambda u: u.get_full_name() or u.username


class DischargeForm(BootstrapForm):
    discharged_at = forms.DateTimeField(widget=DateTimeInput(), label="Discharge time")
    discharge_summary = forms.CharField(widget=forms.Textarea(attrs={"rows": 4}))

    def __init__(self, *args, admission=None, **kwargs):
        self.admission = admission
        super().__init__(*args, **kwargs)
        self.initial.setdefault("discharged_at", timezone.localtime().replace(second=0, microsecond=0))

    def clean_discharged_at(self):
        value = _not_future(self.cleaned_data["discharged_at"], "discharge")
        if self.admission and value < self.admission.admitted_at:
            raise forms.ValidationError("The discharge time cannot be before the admission time.")
        return value


class RoomTypeForm(BootstrapModelForm):
    class Meta:
        model = RoomType
        fields = ["name", "description", "daily_rate", "is_active"]


class RoomForm(BootstrapModelForm):
    bed_count = forms.IntegerField(
        min_value=0, max_value=50, initial=1, required=False, label="Beds to create", help_text="Beds are numbered automatically."
    )

    class Meta:
        model = Room
        fields = ["number", "room_type", "department", "floor", "notes", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["room_type"].queryset = RoomType.objects.filter(
            Q(is_active=True) | Q(pk=self.instance.room_type_id or 0)
        )
        if self.instance.pk:
            del self.fields["bed_count"]

    def clean_is_active(self):
        active = self.cleaned_data["is_active"]
        if self.instance.pk and not active and self.instance.beds.filter(status=Bed.Status.OCCUPIED).exists():
            raise forms.ValidationError("This room has occupied beds and cannot be deactivated.")
        return active


class BedForm(BootstrapModelForm):
    class Meta:
        model = Bed
        fields = ["bed_number", "status"]

    def __init__(self, *args, room=None, **kwargs):
        self.room = room
        super().__init__(*args, **kwargs)
        if self.instance.pk and self.instance.status == Bed.Status.OCCUPIED:
            self.fields["status"].disabled = True
            self.fields["status"].help_text = "Occupied beds are released automatically on discharge."
        else:
            self.fields["status"].choices = [
                (Bed.Status.AVAILABLE, Bed.Status.AVAILABLE.label),
                (Bed.Status.MAINTENANCE, Bed.Status.MAINTENANCE.label),
            ]

    def clean_bed_number(self):
        number = self.cleaned_data["bed_number"].strip().upper()
        room = self.room or self.instance.room
        if Bed.objects.filter(room=room, bed_number=number).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("This room already has a bed with that number.")
        return number


class NursingTaskForm(BootstrapModelForm):
    class Meta:
        model = NursingTask
        fields = ["title", "details", "priority", "due_at", "assigned_to"]
        widgets = {"due_at": DateTimeInput(), "details": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assigned_to"].queryset = nurse_queryset()
        self.fields["assigned_to"].label_from_instance = lambda u: u.get_full_name() or u.username


class AdmissionFilterForm(BootstrapForm):
    q = forms.CharField(required=False, label="Search", widget=forms.TextInput(attrs={"placeholder": "Patient, admission no. or room"}))
    status = forms.ChoiceField(required=False, choices=[("admitted", "Currently admitted"), ("discharged", "Discharged"), ("all", "All")])
    doctor = forms.ModelChoiceField(queryset=Doctor.objects.all(), required=False, empty_label="All doctors")
    room_type = forms.ModelChoiceField(queryset=RoomType.objects.all(), required=False, empty_label="All room types")
