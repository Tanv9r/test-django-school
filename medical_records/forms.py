from datetime import timedelta

from django import forms
from django.forms import BaseInlineFormSet, inlineformset_factory
from django.utils import timezone

from appointments.models import Appointment
from core.forms import BootstrapForm, BootstrapModelForm, DateInput, DateTimeInput
from doctors.models import Doctor
from patients.selectors import visible_patients
from pharmacy.models import Medicine

from .models import MedicalRecord, Prescription, PrescriptionItem


class MedicalRecordForm(BootstrapModelForm):
    class Meta:
        model = MedicalRecord
        fields = [
            "patient",
            "appointment",
            "visit_date",
            "symptoms",
            "visit_notes",
            "diagnosis",
            "treatment_plan",
            "follow_up_instructions",
            "follow_up_date",
        ]
        widgets = {"visit_date": DateTimeInput(), "follow_up_date": DateInput()}

    def __init__(self, *args, user=None, doctor=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.doctor = doctor
        self.fields["patient"].queryset = visible_patients(user).filter(is_active=True).order_by("first_name")
        self.fields["appointment"].queryset = (
            Appointment.objects.filter(doctor=doctor).select_related("patient").order_by("-start_at")
            if doctor
            else Appointment.objects.none()
        )
        self.fields["appointment"].required = False
        self.fields["appointment"].label_from_instance = lambda a: (
            f"{a.reference} · {a.patient.full_name} · {timezone.localtime(a.start_at):%d %b %Y %H:%M}"
        )
        if not self.instance.pk:
            self.initial.setdefault("visit_date", timezone.localtime().replace(second=0, microsecond=0))
        else:
            self.fields["patient"].disabled = True

    def clean_visit_date(self):
        visit = self.cleaned_data["visit_date"]
        if visit > timezone.now() + timedelta(minutes=5):
            raise forms.ValidationError("The visit date cannot be in the future.")
        return visit

    def clean(self):
        cleaned = super().clean()
        patient, appointment = cleaned.get("patient"), cleaned.get("appointment")
        if patient and appointment and appointment.patient_id != patient.pk:
            self.add_error("appointment", "This appointment belongs to a different patient.")
        follow_up, visit = cleaned.get("follow_up_date"), cleaned.get("visit_date")
        if follow_up and visit and follow_up < timezone.localtime(visit).date():
            self.add_error("follow_up_date", "The follow-up date must be after the visit.")
        return cleaned


class PrescriptionForm(BootstrapModelForm):
    class Meta:
        model = Prescription
        fields = ["patient", "medical_record", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, user=None, doctor=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["patient"].queryset = visible_patients(user).filter(is_active=True).order_by("first_name")
        self.fields["medical_record"].queryset = (
            MedicalRecord.objects.filter(doctor=doctor).select_related("patient") if doctor else MedicalRecord.objects.none()
        )
        self.fields["medical_record"].required = False
        self.fields["medical_record"].label = "Linked medical record"

    def clean(self):
        cleaned = super().clean()
        patient, record = cleaned.get("patient"), cleaned.get("medical_record")
        if patient and record and record.patient_id != patient.pk:
            self.add_error("medical_record", "This record belongs to a different patient.")
        return cleaned


class PrescriptionItemForm(BootstrapModelForm):
    class Meta:
        model = PrescriptionItem
        fields = ["medicine", "medication_name", "dosage", "frequency", "duration", "quantity", "instructions"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["medicine"].queryset = Medicine.objects.filter(
            is_active=True, expiry_date__gte=timezone.localdate()
        ).order_by("name")
        self.fields["medicine"].required = False
        self.fields["medicine"].label = "Inventory item"
        self.fields["medicine"].label_from_instance = lambda m: f"{m.name} · batch {m.batch_number} · {m.quantity} {m.unit}"
        self.fields["medication_name"].required = False

    def clean(self):
        cleaned = super().clean()
        medicine = cleaned.get("medicine")
        if not cleaned.get("medication_name"):
            if medicine:
                cleaned["medication_name"] = medicine.name
            elif any(cleaned.get(f) for f in ("dosage", "frequency", "duration")):
                self.add_error("medication_name", "Enter the medication name or choose an inventory item.")
        if cleaned.get("quantity") and not medicine:
            self.add_error("quantity", "A dispense quantity requires a linked inventory item.")
        return cleaned


class BasePrescriptionItemFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        live = [
            f for f in self.forms
            if getattr(f, "cleaned_data", None) and not f.cleaned_data.get("DELETE") and f.cleaned_data.get("medication_name")
        ]
        if not live:
            raise forms.ValidationError("Add at least one medication to the prescription.")


PrescriptionItemFormSet = inlineformset_factory(
    Prescription,
    PrescriptionItem,
    form=PrescriptionItemForm,
    formset=BasePrescriptionItemFormSet,
    extra=1,
    can_delete=True,
)


class RecordFilterForm(BootstrapForm):
    q = forms.CharField(required=False, label="Search", widget=forms.TextInput(attrs={"placeholder": "Patient name, ID or diagnosis"}))
    doctor = forms.ModelChoiceField(queryset=Doctor.objects.all(), required=False, empty_label="All doctors")
    date_from = forms.DateField(required=False, widget=DateInput(), label="From")
    date_to = forms.DateField(required=False, widget=DateInput(), label="To")
