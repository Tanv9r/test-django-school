from datetime import timedelta

from django import forms
from django.utils import timezone

from core.forms import BootstrapForm, BootstrapModelForm, DateInput, TimeInput
from doctors.forms import DoctorSelect
from doctors.models import Department, Doctor
from patients.models import Patient

from . import services
from .models import Appointment


class AppointmentForm(BootstrapModelForm):
    date = forms.DateField(widget=DateInput())
    time = forms.TimeField(widget=TimeInput(), help_text="Local time")

    class Meta:
        model = Appointment
        fields = ["patient", "department", "doctor", "reason", "notes"]
        widgets = {"doctor": DoctorSelect(), "reason": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["patient"].queryset = Patient.objects.filter(is_active=True).order_by("first_name", "last_name")
        self.fields["doctor"].queryset = Doctor.objects.filter(is_active=True).select_related("department")
        self.fields["department"].queryset = Department.objects.filter(is_active=True)
        self.fields["department"].required = False
        self.fields["department"].help_text = "Defaults to the doctor's department."
        if self.instance.pk:
            local = timezone.localtime(self.instance.start_at)
            self.initial.setdefault("date", local.date())
            self.initial.setdefault("time", local.time().replace(second=0, microsecond=0))
            # The patient of an existing appointment cannot be swapped; book a new one instead.
            self.fields["patient"].disabled = True

    def clean(self):
        cleaned = super().clean()
        doctor, day, clock = cleaned.get("doctor"), cleaned.get("date"), cleaned.get("time")
        department = cleaned.get("department")
        if doctor and not department:
            cleaned["department"] = department = doctor.department
        if doctor and department and doctor.department_id != department.pk:
            self.add_error("doctor", f"{doctor} does not work in the {department} department.")
            return cleaned
        if not (doctor and day and clock):
            return cleaned

        start = services.local_dt(day, clock.replace(second=0, microsecond=0))
        end = start + timedelta(minutes=doctor.slot_minutes)
        if start <= timezone.now():
            raise forms.ValidationError("Appointments must be scheduled for a future date and time.")
        if not services.is_within_availability(doctor, start, end):
            raise forms.ValidationError(
                f"{doctor} is not available at that time. Choose a slot within the doctor's working hours."
            )
        exclude = self.instance.pk
        if services.doctor_conflicts(doctor, start, end, exclude).exists():
            raise forms.ValidationError("The doctor already has an appointment that overlaps this time slot.")
        patient = cleaned.get("patient") or (self.instance.patient if self.instance.pk else None)
        if patient and services.patient_conflicts(patient, start, end, exclude).exists():
            raise forms.ValidationError("This patient already has another appointment at that time.")
        self.instance.start_at, self.instance.end_at = start, end
        return cleaned


class StatusChangeForm(BootstrapForm):
    status = forms.ChoiceField(choices=Appointment.Status.choices)
    reason = forms.CharField(required=False, max_length=255, label="Cancellation reason")

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("status") == Appointment.Status.CANCELLED and not cleaned.get("reason", "").strip():
            self.add_error("reason", "Please give a reason for the cancellation.")
        return cleaned


class AppointmentFilterForm(BootstrapForm):
    q = forms.CharField(required=False, label="Search", widget=forms.TextInput(attrs={"placeholder": "Patient name, ID or reference"}))
    doctor = forms.ModelChoiceField(queryset=Doctor.objects.all(), required=False, empty_label="All doctors")
    department = forms.ModelChoiceField(queryset=Department.objects.all(), required=False, empty_label="All departments")
    status = forms.ChoiceField(required=False, choices=[("", "Any status"), *Appointment.Status.choices])
    date_from = forms.DateField(required=False, widget=DateInput(), label="From")
    date_to = forms.DateField(required=False, widget=DateInput(), label="To")
