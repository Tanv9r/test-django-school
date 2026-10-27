from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q

from accounts.models import Role, phone_validator
from core.models import SequentialCodeMixin, TimeStampedModel


class Department(TimeStampedModel):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    location = models.CharField(max_length=100, blank=True, help_text="e.g. Block B, 2nd floor")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Doctor(SequentialCodeMixin, TimeStampedModel):
    code_field = "doctor_code"
    code_prefix = "DR-"
    code_width = 4

    SLOT_CHOICES = [(10, "10 minutes"), (15, "15 minutes"), (20, "20 minutes"), (30, "30 minutes"), (45, "45 minutes"), (60, "60 minutes")]

    doctor_code = models.CharField(max_length=12, unique=True, null=True, blank=True, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="doctor_profile",
        limit_choices_to={"role": Role.DOCTOR},
        help_text="Login account used by this doctor (role must be Doctor).",
    )
    first_name = models.CharField(max_length=60)
    last_name = models.CharField(max_length=60)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=20, validators=[phone_validator])
    specialization = models.CharField(max_length=120)
    qualifications = models.CharField(max_length=255, help_text="e.g. MBBS, MD (Cardiology)")
    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="doctors")
    consultation_fee = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0.00"), validators=[MinValueValidator(Decimal("0"))]
    )
    slot_minutes = models.PositiveSmallIntegerField(
        choices=SLOT_CHOICES, default=30, help_text="Length of one appointment slot."
    )
    bio = models.TextField(blank=True)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ["last_name", "first_name"]
        indexes = [models.Index(fields=["last_name", "first_name"])]
        constraints = [
            models.CheckConstraint(condition=Q(consultation_fee__gte=0), name="doctor_fee_non_negative"),
        ]

    def __str__(self):
        return f"Dr. {self.first_name} {self.last_name}"

    @property
    def full_name(self):
        return str(self)


class DoctorAvailability(models.Model):
    class Weekday(models.IntegerChoices):
        MONDAY = 0, "Monday"
        TUESDAY = 1, "Tuesday"
        WEDNESDAY = 2, "Wednesday"
        THURSDAY = 3, "Thursday"
        FRIDAY = 4, "Friday"
        SATURDAY = 5, "Saturday"
        SUNDAY = 6, "Sunday"

    doctor = models.ForeignKey(Doctor, on_delete=models.CASCADE, related_name="availability")
    weekday = models.PositiveSmallIntegerField(choices=Weekday.choices)
    start_time = models.TimeField()
    end_time = models.TimeField()

    class Meta:
        ordering = ["weekday", "start_time"]
        verbose_name_plural = "doctor availability"
        constraints = [
            models.CheckConstraint(condition=Q(end_time__gt=F("start_time")), name="availability_end_after_start"),
            models.UniqueConstraint(fields=["doctor", "weekday", "start_time"], name="unique_availability_start"),
        ]

    def __str__(self):
        return f"{self.get_weekday_display()} {self.start_time:%H:%M}–{self.end_time:%H:%M}"
