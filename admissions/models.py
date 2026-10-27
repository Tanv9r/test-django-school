import math
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from accounts.models import Role
from core.models import SequentialCodeMixin, TimeStampedModel


class RoomType(models.Model):
    name = models.CharField(max_length=80, unique=True, help_text="e.g. General Ward, Private, ICU")
    description = models.CharField(max_length=255, blank=True)
    daily_rate = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0"))])
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        constraints = [models.CheckConstraint(condition=Q(daily_rate__gte=0), name="room_rate_non_negative")]

    def __str__(self):
        return self.name


class Room(TimeStampedModel):
    number = models.CharField(max_length=20, unique=True)
    room_type = models.ForeignKey(RoomType, on_delete=models.PROTECT, related_name="rooms")
    department = models.ForeignKey(
        "doctors.Department", null=True, blank=True, on_delete=models.SET_NULL, related_name="rooms"
    )
    floor = models.CharField(max_length=20, blank=True)
    notes = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["number"]

    def __str__(self):
        return f"Room {self.number} ({self.room_type})"


class Bed(TimeStampedModel):
    class Status(models.TextChoices):
        AVAILABLE = "available", "Available"
        OCCUPIED = "occupied", "Occupied"
        MAINTENANCE = "maintenance", "Maintenance"

    room = models.ForeignKey(Room, on_delete=models.PROTECT, related_name="beds")
    bed_number = models.CharField(max_length=10)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.AVAILABLE, db_index=True)

    class Meta:
        ordering = ["room__number", "bed_number"]
        constraints = [models.UniqueConstraint(fields=["room", "bed_number"], name="unique_bed_per_room")]

    def __str__(self):
        return f"{self.room.number}-{self.bed_number}"

    @property
    def label(self):
        return f"Room {self.room.number} · Bed {self.bed_number}"


class Admission(SequentialCodeMixin, TimeStampedModel):
    code_field = "admission_number"
    code_prefix = "ADM-"

    class Status(models.TextChoices):
        ADMITTED = "admitted", "Admitted"
        DISCHARGED = "discharged", "Discharged"

    admission_number = models.CharField(max_length=12, unique=True, null=True, blank=True, editable=False)
    patient = models.ForeignKey("patients.Patient", on_delete=models.PROTECT, related_name="admissions")
    bed = models.ForeignKey(Bed, on_delete=models.PROTECT, related_name="admissions")
    attending_doctor = models.ForeignKey("doctors.Doctor", on_delete=models.PROTECT, related_name="admissions")
    assigned_nurse = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="nursing_admissions",
        limit_choices_to={"role": Role.NURSE},
    )
    admitted_at = models.DateTimeField(default=timezone.now, db_index=True)
    reason = models.TextField(help_text="Reason for admission.")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ADMITTED, db_index=True)
    discharged_at = models.DateTimeField(null=True, blank=True, db_index=True)
    discharge_summary = models.TextField(blank=True)
    admitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    discharged_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-admitted_at"]
        constraints = [
            models.UniqueConstraint(fields=["bed"], condition=Q(status="admitted"), name="one_active_admission_per_bed"),
            models.UniqueConstraint(fields=["patient"], condition=Q(status="admitted"), name="one_active_admission_per_patient"),
            models.CheckConstraint(
                condition=Q(discharged_at__isnull=True) | Q(discharged_at__gte=F("admitted_at")),
                name="discharge_after_admission",
            ),
        ]

    def __str__(self):
        return f"{self.admission_number} – {self.patient.full_name}"

    @property
    def length_of_stay_days(self) -> int:
        """Billable days: any started day counts, minimum one."""
        end = self.discharged_at or timezone.now()
        seconds = max((end - self.admitted_at).total_seconds(), 0)
        return max(1, math.ceil(seconds / 86400))


class NursingTask(TimeStampedModel):
    class Priority(models.TextChoices):
        LOW = "low", "Low"
        NORMAL = "normal", "Normal"
        HIGH = "high", "High"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        IN_PROGRESS = "in_progress", "In progress"
        DONE = "done", "Done"

    admission = models.ForeignKey(Admission, on_delete=models.PROTECT, related_name="tasks")
    title = models.CharField(max_length=150, help_text="e.g. Check vitals every 4 hours")
    details = models.TextField(blank=True)
    due_at = models.DateTimeField(null=True, blank=True)
    priority = models.CharField(max_length=8, choices=Priority.choices, default=Priority.NORMAL)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="nursing_tasks",
        limit_choices_to={"role": Role.NURSE},
    )
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["status", "due_at", "-priority"]

    def __str__(self):
        return self.title
