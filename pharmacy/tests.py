from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role
from core.testing import make_medicine, make_user
from pharmacy.models import Medicine, StockTransaction
from pharmacy.services import StockError, adjust_stock


class StockTests(TestCase):
    def setUp(self):
        self.pharmacist = make_user(Role.PHARMACIST)
        self.medicine = make_medicine()

    def test_adjust_stock_records_transaction(self):
        adjust_stock(self.medicine, 50, StockTransaction.Type.ADDITION, self.pharmacist)
        adjust_stock(self.medicine, -20, StockTransaction.Type.DISPENSE, self.pharmacist)
        self.medicine.refresh_from_db()
        self.assertEqual(self.medicine.quantity, 30)
        self.assertEqual(list(self.medicine.transactions.order_by("pk").values_list("balance_after", flat=True)), [50, 30])

    def test_negative_stock_prevented(self):
        adjust_stock(self.medicine, 5, StockTransaction.Type.ADDITION)
        with self.assertRaises(StockError):
            adjust_stock(self.medicine, -6, StockTransaction.Type.DISPENSE)
        self.medicine.refresh_from_db()
        self.assertEqual(self.medicine.quantity, 5)
        self.assertEqual(self.medicine.transactions.count(), 1)

    def test_zero_change_rejected(self):
        with self.assertRaises(StockError):
            adjust_stock(self.medicine, 0, StockTransaction.Type.ADJUSTMENT)

    def test_adjust_view_validates_on_server(self):
        self.client.force_login(self.pharmacist)
        url = reverse("pharmacy:adjust", args=[self.medicine.pk])
        response = self.client.post(url, {"action": "decrease", "quantity": 3, "note": "Broken"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("quantity", response.context["form"].errors)
        response = self.client.post(url, {"action": "increase", "quantity": 3, "note": ""})
        self.assertIn("note", response.context["form"].errors)
        response = self.client.post(url, {"action": "addition", "quantity": 10, "reference": "GRN-1"})
        self.assertEqual(response.status_code, 302)
        self.medicine.refresh_from_db()
        self.assertEqual(self.medicine.quantity, 10)

    def test_create_medicine_with_opening_stock(self):
        self.client.force_login(self.pharmacist)
        response = self.client.post(reverse("pharmacy:create"), {
            "name": "Newcillin", "generic_name": "", "category": self.medicine.category.pk, "manufacturer": "Acme",
            "batch_number": "N-1", "unit": "tablets", "unit_price": "0.50", "reorder_level": 10,
            "expiry_date": (timezone.localdate() + timedelta(days=200)).isoformat(), "is_active": "on", "opening_stock": 100,
        })
        self.assertEqual(response.status_code, 302)
        med = Medicine.objects.get(name="Newcillin")
        self.assertEqual(med.quantity, 100)
        self.assertEqual(med.transactions.get().transaction_type, StockTransaction.Type.INITIAL)

    def test_low_stock_and_expiry_queries(self):
        low = make_medicine(name="Low", batch_number="L", reorder_level=10)
        adjust_stock(low, 5, StockTransaction.Type.ADDITION)
        expiring = make_medicine(name="Soon", batch_number="S", expiry_date=timezone.localdate() + timedelta(days=10))
        adjust_stock(expiring, 100, StockTransaction.Type.ADDITION)
        self.assertIn(low, Medicine.objects.low_stock())
        self.assertIn(expiring, Medicine.objects.expiring_within(30))
        self.assertNotIn(expiring, Medicine.objects.low_stock())

    def test_accountant_cannot_manage_stock(self):
        self.client.force_login(make_user(Role.ACCOUNTANT))
        self.assertEqual(self.client.get(reverse("pharmacy:list")).status_code, 403)
