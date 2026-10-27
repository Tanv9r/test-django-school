"""Populate the database with clearly-marked demo data for local testing and tutorials.

All demo people use e-mail addresses on the ``demo.hms.local`` domain and demo
logins start with ``demo_``. For complete separation, point HMS_DB_PATH at a
separate SQLite file (e.g. demo.sqlite3) before running this command.
"""
import random
from datetime import time, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import Role, User
from admissions.models import Admission, Bed, NursingTask, Room, RoomType
from admissions.services import admit_patient, discharge_patient
from appointments.models import Appointment
from appointments.services import local_dt
from billing.models import Invoice, PaymentMethod
from billing.services import consultation_charge, record_payment, room_charge, save_invoice
from core.models import HospitalSettings
from doctors.models import Department, Doctor, DoctorAvailability
from medical_records.models import MedicalRecord, Prescription, PrescriptionItem
from patients.models import Patient
from pharmacy.models import Medicine, MedicineCategory, StockTransaction
from pharmacy.services import adjust_stock
from staff.models import StaffProfile

DEMO_DOMAIN = "demo.hms.local"

FIRST_NAMES = ["Aisha", "Ben", "Carlos", "Diana", "Ethan", "Fatima", "George", "Hana", "Ivan", "Julia", "Kofi", "Leila",
               "Mateo", "Nadia", "Omar", "Priya", "Quinn", "Rosa", "Samir", "Tara", "Umar", "Vera", "Wei", "Yara", "Zane",
               "Amira", "Bilal", "Chloe", "Dev", "Elena"]
LAST_NAMES = ["Rahman", "Okafor", "Silva", "Novak", "Haddad", "Chen", "Patel", "Kowalski", "Mensah", "Larsen", "Ito",
              "Moreau", "Santos", "Ahmed", "Fischer", "Nair", "Costa", "Ibrahim", "Walsh", "Kim"]
REASONS = ["Routine check-up", "Chest pain on exertion", "Persistent headache", "Knee pain after fall", "Fever and cough",
           "Follow-up visit", "Blood pressure review", "Child vaccination review", "Back pain", "Prenatal consultation",
           "Dizziness", "Skin rash", "Shortness of breath", "Diabetes review"]


class Command(BaseCommand):
    help = "Create clearly-marked demo data (users, doctors, patients, appointments, admissions, stock, invoices)."

    def add_arguments(self, parser):
        parser.add_argument("--password", default="Demo@12345", help="Password for all demo logins.")
        parser.add_argument("--force", action="store_true", help="Run even if non-demo patients exist.")

    def handle(self, *args, password, force, **options):
        if User.objects.filter(username="demo_admin").exists():
            raise CommandError("Demo data already exists (user 'demo_admin' found).")
        if not force and Patient.objects.exclude(email__endswith=DEMO_DOMAIN).exists():
            raise CommandError(
                "This database already contains real (non-demo) patients. Use a separate database "
                "(set HMS_DB_PATH) or pass --force if you really want to mix demo data in."
            )
        self.rng = random.Random(42)
        self.now = timezone.now()
        self.today = timezone.localdate()
        with transaction.atomic():
            self._settings()
            users = self._users(password)
            doctors = self._doctors(users)
            self._staff(users)
            beds = self._rooms()
            medicines = self._medicines(users["demo_pharmacist"])
            patients = self._patients(users["demo_reception"])
            appointments = self._appointments(patients, doctors, users["demo_reception"])
            self._records(appointments, medicines)
            admissions = self._admissions(patients, doctors, beds, users)
            self._billing(appointments, admissions, users["demo_accountant"])
        self.stdout.write(self.style.SUCCESS("Demo data created."))
        self.stdout.write(f"Sign in with any of these usernames and the password '{password}':")
        for name in ["demo_admin", "demo_dr_carter", "demo_nurse", "demo_reception", "demo_pharmacist", "demo_accountant"]:
            self.stdout.write(f"  - {name}")

    # ------------------------------------------------------------------ helpers
    def _email(self, first, last):
        return f"{first}.{last}@{DEMO_DOMAIN}".lower()

    def _phone(self):
        return f"+1 555 {self.rng.randint(100, 999)} {self.rng.randint(1000, 9999)}"

    def _settings(self):
        s = HospitalSettings.load()
        s.name = "CityCare General Hospital"
        s.address = "120 Riverside Avenue\nSpringfield"
        s.phone = "+1 555 010 2000"
        s.email = f"info@{DEMO_DOMAIN}"
        s.save()

    def _users(self, password):
        spec = [
            ("demo_admin", "Avery", "Morgan", Role.ADMIN),
            ("demo_dr_carter", "Emily", "Carter", Role.DOCTOR),
            ("demo_dr_singh", "Arjun", "Singh", Role.DOCTOR),
            ("demo_dr_lopez", "Maria", "Lopez", Role.DOCTOR),
            ("demo_nurse", "Grace", "Okoye", Role.NURSE),
            ("demo_nurse2", "Daniel", "Reyes", Role.NURSE),
            ("demo_reception", "Sophie", "Turner", Role.RECEPTIONIST),
            ("demo_pharmacist", "Liam", "Becker", Role.PHARMACIST),
            ("demo_accountant", "Noah", "Kim", Role.ACCOUNTANT),
        ]
        users = {}
        for username, first, last, role in spec:
            user = User(username=username, first_name=first, last_name=last, role=role,
                        email=self._email(first, last), phone=self._phone())
            user.set_password(password)
            user.save()
            users[username] = user
        return users

    def _doctors(self, users):
        depts = {d.name: d for d in Department.objects.all()}
        spec = [
            ("Emily", "Carter", "Cardiology", "Interventional Cardiology", "MBBS, MD (Cardiology)", "120.00", users["demo_dr_carter"]),
            ("Arjun", "Singh", "Neurology", "Neurology", "MBBS, DM (Neurology)", "110.00", users["demo_dr_singh"]),
            ("Maria", "Lopez", "Pediatrics", "General Pediatrics", "MBBS, DCH", "80.00", users["demo_dr_lopez"]),
            ("James", "Okafor", "Orthopedics", "Joint Replacement", "MBBS, MS (Ortho)", "100.00", None),
            ("Sara", "Haddad", "General Medicine", "Internal Medicine", "MBBS, MD", "60.00", None),
            ("Mei", "Chen", "Gynecology", "Obstetrics & Gynecology", "MBBS, MS (OBG)", "90.00", None),
            ("Victor", "Mensah", "Emergency", "Emergency Medicine", "MBBS, FCEM", "70.00", None),
        ]
        doctors = []
        for first, last, dept, spec_name, quals, fee, user in spec:
            doctor = Doctor.objects.create(
                first_name=first, last_name=last, department=depts[dept], specialization=spec_name,
                qualifications=quals, consultation_fee=Decimal(fee), phone=self._phone(),
                email=self._email(first, last), user=user, slot_minutes=30,
                bio=f"Demo profile for Dr. {first} {last}.",
            )
            for weekday in range(5):
                DoctorAvailability.objects.create(doctor=doctor, weekday=weekday, start_time=time(9), end_time=time(17))
            DoctorAvailability.objects.create(doctor=doctor, weekday=5, start_time=time(9), end_time=time(13))
            doctors.append(doctor)
        return doctors

    def _staff(self, users):
        depts = list(Department.objects.all())
        titles = {
            "demo_admin": "Hospital Administrator", "demo_nurse": "Senior Staff Nurse", "demo_nurse2": "Staff Nurse",
            "demo_reception": "Front Desk Coordinator", "demo_pharmacist": "Chief Pharmacist", "demo_accountant": "Billing Accountant",
        }
        for username, title in titles.items():
            u = users[username]
            StaffProfile.objects.create(
                user=u, first_name=u.first_name, last_name=u.last_name, email=u.email, phone=u.phone or self._phone(),
                job_title=title, department=self.rng.choice(depts), joining_date=self.today - timedelta(days=self.rng.randint(90, 2000)),
                address="Demo address",
            )
        for first, last, title in [("Hugo", "Larsen", "Lab Technician"), ("Ines", "Costa", "Radiographer"), ("Tom", "Walsh", "Porter")]:
            StaffProfile.objects.create(
                first_name=first, last_name=last, email=self._email(first, last), phone=self._phone(), job_title=title,
                department=self.rng.choice(depts), joining_date=self.today - timedelta(days=self.rng.randint(30, 900)),
                employment_status=self.rng.choice([StaffProfile.EmploymentStatus.ACTIVE, StaffProfile.EmploymentStatus.ON_LEAVE]),
            )

    def _rooms(self):
        types = {t.name: t for t in RoomType.objects.all()}
        depts = {d.name: d for d in Department.objects.all()}
        layout = [
            ("101", "General Ward", "General Medicine", "1", 4), ("102", "General Ward", "Orthopedics", "1", 4),
            ("103", "General Ward", "Pediatrics", "1", 4), ("201", "Semi-Private", "Cardiology", "2", 2),
            ("202", "Semi-Private", "Neurology", "2", 2), ("203", "Private", "Gynecology", "2", 1),
            ("204", "Private", "Cardiology", "2", 1), ("ICU-1", "ICU", "Emergency", "G", 3),
        ]
        beds = []
        for number, rtype, dept, floor, count in layout:
            room = Room.objects.create(number=number, room_type=types[rtype], department=depts[dept], floor=floor)
            for i in range(1, count + 1):
                beds.append(Bed.objects.create(room=room, bed_number=str(i)))
        beds[-1].status = Bed.Status.MAINTENANCE
        beds[-1].save()
        return beds

    def _medicines(self, pharmacist):
        cats = {c.name: c for c in MedicineCategory.objects.all()}
        spec = [
            ("Paracetamol 500mg", "Acetaminophen", "Analgesics", "tablets", "0.10", 800, 400),
            ("Ibuprofen 400mg", "Ibuprofen", "Analgesics", "tablets", "0.15", 35, 300),
            ("Amoxicillin 500mg", "Amoxicillin", "Antibiotics", "capsules", "0.40", 420, 200),
            ("Azithromycin 250mg", "Azithromycin", "Antibiotics", "tablets", "0.90", 12, 200),
            ("Ceftriaxone 1g", "Ceftriaxone", "Antibiotics", "vials", "3.50", 60, 120),
            ("Amlodipine 5mg", "Amlodipine", "Antihypertensives", "tablets", "0.20", 500, 365),
            ("Losartan 50mg", "Losartan", "Antihypertensives", "tablets", "0.30", 0, 300),
            ("Metformin 500mg", "Metformin", "Antidiabetics", "tablets", "0.12", 650, 40),
            ("Insulin Glargine", "Insulin glargine", "Antidiabetics", "pens", "18.00", 25, 25),
            ("Vitamin D3 1000IU", "Cholecalciferol", "Vitamins & Supplements", "capsules", "0.08", 300, 500),
            ("Povidone-Iodine 10%", "Povidone-iodine", "Antiseptics", "bottles", "2.40", 45, 700),
            ("Salbutamol Inhaler", "Salbutamol", "Respiratory", "inhalers", "4.20", 18, 20),
        ]
        meds = []
        for i, (name, generic, cat, unit, price, qty, days) in enumerate(spec):
            med = Medicine.objects.create(
                name=name, generic_name=generic, category=cats[cat], manufacturer=self.rng.choice(["MediCorp", "HealWell", "Nova Pharma"]),
                batch_number=f"B{2026}{i:03d}", unit=unit, unit_price=Decimal(price), reorder_level=40 if unit == "tablets" else 15,
                expiry_date=self.today + timedelta(days=days),
            )
            if qty:
                adjust_stock(med, qty, StockTransaction.Type.INITIAL, pharmacist, "Opening stock (demo)")
            meds.append(med)
        return meds

    def _patients(self, receptionist):
        patients = []
        used = set()
        while len(patients) < 30:
            first, last = self.rng.choice(FIRST_NAMES), self.rng.choice(LAST_NAMES)
            if (first, last) in used:
                continue
            used.add((first, last))
            p = Patient.objects.create(
                first_name=first, last_name=last,
                date_of_birth=self.today - timedelta(days=self.rng.randint(365 * 2, 365 * 85)),
                gender=self.rng.choice(["M", "F"]), phone=self._phone(), email=self._email(first, last),
                address=f"{self.rng.randint(1, 250)} Demo Street, Springfield",
                emergency_contact_name=f"{self.rng.choice(FIRST_NAMES)} {last}", emergency_contact_phone=self._phone(),
                emergency_contact_relation=self.rng.choice(["Spouse", "Parent", "Sibling", "Child"]),
                blood_group=self.rng.choice(["A+", "B+", "O+", "AB+", "O-", "A-", "UNK"]),
                allergies=self.rng.choice(["", "", "", "Penicillin", "Peanuts", "Latex"]),
                chronic_conditions=self.rng.choice(["", "", "Hypertension", "Type 2 diabetes", "Asthma"]),
                registered_by=receptionist,
            )
            # Spread registrations over the last six months for realistic reports.
            Patient.objects.filter(pk=p.pk).update(created_at=self.now - timedelta(days=self.rng.randint(0, 180)))
            patients.append(p)
        return patients

    def _appointments(self, patients, doctors, receptionist):
        S = Appointment.Status
        created = []
        for offset in range(-45, 15):
            day = self.today + timedelta(days=offset)
            if day.weekday() == 6:
                continue
            for doctor in doctors:
                hours = [9, 10, 11, 12] if day.weekday() == 5 else [9, 10, 11, 14, 15, 16]
                for hour in self.rng.sample(hours, k=self.rng.randint(0, 2)):
                    start = local_dt(day, time(hour, self.rng.choice([0, 30])))
                    end = start + timedelta(minutes=doctor.slot_minutes)
                    if start < self.now:
                        status = self.rng.choices([S.COMPLETED, S.CANCELLED, S.NO_SHOW], weights=[80, 12, 8])[0]
                    else:
                        status = self.rng.choice([S.SCHEDULED, S.CONFIRMED])
                    patient = self.rng.choice(patients)
                    if Appointment.objects.filter(patient=patient, start_at__lt=end, end_at__gt=start).exists():
                        continue
                    created.append(Appointment.objects.create(
                        patient=patient, doctor=doctor, department=doctor.department, start_at=start, end_at=end,
                        reason=self.rng.choice(REASONS), status=status, booked_by=receptionist,
                        cancellation_reason="Patient requested (demo)" if status == S.CANCELLED else "",
                    ))
        return created

    def _records(self, appointments, medicines):
        diagnoses = ["Essential hypertension", "Viral upper respiratory infection", "Tension-type headache", "Lumbar strain",
                     "Type 2 diabetes mellitus – stable", "Mild persistent asthma", "Knee sprain"]
        completed = [a for a in appointments if a.status == Appointment.Status.COMPLETED]
        for appt in self.rng.sample(completed, k=min(25, len(completed))):
            record = MedicalRecord.objects.create(
                patient=appt.patient, doctor=appt.doctor, appointment=appt, visit_date=appt.start_at,
                symptoms=appt.reason, diagnosis=self.rng.choice(diagnoses),
                visit_notes="Demo note: entered for testing purposes only.",
                treatment_plan="Demo treatment plan – reviewed by the treating clinician.",
                follow_up_instructions="Return if symptoms persist.", created_by=appt.doctor.user, updated_by=appt.doctor.user,
            )
            if self.rng.random() < 0.6:
                rx = Prescription.objects.create(patient=appt.patient, doctor=appt.doctor, medical_record=record, notes="Demo prescription.")
                for med in self.rng.sample([m for m in medicines if m.quantity > 50], k=2):
                    PrescriptionItem.objects.create(
                        prescription=rx, medicine=med, medication_name=med.name, dosage="1 unit",
                        frequency=self.rng.choice(["Once daily", "Twice daily", "Every 8 hours"]),
                        duration=self.rng.choice(["5 days", "7 days", "14 days"]), quantity=self.rng.choice([10, 14, 20]),
                        instructions="Demo instructions",
                    )

    def _admissions(self, patients, doctors, beds, users):
        nurses = [users["demo_nurse"], users["demo_nurse2"]]
        reasons = ["Observation after chest pain", "Post-operative care", "Severe dehydration", "Pneumonia treatment",
                   "Fracture management", "Monitoring after head injury"]
        available = [b for b in beds if b.status == Bed.Status.AVAILABLE]
        admissions = []
        for i, patient in enumerate(self.rng.sample(patients, k=14)):
            bed = available[i]
            admitted_at = self.now - timedelta(days=self.rng.randint(1, 20), hours=self.rng.randint(0, 12))
            admission = admit_patient(
                patient=patient, bed=bed, doctor=self.rng.choice(doctors), nurse=self.rng.choice(nurses),
                reason=self.rng.choice(reasons), user=users["demo_reception"], admitted_at=admitted_at,
            )
            if i >= 8:  # discharge the older ones
                discharge_patient(
                    admission, summary="Recovered well. Discharged with follow-up advice (demo).", user=users["demo_dr_carter"],
                    discharged_at=min(admitted_at + timedelta(days=self.rng.randint(1, 6)), self.now),
                )
                admission.refresh_from_db()
            else:
                for title in ["Check vitals every 4 hours", "Administer evening medication", "Change dressing"]:
                    NursingTask.objects.create(
                        admission=admission, title=title, assigned_to=admission.assigned_nurse, created_by=users["demo_dr_carter"],
                        due_at=self.now + timedelta(hours=self.rng.randint(-3, 12)),
                        priority=self.rng.choice(["low", "normal", "high"]),
                    )
            admissions.append(admission)
        return admissions

    def _billing(self, appointments, admissions, accountant):
        methods = list(PaymentMethod.objects.filter(is_active=True))
        cash = PaymentMethod.objects.get(name="Cash")
        completed = [a for a in appointments if a.status == Appointment.Status.COMPLETED]
        for appt in completed:
            issue = timezone.localtime(appt.start_at).date()
            invoice = save_invoice(
                Invoice(patient=appt.patient, appointment=appt, issue_date=issue, due_date=issue + timedelta(days=14)),
                [consultation_charge(appt)], accountant,
            )
            self._pay(invoice, methods, cash, accountant, appt.start_at)
        for adm in admissions:
            issue = timezone.localtime(adm.discharged_at or self.now).date()
            rows = [room_charge(adm), {"item_type": "lab", "description": "Laboratory tests", "quantity": 1, "unit_price": Decimal("45.00")}]
            invoice = save_invoice(
                Invoice(patient=adm.patient, admission=adm, issue_date=issue, due_date=issue + timedelta(days=30),
                        discount_amount=Decimal("10.00") if self.rng.random() < 0.3 else Decimal("0")),
                rows, accountant,
            )
            if adm.status == Admission.Status.DISCHARGED:
                self._pay(invoice, methods, cash, accountant, adm.discharged_at)

    def _pay(self, invoice, methods, cash, user, when):
        roll = self.rng.random()
        if roll < 0.15:
            return  # leave unpaid
        method = self.rng.choice(methods)
        amount = invoice.total if roll > 0.3 else (invoice.total / 2).quantize(Decimal("0.01"))
        paid_at = min(when + timedelta(hours=self.rng.randint(0, 48)), self.now)
        record_payment(
            invoice, amount=amount, method=method, user=user, paid_at=paid_at,
            reference="" if method == cash else f"DEMO-{self.rng.randint(10000, 99999)}",
        )
