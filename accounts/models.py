from django.contrib.auth.models import AbstractUser
from django.core.validators import RegexValidator
from django.db import models

phone_validator = RegexValidator(
    r"^\+?[0-9][0-9\s\-()]{6,19}$", "Enter a valid phone number (digits, spaces, dashes, optional leading +)."
)


class Role(models.TextChoices):
    ADMIN = "admin", "Administrator"
    DOCTOR = "doctor", "Doctor"
    NURSE = "nurse", "Nurse"
    RECEPTIONIST = "receptionist", "Receptionist"
    PHARMACIST = "pharmacist", "Pharmacist"
    ACCOUNTANT = "accountant", "Accountant"


class User(AbstractUser):
    """Login account. Employment details live separately in ``staff.StaffProfile``."""

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.RECEPTIONIST, db_index=True)
    phone = models.CharField(max_length=20, blank=True, validators=[phone_validator])

    class Meta:
        ordering = ["first_name", "last_name", "username"]

    def save(self, *args, **kwargs):
        # Superusers created with ``createsuperuser`` are always administrators.
        if self.is_superuser:
            self.role = Role.ADMIN
        super().save(*args, **kwargs)

    def __str__(self):
        return self.get_full_name() or self.username

    @property
    def effective_role(self) -> str:
        return Role.ADMIN if self.is_superuser else self.role

    @property
    def is_admin(self) -> bool:
        return self.effective_role == Role.ADMIN

    @property
    def display_name(self) -> str:
        name = self.get_full_name() or self.username
        return f"Dr. {name}" if self.role == Role.DOCTOR else name
