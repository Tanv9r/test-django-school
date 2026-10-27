from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role
from core.models import AuditLog
from core.testing import make_appointment, make_doctor, make_patient, make_user
from patients.models import Patient
from patients.selectors import visible_patients

VALID = {
    "first_name": "alice", "last_name": "smith", "date_of_birth": "1985-02-03", "gender": "F",
    "phone": "+1 555 123 4567", "email": "alice@example.com", "address": "5 Main St",
    "emergency_contact_name": "Bob Smith", "emergency_contact_phone": "+1 555 765 4321",
    "emergency_contact_relation": "Brother", "blood_group": "O+", "allergies": "", "chronic_conditions": "", "current_medications": "",
}


class PatientRegistrationTests(TestCase):
    def setUp(self):
        self.receptionist = make_user(Role.RECEPTIONIST)
        self.client.force_login(self.receptionist)

    def test_register_patient_generates_unique_id(self):
        response = self.client.post(reverse("patients:create"), VALID)
        patient = Patient.objects.get()
        self.assertRedirects(response, reverse("patients:detail", args=[patient.pk]))
        self.assertEqual(patient.patient_id, f"PT-{patient.pk:06d}")
        self.assertEqual(patient.first_name, "Alice")  # normalised
        self.assertEqual(patient.registered_by, self.receptionist)
        self.assertTrue(AuditLog.objects.filter(action="create", object_id=str(patient.pk)).exists())

    def test_ids_are_unique_across_patients(self):
        ids = {make_patient(first_name=f"P{i}").patient_id for i in range(5)}
        self.assertEqual(len(ids), 5)

    def test_future_birth_date_rejected(self):
        data = {**VALID, "date_of_birth": (timezone.localdate().replace(year=timezone.localdate().year + 1)).isoformat()}
        response = self.client.post(reverse("patients:create"), data)
        self.assertEqual(response.status_code, 200)
        self.assertIn("date_of_birth", response.context["form"].errors)
        self.assertFalse(Patient.objects.exists())

    def test_required_fields_and_phone_validation(self):
        response = self.client.post(reverse("patients:create"), {**VALID, "phone": "abc", "address": ""})
        errors = response.context["form"].errors
        self.assertIn("phone", errors)
        self.assertIn("address", errors)

    def test_duplicate_patient_rejected(self):
        self.client.post(reverse("patients:create"), VALID)
        response = self.client.post(reverse("patients:create"), VALID)
        self.assertEqual(Patient.objects.count(), 1)
        self.assertTrue(response.context["form"].non_field_errors())

    def test_edit_and_archive(self):
        patient = make_patient()
        response = self.client.post(reverse("patients:edit", args=[patient.pk]), {**VALID, "first_name": "Janet", "last_name": "Doe", "date_of_birth": "1990-05-17"})
        self.assertEqual(response.status_code, 302)
        patient.refresh_from_db()
        self.assertEqual(patient.first_name, "Janet")
        self.client.post(reverse("patients:toggle_archive", args=[patient.pk]))
        patient.refresh_from_db()
        self.assertFalse(patient.is_active)
        self.assertNotContains(self.client.get(reverse("patients:list")), "Janet Doe")

    def test_search(self):
        make_patient(first_name="Zelda", last_name="Unique")
        make_patient(first_name="Other", last_name="Person")
        response = self.client.get(reverse("patients:list"), {"q": "zelda"})
        self.assertContains(response, "Zelda Unique")
        self.assertNotContains(response, "Other Person")


class PatientVisibilityTests(TestCase):
    def test_doctor_sees_only_assigned_patients(self):
        doctor_user = make_user(Role.DOCTOR)
        doctor = make_doctor(user=doctor_user)
        mine, other = make_patient(first_name="Mine"), make_patient(first_name="Other")
        make_appointment(mine, doctor)
        self.assertEqual(list(visible_patients(doctor_user)), [mine])
        self.client.force_login(doctor_user)
        self.assertEqual(self.client.get(reverse("patients:detail", args=[other.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("patients:detail", args=[mine.pk])).status_code, 200)

    def test_accountant_does_not_see_clinical_details(self):
        patient = make_patient(allergies="Penicillin-XYZ")
        self.client.force_login(make_user(Role.ACCOUNTANT))
        response = self.client.get(reverse("patients:detail", args=[patient.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Penicillin-XYZ")
        self.assertEqual(self.client.get(reverse("patients:create")).status_code, 403)
