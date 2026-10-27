from django.conf import settings
from django.db import models

from accounts.models import phone_validator
from core.models import SequentialCodeMixin, TimeStampedModel


class StaffProfile(SequentialCodeMixin, TimeStampedModel):
    """Employment record. Login credentials live on the separate ``accounts.User``."""

    code_field = "employee_id"
    code_prefix = "EMP-"
    code_width = 4

    class EmploymentStatus(models.TextChoices):
        ACTIVE = "active", "Active"
        ON_LEAVE = "on_leave", "On leave"
        SUSPENDED = "suspended", "Suspended"
        TERMINATED = "terminated", "Terminated"

    employee_id = models.CharField(max_length=12, unique=True, null=True, blank=True, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="staff_profile",
        help_text="Optional login account giving this person system access.",
    )
    first_name = models.CharField(max_length=60)
    last_name = models.CharField(max_length=60)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=20, validators=[phone_validator])
    job_title = models.CharField(max_length=100)
    department = models.ForeignKey(
        "doctors.Department", null=True, blank=True, on_delete=models.SET_NULL, related_name="staff"
    )
    joining_date = models.DateField()
    employment_status = models.CharField(
        max_length=12, choices=EmploymentStatus.choices, default=EmploymentStatus.ACTIVE, db_index=True
    )
    address = models.TextField(blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["last_name", "first_name"]

    def __str__(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def full_name(self):
        return str(self)
