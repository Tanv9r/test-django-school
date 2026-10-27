from django.conf import settings
from django.db import models
from django.db.models import F, Q

from core.models import SequentialCodeMixin, TimeStampedModel


class Appointment(SequentialCodeMixin, TimeStampedModel):
    code_field = "reference"
    code_prefix = "APT-"

    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Scheduled"
        CONFIRMED = "confirmed", "Confirmed"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"
        NO_SHOW = "no_show", "No-show"

    # Statuses that occupy the doctor's time slot.
    BLOCKING_STATUSES = [Status.SCHEDULED, Status.CONFIRMED, Status.COMPLETED]
    OPEN_STATUSES = [Status.SCHEDULED, Status.CONFIRMED]
    TRANSITIONS = {
        Status.SCHEDULED: [Status.CONFIRMED, Status.COMPLETED, Status.CANCELLED, Status.NO_SHOW],
        Status.CONFIRMED: [Status.COMPLETED, Status.CANCELLED, Status.NO_SHOW],
    }

    reference = models.CharField(max_length=12, unique=True, null=True, blank=True, editable=False)
    patient = models.ForeignKey("patients.Patient", on_delete=models.PROTECT, related_name="appointments")
    doctor = models.ForeignKey("doctors.Doctor", on_delete=models.PROTECT, related_name="appointments")
    department = models.ForeignKey("doctors.Department", on_delete=models.PROTECT, related_name="appointments")
    start_at = models.DateTimeField(db_index=True)
    end_at = models.DateTimeField()
    reason = models.TextField(help_text="Reason for the visit.")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.SCHEDULED, db_index=True)
    notes = models.TextField(blank=True, help_text="Front-desk notes (not clinical).")
    cancellation_reason = models.CharField(max_length=255, blank=True)
    booked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="booked_appointments"
    )

    class Meta:
        ordering = ["-start_at"]
        indexes = [
            models.Index(fields=["doctor", "start_at"]),
            models.Index(fields=["status", "start_at"]),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(end_at__gt=F("start_at")), name="appointment_end_after_start"),
            # Database-level guard against double booking the same slot.
            models.UniqueConstraint(
                fields=["doctor", "start_at"],
                condition=Q(status__in=["scheduled", "confirmed", "completed"]),
                name="unique_active_doctor_slot",
            ),
        ]

    def __str__(self):
        return f"{self.reference or 'Appointment'} – {self.patient.full_name}"

    @property
    def is_open(self):
        return self.status in self.OPEN_STATUSES

    @property
    def allowed_transitions(self):
        return self.TRANSITIONS.get(self.status, [])
