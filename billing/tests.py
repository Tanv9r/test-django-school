from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from accounts.models import Role
from billing.models import Invoice, Payment, PaymentMethod
from billing.services import BillingError, cancel_invoice, record_payment, save_invoice
from core.testing import make_appointment, make_doctor, make_patient, make_user


def rows(*pairs):
    return [{"item_type": "other", "description": f"Item {i}", "quantity": Decimal(q), "unit_price": Decimal(p)} for i, (q, p) in enumerate(pairs)]


class InvoiceCalculationTests(TestCase):
    def setUp(self):
        self.patient = make_patient()
        self.cash = PaymentMethod.objects.get(name="Cash")
        self.user = make_user(Role.ACCOUNTANT)

    def test_totals_use_exact_decimals(self):
        invoice = save_invoice(Invoice(patient=self.patient, discount_amount=Decimal("0.30")), rows(("3", "0.10"), ("1", "0.20")))
        self.assertEqual(invoice.subtotal, Decimal("0.50"))
        self.assertEqual(invoice.total, Decimal("0.20"))
        self.assertEqual(invoice.status, Invoice.Status.UNPAID)

    def test_rounding_half_up(self):
        invoice = save_invoice(Invoice(patient=self.patient), rows(("1.5", "0.33")))  # 0.495 -> 0.50
        self.assertEqual(invoice.total, Decimal("0.50"))

    def test_discount_cannot_exceed_subtotal(self):
        with self.assertRaises(BillingError):
            save_invoice(Invoice(patient=self.patient, discount_amount=Decimal("100")), rows(("1", "50")))

    def test_partial_then_full_payment(self):
        invoice = save_invoice(Invoice(patient=self.patient), rows(("2", "75.00")))
        record_payment(invoice, amount=Decimal("100.00"), method=self.cash, user=self.user)
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, Invoice.Status.PARTIALLY_PAID)
        self.assertEqual(invoice.balance_due, Decimal("50.00"))
        record_payment(invoice, amount=Decimal("50.00"), method=self.cash, user=self.user)
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, Invoice.Status.PAID)
        self.assertEqual(invoice.balance_due, Decimal("0.00"))

    def test_overpayment_and_zero_payment_rejected(self):
        invoice = save_invoice(Invoice(patient=self.patient), rows(("1", "10.00")))
        for amount in ("10.01", "0", "-5"):
            with self.assertRaises(BillingError):
                record_payment(invoice, amount=Decimal(amount), method=self.cash, user=self.user)
        self.assertFalse(Payment.objects.exists())

    def test_never_paid_without_payment_record(self):
        invoice = save_invoice(Invoice(patient=self.patient, discount_amount=Decimal("10")), rows(("1", "10.00")))
        self.assertEqual(invoice.total, Decimal("0.00"))
        self.assertEqual(invoice.status, Invoice.Status.UNPAID)
        with self.assertRaises(BillingError):
            record_payment(invoice, amount=Decimal("1"), method=self.cash, user=self.user)

    def test_cancel_rules(self):
        invoice = save_invoice(Invoice(patient=self.patient), rows(("1", "10.00")))
        record_payment(invoice, amount=Decimal("5"), method=self.cash, user=self.user)
        with self.assertRaises(BillingError):
            cancel_invoice(invoice, "mistake")
        other = save_invoice(Invoice(patient=self.patient), rows(("1", "10.00")))
        cancel_invoice(other, "duplicate")
        other.refresh_from_db()
        self.assertEqual(other.status, Invoice.Status.CANCELLED)
        with self.assertRaises(BillingError):
            record_payment(other, amount=Decimal("1"), method=self.cash, user=self.user)

    def test_paid_invoice_cannot_be_edited(self):
        invoice = save_invoice(Invoice(patient=self.patient), rows(("1", "10.00")))
        record_payment(invoice, amount=Decimal("10"), method=self.cash, user=self.user)
        invoice.refresh_from_db()
        with self.assertRaises(BillingError):
            save_invoice(invoice, rows(("1", "1.00")))


class InvoiceViewTests(TestCase):
    def setUp(self):
        self.user = make_user(Role.ACCOUNTANT)
        self.client.force_login(self.user)
        self.patient = make_patient()

    def test_create_invoice_with_consultation_charge(self):
        appt = make_appointment(self.patient, make_doctor())
        response = self.client.post(reverse("billing:invoice_create"), {
            "patient": self.patient.pk, "appointment": appt.pk, "admission": "", "issue_date": "2026-01-10", "due_date": "",
            "discount_amount": "5.00", "notes": "", "add_consultation": "on",
            "items-TOTAL_FORMS": "1", "items-INITIAL_FORMS": "0", "items-MIN_NUM_FORMS": "0", "items-MAX_NUM_FORMS": "1000",
            "items-0-item_type": "lab", "items-0-description": "Blood test", "items-0-quantity": "2", "items-0-unit_price": "12.50",
        })
        invoice = Invoice.objects.get()
        self.assertRedirects(response, reverse("billing:invoice_detail", args=[invoice.pk]))
        self.assertEqual(invoice.items.count(), 2)
        self.assertEqual(invoice.subtotal, Decimal("125.00"))
        self.assertEqual(invoice.total, Decimal("120.00"))
        self.assertTrue(invoice.invoice_number.startswith("INV-2026-"))
        self.assertEqual(self.client.get(reverse("billing:invoice_print", args=[invoice.pk])).status_code, 200)

    def test_payment_view_requires_reference_for_card(self):
        invoice = save_invoice(Invoice(patient=self.patient), rows(("1", "40.00")))
        card = PaymentMethod.objects.get(name="Card")
        url = reverse("billing:payment_create", args=[invoice.pk])
        response = self.client.post(url, {"amount": "40.00", "method": card.pk, "paid_at": "2026-01-10T10:00", "reference": ""})
        self.assertIn("reference", response.context["form"].errors)
        response = self.client.post(url, {"amount": "40.00", "method": card.pk, "paid_at": "2026-01-10T10:00", "reference": "TX1"})
        self.assertEqual(response.status_code, 302)
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, Invoice.Status.PAID)

    def test_nurse_cannot_access_billing(self):
        self.client.force_login(make_user(Role.NURSE))
        self.assertEqual(self.client.get(reverse("billing:invoice_list")).status_code, 403)
