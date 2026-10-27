from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role
from admissions.models import Admission, Bed
from admissions.services import AdmissionError, admit_patient, discharge_patient
from core.testing import make_bed, make_doctor, make_patient, make_user


class BedAssignmentTests(TestCase):
    def setUp(self):
        self.user = make_user(Role.RECEPTIONIST)
        self.doctor = make_doctor()
        self.bed = make_bed()

    def admit(self, patient, bed=None):
        return admit_patient(patient=patient, bed=bed or self.bed, doctor=self.doctor, reason="Observation", user=self.user)

    def test_admission_occupies_bed_and_discharge_releases_it(self):
        admission = self.admit(make_patient())
        self.bed.refresh_from_db()
        self.assertEqual(self.bed.status, Bed.Status.OCCUPIED)
        discharge_patient(admission, summary="Recovered", user=self.user)
        self.bed.refresh_from_db()
        admission.refresh_from_db()
        self.assertEqual(self.bed.status, Bed.Status.AVAILABLE)
        self.assertEqual(admission.status, Admission.Status.DISCHARGED)
        self.assertIsNotNone(admission.discharged_at)

    def test_occupied_bed_cannot_be_assigned(self):
        self.admit(make_patient())
        with self.assertRaises(AdmissionError):
            self.admit(make_patient(first_name="Second"))
        self.assertEqual(Admission.objects.count(), 1)

    def test_maintenance_bed_cannot_be_assigned(self):
        self.bed.status = Bed.Status.MAINTENANCE
        self.bed.save()
        with self.assertRaises(AdmissionError):
            self.admit(make_patient())

    def test_patient_cannot_be_admitted_twice(self):
        patient = make_patient()
        self.admit(patient)
        with self.assertRaises(AdmissionError):
            self.admit(patient, bed=make_bed(bed_number="2"))

    def test_cannot_discharge_twice(self):
        admission = self.admit(make_patient())
        discharge_patient(admission, summary="Done", user=self.user)
        with self.assertRaises(AdmissionError):
            discharge_patient(admission, summary="Again", user=self.user)

    def test_db_constraint_one_active_admission_per_bed(self):
        self.admit(make_patient())
        with self.assertRaises(IntegrityError), transaction.atomic():
            Admission.objects.create(patient=make_patient(first_name="X"), bed=self.bed, attending_doctor=self.doctor, reason="r")

    def test_admit_and_discharge_through_views(self):
        self.client.force_login(self.user)
        patient = make_patient()
        response = self.client.post(reverse("admissions:create"), {
            "patient": patient.pk, "bed": self.bed.pk, "attending_doctor": self.doctor.pk, "assigned_nurse": "",
            "admitted_at": timezone.localtime().strftime("%Y-%m-%dT%H:%M"), "reason": "Pneumonia",
        })
        admission = Admission.objects.get()
        self.assertRedirects(response, reverse("admissions:detail", args=[admission.pk]))
        # occupied bed is no longer offered
        self.assertNotIn(self.bed, self.client.get(reverse("admissions:create")).context["form"].fields["bed"].queryset)
        self.client.post(reverse("admissions:discharge", args=[admission.pk]), {
            "discharged_at": timezone.localtime().strftime("%Y-%m-%dT%H:%M"), "discharge_summary": "Stable",
        })
        self.bed.refresh_from_db()
        self.assertEqual(self.bed.status, Bed.Status.AVAILABLE)

    def test_nurse_sees_only_assigned_admissions(self):
        nurse, other_nurse = make_user(Role.NURSE), make_user(Role.NURSE)
        mine = admit_patient(patient=make_patient(), bed=self.bed, doctor=self.doctor, reason="r", user=self.user, nurse=nurse)
        theirs = admit_patient(patient=make_patient(first_name="B"), bed=make_bed(bed_number="2"), doctor=self.doctor, reason="r", user=self.user, nurse=other_nurse)
        self.client.force_login(nurse)
        self.assertEqual(self.client.get(reverse("admissions:detail", args=[mine.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("admissions:detail", args=[theirs.pk])).status_code, 404)
