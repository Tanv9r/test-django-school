from datetime import date

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from accounts.models import phone_validator
from core.models import SequentialCodeMixin, TimeStampedModel


def validate_birth_date(value):
    today = timezone.localdate()
    if value > today:
        raise ValidationError("Date of birth cannot be in the future.")
    if value < date(today.year - 130, 1, 1):
        raise ValidationError("Please enter a realistic date of birth.")


class Patient(SequentialCodeMixin, TimeStampedModel):
    code_field = "patient_id"
    code_prefix = "PT-"

    class Gender(models.TextChoices):
        MALE = "M", "Male"
        FEMALE = "F", "Female"
        OTHER = "O", "Other"

    class BloodGroup(models.TextChoices):
        A_POS = "A+", "A+"
        A_NEG = "A-", "A-"
        B_POS = "B+", "B+"
        B_NEG = "B-", "B-"
        AB_POS = "AB+", "AB+"
        AB_NEG = "AB-", "AB-"
        O_POS = "O+", "O+"
        O_NEG = "O-", "O-"
        UNKNOWN = "UNK", "Unknown"

    patient_id = models.CharField("Patient ID", max_length=12, unique=True, null=True, blank=True, editable=False)
    first_name = models.CharField(max_length=60)
    last_name = models.CharField(max_length=60)
    date_of_birth = models.DateField(validators=[validate_birth_date])
    gender = models.CharField(max_length=1, choices=Gender.choices)
    phone = models.CharField(max_length=20, validators=[phone_validator])
    email = models.EmailField(blank=True)
    address = models.TextField()
    emergency_contact_name = models.CharField(max_length=120)
    emergency_contact_phone = models.CharField(max_length=20, validators=[phone_validator])
    emergency_contact_relation = models.CharField(max_length=50, blank=True)

    # Basic medical information captured at registration.
    blood_group = models.CharField(max_length=3, choices=BloodGroup.choices, default=BloodGroup.UNKNOWN)
    allergies = models.TextField(blank=True, help_text="Known allergies, one per line.")
    chronic_conditions = models.TextField(blank=True)
    current_medications = models.TextField(blank=True)

    is_active = models.BooleanField(default=True, db_index=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    registered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="registered_patients"
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["last_name", "first_name"]),
            models.Index(fields=["phone"]),
        ]

    def __str__(self):
        return f"{self.full_name} ({self.patient_id})" if self.patient_id else self.full_name

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def age(self):
        today = timezone.localdate()
        dob = self.date_of_birth
        return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
