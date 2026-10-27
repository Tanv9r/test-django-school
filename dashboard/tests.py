from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role
from admissions.services import admit_patient
from billing.models import Invoice, PaymentMethod
from billing.services import record_payment, save_invoice
from core.testing import make_appointment, make_bed, make_doctor, make_patient, make_user
from dashboard import stats


class DashboardTests(TestCase):
    def test_empty_dashboard_renders_for_every_role(self):
        for role in Role.values:
            self.client.force_login(make_user(role))
            response = self.client.get(reverse("dashboard:index"))
            self.assertEqual(response.status_code, 200, role)

    def test_statistics_come_from_database(self):
        admin = make_user(Role.ADMIN)
        doctor = make_doctor()
        patient = make_patient()
        start = timezone.now() + timedelta(minutes=30)
        if timezone.localtime(start).date() == timezone.localdate():
            make_appointment(patient, doctor, start=start)
        admit_patient(patient=patient, bed=make_bed(), doctor=doctor, reason="r", user=admin)
        make_bed(bed_number="2")
        invoice = save_invoice(Invoice(patient=patient), [{"item_type": "other", "description": "x", "quantity": Decimal("1"), "unit_price": Decimal("80")}])
        record_payment(invoice, amount=Decimal("30"), method=PaymentMethod.objects.get(name="Cash"), user=admin)

        self.assertEqual(stats.todays_collections(), Decimal("30.00"))
        self.assertEqual(stats.pending_invoices()["count"], 1)
        occupancy = stats.bed_occupancy()
        self.assertEqual((occupancy["occupied"], occupancy["available"], occupancy["occupancy_rate"]), (1, 1, 50))
        self.assertEqual(stats.monthly_revenue()["values"][-1], 30.0)

        self.client.force_login(make_user(Role.RECEPTIONIST))
        cards = {c["label"]: c["value"] for c in self.client.get(reverse("dashboard:index")).context["cards"]}
        self.assertEqual(cards["Registered patients"], 1)
        self.assertEqual(cards["Currently admitted"], 1)
        self.assertEqual(cards["Available beds"], 1)
        self.assertNotIn("Pending invoices", cards)  # receptionists have no billing access

    def test_admin_overview_and_reports(self):
        self.client.force_login(make_user(Role.ADMIN))
        self.assertEqual(self.client.get(reverse("adminpanel:overview")).status_code, 200)
        for slug in ["patients", "appointments", "doctor-workload", "admissions", "bed-occupancy", "medicine-stock", "revenue", "outstanding"]:
            self.assertEqual(self.client.get(reverse("dashboard:report_detail", args=[slug])).status_code, 200, slug)
        csv = self.client.get(reverse("dashboard:report_detail", args=["patients"]), {"export": "csv"})
        self.assertEqual(csv["Content-Type"], "text/csv")

    def test_financial_reports_restricted(self):
        self.client.force_login(make_user(Role.RECEPTIONIST))
        self.assertEqual(self.client.get(reverse("dashboard:report_detail", args=["revenue"])).status_code, 403)
        self.client.force_login(make_user(Role.ACCOUNTANT))
        self.assertEqual(self.client.get(reverse("dashboard:report_detail", args=["revenue"])).status_code, 200)
        self.assertEqual(self.client.get(reverse("dashboard:report_detail", args=["admissions"])).status_code, 403)

    def test_csv_export_neutralises_formulas(self):
        make_patient(first_name="=HYPERLINK", last_name="Evil")
        self.client.force_login(make_user(Role.ADMIN))
        content = self.client.get(reverse("dashboard:report_detail", args=["patients"]), {"export": "csv"}).content.decode()
        self.assertIn("'=HYPERLINK Evil", content.replace('"', ""))

    def test_global_search_respects_roles(self):
        make_patient(first_name="Searchable", last_name="Person")
        self.client.force_login(make_user(Role.PHARMACIST))
        response = self.client.get(reverse("dashboard:search"), {"q": "Searchable"})
        self.assertNotContains(response, "Searchable Person")
        self.client.force_login(make_user(Role.RECEPTIONIST))
        self.assertContains(self.client.get(reverse("dashboard:search"), {"q": "Searchable"}), "Searchable Person")
