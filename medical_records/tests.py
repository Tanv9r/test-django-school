from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role
from admissions.services import admit_patient
from core.models import AuditLog
from core.testing import make_appointment, make_bed, make_doctor, make_medicine, make_patient, make_user
from medical_records.models import MedicalRecord, Prescription, PrescriptionItem
from medical_records.services import dispense_prescription
from pharmacy.models import StockTransaction
from pharmacy.services import StockError, adjust_stock


class MedicalRecordAccessTests(TestCase):
    def setUp(self):
        self.doctor_user = make_user(Role.DOCTOR)
        self.doctor = make_doctor(user=self.doctor_user)
        self.patient = make_patient()
        make_appointment(self.patient, self.doctor)
        self.record = MedicalRecord.objects.create(patient=self.patient, doctor=self.doctor, symptoms="Cough", diagnosis="Secret-Diagnosis-123")

    def test_non_clinical_roles_cannot_view_records(self):
        for role in (Role.RECEPTIONIST, Role.ACCOUNTANT, Role.PHARMACIST):
            self.client.force_login(make_user(role))
            self.assertEqual(self.client.get(reverse("records:detail", args=[self.record.pk])).status_code, 403, role)
            self.assertEqual(self.client.get(reverse("records:list")).status_code, 403, role)

    def test_patient_page_hides_records_from_receptionist(self):
        self.client.force_login(make_user(Role.RECEPTIONIST))
        response = self.client.get(reverse("patients:detail", args=[self.patient.pk]))
        self.assertNotContains(response, "Secret-Diagnosis-123")

    def test_unassigned_doctor_and_nurse_cannot_view(self):
        other_user = make_user(Role.DOCTOR)
        make_doctor(user=other_user, first_name="Other", last_name="Doc")
        self.client.force_login(other_user)
        self.assertEqual(self.client.get(reverse("records:detail", args=[self.record.pk])).status_code, 404)
        self.client.force_login(make_user(Role.NURSE))
        self.assertEqual(self.client.get(reverse("records:detail", args=[self.record.pk])).status_code, 404)

    def test_assigned_nurse_can_view_but_not_edit(self):
        nurse = make_user(Role.NURSE)
        admit_patient(patient=self.patient, bed=make_bed(), doctor=self.doctor, reason="r", user=self.doctor_user, nurse=nurse)
        self.client.force_login(nurse)
        self.assertContains(self.client.get(reverse("records:detail", args=[self.record.pk])), "Secret-Diagnosis-123")
        self.assertEqual(self.client.get(reverse("records:edit", args=[self.record.pk])).status_code, 403)

    def test_admin_can_view_but_not_author(self):
        self.client.force_login(make_user(Role.ADMIN))
        self.assertEqual(self.client.get(reverse("records:detail", args=[self.record.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("records:create")).status_code, 403)

    def test_doctor_creates_and_amends_record_with_audit(self):
        self.client.force_login(self.doctor_user)
        response = self.client.post(reverse("records:create"), {
            "patient": self.patient.pk, "appointment": "", "visit_date": timezone.localtime().strftime("%Y-%m-%dT%H:%M"),
            "symptoms": "Fever", "visit_notes": "", "diagnosis": "Viral infection", "treatment_plan": "Rest",
            "follow_up_instructions": "", "follow_up_date": "",
        })
        record = MedicalRecord.objects.get(diagnosis="Viral infection")
        self.assertRedirects(response, reverse("records:detail", args=[record.pk]))
        self.assertEqual(record.doctor, self.doctor)
        self.client.post(reverse("records:edit", args=[record.pk]), {
            "appointment": "", "visit_date": timezone.localtime(record.visit_date).strftime("%Y-%m-%dT%H:%M"),
            "symptoms": "Fever", "visit_notes": "", "diagnosis": "Influenza", "treatment_plan": "Rest",
            "follow_up_instructions": "", "follow_up_date": "",
        })
        record.refresh_from_db()
        self.assertEqual(record.diagnosis, "Influenza")
        entry = AuditLog.objects.get(action="update", object_id=str(record.pk), model_label="medical_records.MedicalRecord")
        self.assertIn("diagnosis", entry.changes)

    def test_other_doctor_cannot_edit(self):
        other_user = make_user(Role.DOCTOR)
        other = make_doctor(user=other_user, first_name="Other", last_name="Doc")
        make_appointment(self.patient, other, start=timezone.now() + timedelta(days=5))
        self.client.force_login(other_user)
        self.assertEqual(self.client.get(reverse("records:detail", args=[self.record.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("records:edit", args=[self.record.pk])).status_code, 403)


class PrescriptionDispenseTests(TestCase):
    def setUp(self):
        self.pharmacist = make_user(Role.PHARMACIST)
        self.doctor = make_doctor()
        self.patient = make_patient()
        self.medicine = make_medicine()
        adjust_stock(self.medicine, 10, StockTransaction.Type.ADDITION)
        self.rx = Prescription.objects.create(patient=self.patient, doctor=self.doctor)

    def add_item(self, qty):
        PrescriptionItem.objects.create(prescription=self.rx, medicine=self.medicine, medication_name="Testamol",
                                        dosage="1", frequency="daily", duration="5 days", quantity=qty)

    def test_dispense_deducts_stock(self):
        self.add_item(4)
        dispense_prescription(self.rx, self.pharmacist)
        self.medicine.refresh_from_db()
        self.rx.refresh_from_db()
        self.assertEqual(self.medicine.quantity, 6)
        self.assertEqual(self.rx.status, Prescription.Status.DISPENSED)
        with self.assertRaises(StockError):
            dispense_prescription(self.rx, self.pharmacist)

    def test_insufficient_stock_rolls_back(self):
        self.add_item(4)
        self.add_item(20)
        with self.assertRaises(StockError):
            dispense_prescription(self.rx, self.pharmacist)
        self.medicine.refresh_from_db()
        self.rx.refresh_from_db()
        self.assertEqual(self.medicine.quantity, 10)
        self.assertEqual(self.rx.status, Prescription.Status.ACTIVE)

    def test_only_pharmacist_can_dispense(self):
        self.add_item(1)
        self.client.force_login(make_user(Role.NURSE))
        self.assertEqual(self.client.post(reverse("records:prescription_dispense", args=[self.rx.pk])).status_code, 403)
        self.client.force_login(self.pharmacist)
        self.client.post(reverse("records:prescription_dispense", args=[self.rx.pk]))
        self.rx.refresh_from_db()
        self.assertEqual(self.rx.status, Prescription.Status.DISPENSED)

    def test_doctor_issues_prescription(self):
        user = make_user(Role.DOCTOR)
        doctor = make_doctor(user=user, first_name="Rx", last_name="Writer")
        make_appointment(self.patient, doctor)
        self.client.force_login(user)
        response = self.client.post(reverse("records:prescription_create"), {
            "patient": self.patient.pk, "medical_record": "", "notes": "",
            "items-TOTAL_FORMS": "1", "items-INITIAL_FORMS": "0", "items-MIN_NUM_FORMS": "0", "items-MAX_NUM_FORMS": "1000",
            "items-0-medicine": self.medicine.pk, "items-0-medication_name": "", "items-0-dosage": "500 mg",
            "items-0-frequency": "Twice daily", "items-0-duration": "5 days", "items-0-quantity": "10", "items-0-instructions": "",
        })
        rx = Prescription.objects.get(doctor=doctor)
        self.assertRedirects(response, reverse("records:prescription_detail", args=[rx.pk]))
        self.assertEqual(rx.items.get().medication_name, "Testamol")

    def test_empty_prescription_rejected(self):
        user = make_user(Role.DOCTOR)
        make_doctor(user=user, first_name="Rx", last_name="Writer")
        self.client.force_login(user)
        response = self.client.post(reverse("records:prescription_create"), {
            "patient": "", "medical_record": "", "notes": "",
            "items-TOTAL_FORMS": "1", "items-INITIAL_FORMS": "0", "items-MIN_NUM_FORMS": "0", "items-MAX_NUM_FORMS": "1000",
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Prescription.objects.filter(doctor__user=user).exists())
