"""Scheduling rules: availability, conflicts and status changes."""
from datetime import datetime, time, timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import Appointment


class SchedulingError(Exception):
    pass


def local_dt(day, clock):
    """Combine a date and time in the configured local time zone into an aware datetime."""
    return timezone.make_aware(datetime.combine(day, clock), timezone.get_current_timezone())


def doctor_conflicts(doctor, start, end, exclude_pk=None):
    return (
        Appointment.objects.filter(
            doctor=doctor, status__in=Appointment.BLOCKING_STATUSES, start_at__lt=end, end_at__gt=start
        ).exclude(pk=exclude_pk)
    )


def patient_conflicts(patient, start, end, exclude_pk=None):
    return (
        Appointment.objects.filter(
            patient=patient, status__in=Appointment.OPEN_STATUSES, start_at__lt=end, end_at__gt=start
        ).exclude(pk=exclude_pk)
    )


def is_within_availability(doctor, start, end) -> bool:
    """True if [start, end) falls entirely inside one of the doctor's working-hour windows."""
    local_start, local_end = timezone.localtime(start), timezone.localtime(end)
    if local_start.date() != local_end.date():
        return False
    return doctor.availability.filter(
        weekday=local_start.weekday(), start_time__lte=local_start.time(), end_time__gte=local_end.time()
    ).exists()


def available_slots(doctor, day, exclude_pk=None):
    """Free, future slots for ``doctor`` on ``day`` (a date in local time)."""
    step = timedelta(minutes=doctor.slot_minutes)
    day_start = local_dt(day, time.min)
    booked = list(
        Appointment.objects.filter(
            doctor=doctor,
            status__in=Appointment.BLOCKING_STATUSES,
            start_at__lt=day_start + timedelta(days=1),
            end_at__gt=day_start,
        )
        .exclude(pk=exclude_pk)
        .values_list("start_at", "end_at")
    )
    now = timezone.now()
    slots = []
    for window in doctor.availability.filter(weekday=day.weekday()):
        cursor, window_end = local_dt(day, window.start_time), local_dt(day, window.end_time)
        while cursor + step <= window_end:
            slot_end = cursor + step
            if cursor > now and not any(s < slot_end and e > cursor for s, e in booked):
                slots.append(cursor)
            cursor = slot_end
    return slots


def save_appointment(appointment, user=None):
    """Persist a validated appointment, re-checking conflicts inside the write transaction."""
    try:
        with transaction.atomic():
            if doctor_conflicts(appointment.doctor, appointment.start_at, appointment.end_at, appointment.pk).exists():
                raise SchedulingError("The doctor already has an appointment in this time slot.")
            if patient_conflicts(appointment.patient, appointment.start_at, appointment.end_at, appointment.pk).exists():
                raise SchedulingError("The patient already has another appointment at this time.")
            if appointment.pk is None and user is not None:
                appointment.booked_by = user
            appointment.save()
    except IntegrityError as exc:
        raise SchedulingError("This time slot was just booked by someone else. Please choose another slot.") from exc
    return appointment


def change_status(appointment, new_status, reason=""):
    if new_status not in appointment.allowed_transitions:
        raise SchedulingError(
            f"An appointment that is {appointment.get_status_display().lower()} cannot be marked as "
            f"{Appointment.Status(new_status).label.lower()}."
        )
    if new_status in (Appointment.Status.COMPLETED, Appointment.Status.NO_SHOW) and appointment.start_at > timezone.now():
        raise SchedulingError("Only appointments whose start time has passed can be completed or marked as no-show.")
    appointment.status = new_status
    if new_status == Appointment.Status.CANCELLED:
        appointment.cancellation_reason = reason[:255]
    appointment.save(update_fields=["status", "cancellation_reason", "updated_at"])
    return appointment
