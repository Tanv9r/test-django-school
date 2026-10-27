from django.conf import settings
from django.db import models
from django.utils import timezone

from core.models import SequentialCodeMixin, TimeStampedModel


class MedicalRecord(TimeStampedModel):
    """A clinical encounter note entered by a qualified doctor."""

    patient = models.ForeignKey("patients.Patient", on_delete=models.PROTECT, related_name="medical_records")
    doctor = models.ForeignKey("doctors.Doctor", on_delete=models.PROTECT, related_name="medical_records")
    appointment = models.ForeignKey(
        "appointments.Appointment", null=True, blank=True, on_delete=models.SET_NULL, related_name="medical_records"
    )
    visit_date = models.DateTimeField(default=timezone.now, db_index=True)
    symptoms = models.TextField()
    visit_notes = models.TextField(blank=True)
    diagnosis = models.TextField()
    treatment_plan = models.TextField(blank=True)
    follow_up_instructions = models.TextField(blank=True)
    follow_up_date = models.DateField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["-visit_date"]
        indexes = [models.Index(fields=["patient", "visit_date"])]

    def __str__(self):
        return f"Record #{self.pk} – {self.patient.full_name} ({timezone.localtime(self.visit_date):%d %b %Y})"


class Prescription(SequentialCodeMixin, TimeStampedModel):
    code_field = "prescription_number"
    code_prefix = "RX-"

    class Status(models.TextChoices):
        ACTIVE = "active", "Awaiting dispensing"
        DISPENSED = "dispensed", "Dispensed"
        CANCELLED = "cancelled", "Cancelled"

    prescription_number = models.CharField(max_length=12, unique=True, null=True, blank=True, editable=False)
    patient = models.ForeignKey("patients.Patient", on_delete=models.PROTECT, related_name="prescriptions")
    doctor = models.ForeignKey("doctors.Doctor", on_delete=models.PROTECT, related_name="prescriptions")
    medical_record = models.ForeignKey(
        MedicalRecord, null=True, blank=True, on_delete=models.SET_NULL, related_name="prescriptions"
    )
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    dispensed_at = models.DateTimeField(null=True, blank=True)
    dispensed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.prescription_number} – {self.patient.full_name}"


class PrescriptionItem(models.Model):
    prescription = models.ForeignKey(Prescription, on_delete=models.CASCADE, related_name="items")
    medicine = models.ForeignKey(
        "pharmacy.Medicine",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="prescription_items",
        help_text="Link to inventory so the pharmacy can dispense from stock.",
    )
    medication_name = models.CharField(max_length=150)
    dosage = models.CharField(max_length=60, help_text="e.g. 500 mg")
    frequency = models.CharField(max_length=60, help_text="e.g. Twice daily")
    duration = models.CharField(max_length=60, help_text="e.g. 7 days")
    quantity = models.PositiveIntegerField(default=0, help_text="Units to dispense (0 = not dispensed from stock).")
    instructions = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["pk"]

    def __str__(self):
        return f"{self.medication_name} {self.dosage}"
