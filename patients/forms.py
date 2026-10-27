from django import forms

from core.forms import BootstrapForm, BootstrapModelForm, DateInput

from .models import Patient

CLINICAL_FIELDS = ["blood_group", "allergies", "chronic_conditions", "current_medications"]


class PatientForm(BootstrapModelForm):
    class Meta:
        model = Patient
        fields = [
            "first_name",
            "last_name",
            "date_of_birth",
            "gender",
            "phone",
            "email",
            "address",
            "emergency_contact_name",
            "emergency_contact_phone",
            "emergency_contact_relation",
            *CLINICAL_FIELDS,
        ]
        widgets = {
            "date_of_birth": DateInput(),
            "address": forms.Textarea(attrs={"rows": 2}),
            "allergies": forms.Textarea(attrs={"rows": 2, "placeholder": "e.g. Penicillin"}),
            "chronic_conditions": forms.Textarea(attrs={"rows": 2}),
            "current_medications": forms.Textarea(attrs={"rows": 2}),
        }

    def clean_first_name(self):
        return " ".join(self.cleaned_data["first_name"].split()).title()

    def clean_last_name(self):
        return " ".join(self.cleaned_data["last_name"].split()).title()

    def clean(self):
        cleaned = super().clean()
        first, last, dob = cleaned.get("first_name"), cleaned.get("last_name"), cleaned.get("date_of_birth")
        if first and last and dob:
            duplicate = (
                Patient.objects.filter(first_name__iexact=first, last_name__iexact=last, date_of_birth=dob)
                .exclude(pk=self.instance.pk)
                .first()
            )
            if duplicate:
                raise forms.ValidationError(
                    f"A patient with the same name and date of birth is already registered ({duplicate.patient_id}). "
                    "Please open the existing record instead of creating a duplicate."
                )
        phone, emergency = cleaned.get("phone"), cleaned.get("emergency_contact_phone")
        if phone and emergency and phone == emergency:
            self.add_error("emergency_contact_phone", "The emergency contact must have a different phone number.")
        return cleaned


class PatientFilterForm(BootstrapForm):
    q = forms.CharField(
        required=False, label="Search", widget=forms.TextInput(attrs={"placeholder": "Name, patient ID, phone or email"})
    )
    gender = forms.ChoiceField(required=False, choices=[("", "Any gender"), *Patient.Gender.choices])
    blood_group = forms.ChoiceField(required=False, choices=[("", "Any blood group"), *Patient.BloodGroup.choices])
    status = forms.ChoiceField(
        required=False, choices=[("active", "Active"), ("archived", "Archived"), ("all", "All")], initial="active"
    )
