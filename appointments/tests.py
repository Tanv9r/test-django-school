from datetime import time, timedelta

from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role
from appointments.models import Appointment
from appointments.services import SchedulingError, available_slots, change_status, local_dt
from core.testing import future_slot, make_appointment, make_doctor, make_patient, make_user


class AppointmentBookingTests(TestCase):
    def setUp(self):
        self.client.force_login(make_user(Role.RECEPTIONIST))
        self.doctor = make_doctor()
        self.patient = make_patient()
        self.day = timezone.localdate() + timedelta(days=3)

    def book(self, clock="10:00", patient=None, doctor=None):
        return self.client.post(reverse("appointments:create"), {
            "patient": (patient or self.patient).pk, "department": "", "doctor": (doctor or self.doctor).pk,
            "date": self.day.isoformat(), "time": clock, "reason": "Check-up", "notes": "",
        })

    def test_book_appointment(self):
        response = self.book()
        appt = Appointment.objects.get()
        self.assertRedirects(response, reverse("appointments:detail", args=[appt.pk]))
        self.assertEqual(appt.department, self.doctor.department)
        self.assertEqual(timezone.localtime(appt.start_at).time(), time(10, 0))
        self.assertEqual(appt.end_at - appt.start_at, timedelta(minutes=30))
        self.assertTrue(appt.reference.startswith("APT-"))

    def test_conflicting_slot_for_same_doctor_rejected(self):
        self.book("10:00")
        response = self.book("10:15", patient=make_patient(first_name="Second"))
        self.assertEqual(Appointment.objects.count(), 1)
        self.assertTrue(response.context["form"].non_field_errors())

    def test_adjacent_slot_allowed(self):
        self.book("10:00")
        self.book("10:30", patient=make_patient(first_name="Second"))
        self.assertEqual(Appointment.objects.count(), 2)

    def test_patient_double_booking_rejected(self):
        self.book("10:00")
        other_doctor = make_doctor(first_name="Other", last_name="Doc")
        self.book("10:00", doctor=other_doctor)
        self.assertEqual(Appointment.objects.count(), 1)

    def test_outside_working_hours_rejected(self):
        response = self.book("20:00")
        self.assertFalse(Appointment.objects.exists())
        self.assertIn("not available", str(response.context["form"].non_field_errors()))

    def test_doctor_not_working_that_day_rejected(self):
        doctor = make_doctor(all_week=False, first_name="Part", last_name="Timer")
        self.book("10:00", doctor=doctor)
        self.assertFalse(Appointment.objects.exists())

    def test_past_time_rejected(self):
        self.day = timezone.localdate() - timedelta(days=1)
        self.book("10:00")
        self.assertFalse(Appointment.objects.exists())

    def test_cancelled_slot_can_be_rebooked(self):
        appt = make_appointment(self.patient, self.doctor, start=local_dt(self.day, time(10)))
        change_status(appt, Appointment.Status.CANCELLED, "Patient request")
        self.book("10:00", patient=make_patient(first_name="Second"))
        self.assertEqual(Appointment.objects.filter(status="scheduled").count(), 1)

    def test_database_constraint_prevents_double_booking(self):
        start = future_slot()
        make_appointment(self.patient, self.doctor, start=start)
        with self.assertRaises(IntegrityError):
            make_appointment(make_patient(first_name="X"), self.doctor, start=start)

    def test_available_slots_exclude_booked(self):
        make_appointment(self.patient, self.doctor, start=local_dt(self.day, time(10)))
        slots = [timezone.localtime(s).strftime("%H:%M") for s in available_slots(self.doctor, self.day)]
        self.assertNotIn("10:00", slots)
        self.assertIn("10:30", slots)
        response = self.client.get(reverse("appointments:slots"), {"doctor": self.doctor.pk, "date": self.day.isoformat()})
        self.assertNotIn("10:00", response.json()["slots"])

    def test_reschedule(self):
        appt = make_appointment(self.patient, self.doctor, start=local_dt(self.day, time(10)))
        response = self.client.post(reverse("appointments:edit", args=[appt.pk]), {
            "patient": self.patient.pk, "department": self.doctor.department.pk, "doctor": self.doctor.pk,
            "date": self.day.isoformat(), "time": "11:00", "reason": "Moved", "notes": "",
        })
        self.assertEqual(response.status_code, 302)
        appt.refresh_from_db()
        self.assertEqual(timezone.localtime(appt.start_at).time(), time(11, 0))


class AppointmentStatusTests(TestCase):
    def test_transitions(self):
        doctor, patient = make_doctor(), make_patient()
        future = make_appointment(patient, doctor)
        with self.assertRaises(SchedulingError):
            change_status(future, Appointment.Status.COMPLETED)
        change_status(future, Appointment.Status.CONFIRMED)
        change_status(future, Appointment.Status.CANCELLED, "No longer needed")
        with self.assertRaises(SchedulingError):
            change_status(future, Appointment.Status.CONFIRMED)
        past = make_appointment(patient, doctor, start=timezone.now() - timedelta(hours=3))
        change_status(past, Appointment.Status.COMPLETED)
        self.assertEqual(past.status, Appointment.Status.COMPLETED)

    def test_doctor_sees_only_own_appointments(self):
        user = make_user(Role.DOCTOR)
        mine = make_doctor(user=user)
        other = make_doctor(first_name="Other", last_name="Doc")
        patient = make_patient()
        make_appointment(patient, mine)
        theirs = make_appointment(make_patient(first_name="B"), other)
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse("appointments:detail", args=[theirs.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("appointments:create")).status_code, 403)
