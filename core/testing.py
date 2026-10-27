"""Shared factories for the test suite."""
from datetime import date, time, timedelta
from decimal import Decimal

from django.utils import timezone

from accounts.models import Role, User
from admissions.models import Bed, Room, RoomType
from appointments.models import Appointment
from appointments.services import local_dt
from doctors.models import Department, Doctor, DoctorAvailability
from patients.models import Patient
from pharmacy.models import Medicine, MedicineCategory

PASSWORD = "S3cure-Pass!word"


def make_user(role=Role.RECEPTIONIST, username=None, **extra):
    username = username or f"{role}_{User.objects.count() + 1}"
    return User.objects.create_user(username=username, password=PASSWORD, role=role, first_name="Test", last_name=role.title(), **extra)


def make_department(name="Cardiology"):
    return Department.objects.get_or_create(name=name)[0]


def make_doctor(user=None, all_week=True, **extra):
    doctor = Doctor.objects.create(
        first_name=extra.pop("first_name", "Greg"), last_name=extra.pop("last_name", "House"),
        phone="+1 555 000 1111", specialization="Diagnostics", qualifications="MD",
        department=extra.pop("department", None) or make_department(), consultation_fee=Decimal("100.00"),
        slot_minutes=30, user=user, **extra,
    )
    if all_week:
        for weekday in range(7):
            DoctorAvailability.objects.create(doctor=doctor, weekday=weekday, start_time=time(8), end_time=time(18))
    return doctor


def make_patient(**extra):
    defaults = dict(
        first_name="Jane", last_name="Doe", date_of_birth=date(1990, 5, 17), gender="F", phone="+1 555 222 3333",
        address="1 Test Street", emergency_contact_name="John Doe", emergency_contact_phone="+1 555 444 5555",
    )
    defaults.update(extra)
    return Patient.objects.create(**defaults)


def future_slot(days=2, hour=10, minute=0):
    return local_dt(timezone.localdate() + timedelta(days=days), time(hour, minute))


def make_appointment(patient, doctor, start=None, status=Appointment.Status.SCHEDULED):
    start = start or future_slot()
    return Appointment.objects.create(
        patient=patient, doctor=doctor, department=doctor.department, start_at=start,
        end_at=start + timedelta(minutes=doctor.slot_minutes), reason="Check-up", status=status,
    )


def make_bed(number="101", bed_number="1"):
    room_type = RoomType.objects.get_or_create(name="Test Ward", defaults={"daily_rate": Decimal("50.00")})[0]
    room = Room.objects.get_or_create(number=number, defaults={"room_type": room_type})[0]
    return Bed.objects.create(room=room, bed_number=bed_number)


def make_medicine(**extra):
    category = MedicineCategory.objects.get_or_create(name="Test Category")[0]
    defaults = dict(
        name="Testamol", category=category, manufacturer="Acme", batch_number="T-1", unit_price=Decimal("1.50"),
        expiry_date=timezone.localdate() + timedelta(days=365), reorder_level=5,
    )
    defaults.update(extra)
    return Medicine.objects.create(**defaults)
