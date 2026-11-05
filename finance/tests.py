import hashlib
import hmac
import json
from datetime import date, timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from academics.models import Course, Enrollment
from accounts.models import StudentProfile

from .models import FeeAccount, Payment

User = get_user_model()
KEYS = {"RAZORPAY_KEY_ID": "rzp_test_key", "RAZORPAY_KEY_SECRET": "test_secret", "RAZORPAY_WEBHOOK_SECRET": "hook_secret"}


def sign(secret, message):
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def student(email):
    user = User.objects.create_user(email, email, "Student-Pass-2027")
    profile = StudentProfile.objects.create(user=user, full_name="Riya Sharma", mobile="9876543210", state="UP", city="Noida")
    profile.activate()
    profile.save()
    return profile, Token.objects.create(user=user).key


class FinanceTests(APITestCase):
    def setUp(self):
        admin = User.objects.create_superuser("desk", "desk@gbte.in", "desk-pass-123")
        self.admin_token = Token.objects.create(user=admin).key
        self.course = Course.objects.create(slug="ai", title="Diploma in AI", short_title="AI", category="ai",
                                            category_label="AI", programme_type="Diploma", duration="1 Year")
        self.student, self.token = student("riya@example.com")
        self.enrollment = Enrollment.objects.create(student=self.student, course=self.course)

    def as_admin(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.admin_token}")

    def as_student(self, token=None):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token or self.token}")

    def create_plan(self):
        self.as_admin()
        return self.client.post(
            "/api/portal/admin/finance/accounts/",
            {
                "enrollment": self.enrollment.id,
                "total_fee": "30000.00",
                "installments": [
                    {"title": "Installment 1", "amount": "10000.00", "due_date": (date.today() - timedelta(days=3)).isoformat()},
                    {"title": "Installment 2", "amount": "20000.00", "due_date": (date.today() + timedelta(days=30)).isoformat()},
                ],
            },
            format="json",
        )

    def test_fee_plan_rules(self):
        self.as_admin()
        bad = self.client.post(
            "/api/portal/admin/finance/accounts/",
            {"enrollment": self.enrollment.id, "total_fee": "30000", "installments": [{"title": "A", "amount": "100", "due_date": "2027-01-01"}]},
            format="json",
        )
        self.assertIn("installments", bad.data)
        plan = self.create_plan()
        self.assertEqual(plan.status_code, 201)
        self.assertEqual([item["status"] for item in plan.data["installments"]], ["overdue", "due"])
        self.assertEqual(self.client.post("/api/portal/admin/finance/accounts/", {"enrollment": self.enrollment.id, "total_fee": "1"}, format="json").status_code, 400)

    def test_offline_payment_receipt_and_refund(self):
        plan = self.create_plan().data
        first = plan["installments"][0]["id"]
        no_ref = self.client.post("/api/portal/admin/finance/payments/", {"account": plan["id"], "installment": first, "amount": "10000", "method": "upi"}, format="json")
        self.assertIn("reference", no_ref.data)
        too_much = self.client.post("/api/portal/admin/finance/payments/", {"account": plan["id"], "installment": first, "amount": "15000", "method": "cash"}, format="json")
        self.assertIn("amount", too_much.data)
        online = self.client.post("/api/portal/admin/finance/payments/", {"account": plan["id"], "amount": "100", "method": "razorpay"}, format="json")
        self.assertIn("method", online.data)

        paid = self.client.post(
            "/api/portal/admin/finance/payments/",
            {"account": plan["id"], "installment": first, "amount": "10000", "method": "upi", "reference": "UTR123456"},
            format="json",
        )
        self.assertEqual(paid.status_code, 201)
        self.assertTrue(paid.data["receipt_number"].startswith("GBET-R-"))
        receipt = self.client.get(paid.data["receipt_url"].split("8000")[1])
        self.assertEqual(receipt.status_code, 200)
        self.assertTrue(receipt.content.startswith(b"%PDF"))

        detail = self.client.get(f"/api/portal/admin/finance/accounts/{plan['id']}/").data
        self.assertEqual((detail["net_paid"], detail["balance"]), ("10000.00", "20000.00"))
        self.assertEqual(detail["installments"][0]["status"], "paid")

        over = self.client.post("/api/portal/admin/finance/refunds/", {"payment": paid.data["id"], "amount": "20000", "reason": "x"}, format="json")
        self.assertEqual(over.status_code, 400)
        refund = self.client.post("/api/portal/admin/finance/refunds/", {"payment": paid.data["id"], "amount": "2500", "reason": "Fee concession"}, format="json")
        self.assertEqual(refund.status_code, 201)
        detail = self.client.get(f"/api/portal/admin/finance/accounts/{plan['id']}/").data
        self.assertEqual((detail["refunded"], detail["balance"]), ("2500.00", "22500.00"))

        self.assertEqual(self.client.delete(f"/api/portal/admin/finance/installments/{first}/").status_code, 409)
        summary = self.client.get("/api/portal/admin/finance/summary/").data
        self.assertEqual((summary["collected"], summary["refunded"], summary["outstanding"]), ("10000.00", "2500.00", "22500.00"))

        self.as_student()
        mine = self.client.get("/api/portal/finance/summary/").data
        self.assertFalse(mine["online_enabled"])
        self.assertEqual(mine["accounts"][0]["payments"][0]["receipt_number"], paid.data["receipt_number"])
        self.assertEqual(self.client.get(mine["accounts"][0]["payments"][0]["receipt_url"].split("8000")[1]).status_code, 200)

    def test_online_payment_disabled_without_keys(self):
        plan = self.create_plan().data
        self.as_student()
        res = self.client.post(f"/api/portal/finance/installments/{plan['installments'][0]['id']}/pay/")
        self.assertEqual(res.status_code, 503)
        self.assertFalse(Payment.objects.exists())

    @override_settings(**KEYS)
    def test_razorpay_flow_with_signature_checks(self):
        plan = self.create_plan().data
        installment = plan["installments"][0]["id"]
        self.as_student()
        with mock.patch("finance.razorpay.create_order", return_value={"id": "order_TEST123"}) as create:
            started = self.client.post(f"/api/portal/finance/installments/{installment}/pay/")
        self.assertEqual(started.status_code, 201)
        self.assertEqual((started.data["amount"], started.data["order_id"], started.data["key_id"]), (1000000, "order_TEST123", "rzp_test_key"))
        self.assertEqual(str(create.call_args.args[0]), "10000.00")
        payment_id = started.data["payment_id"]

        self.assertEqual(self.client.get("/api/portal/finance/summary/").data["accounts"][0]["payments"], [])
        forged = self.client.post(
            f"/api/portal/finance/payments/{payment_id}/verify/",
            {"razorpay_order_id": "order_TEST123", "razorpay_payment_id": "pay_ABC", "razorpay_signature": "forged"},
            format="json",
        )
        self.assertEqual(forged.status_code, 400)
        wrong_order = self.client.post(
            f"/api/portal/finance/payments/{payment_id}/verify/",
            {"razorpay_order_id": "order_OTHER", "razorpay_payment_id": "pay_ABC", "razorpay_signature": sign("test_secret", b"order_OTHER|pay_ABC")},
            format="json",
        )
        self.assertEqual(wrong_order.status_code, 400)
        good = self.client.post(
            f"/api/portal/finance/payments/{payment_id}/verify/",
            {"razorpay_order_id": "order_TEST123", "razorpay_payment_id": "pay_ABC", "razorpay_signature": sign("test_secret", b"order_TEST123|pay_ABC")},
            format="json",
        )
        self.assertEqual(good.status_code, 200)
        self.assertEqual(good.data["status"], "paid")
        self.assertEqual(Payment.objects.get(pk=payment_id).gateway_payment_id, "pay_ABC")
        again = self.client.post(f"/api/portal/finance/installments/{installment}/pay/")
        self.assertEqual(again.status_code, 400)

        other, other_token = student("other@example.com")
        self.as_student(other_token)
        self.assertEqual(self.client.get("/api/portal/finance/summary/").data["accounts"], [])
        self.assertEqual(self.client.post(f"/api/portal/finance/payments/{payment_id}/verify/", {}, format="json").status_code, 404)
        receipt_url = good.data["receipt_url"].split("8000")[1]
        self.client.credentials()
        self.assertEqual(self.client.get(receipt_url).status_code, 200)

    @override_settings(**KEYS)
    def test_webhook_marks_payment_paid(self):
        plan = self.create_plan().data
        self.as_student()
        with mock.patch("finance.razorpay.create_order", return_value={"id": "order_HOOK"}):
            payment_id = self.client.post(f"/api/portal/finance/installments/{plan['installments'][1]['id']}/pay/").data["payment_id"]
        self.client.credentials()
        body = json.dumps({"event": "payment.captured", "payload": {"payment": {"entity": {"id": "pay_HOOK", "order_id": "order_HOOK"}}}}).encode()
        bad = self.client.generic("POST", "/api/portal/finance/razorpay/webhook/", body, content_type="application/json", HTTP_X_RAZORPAY_SIGNATURE="bad")
        self.assertEqual(bad.status_code, 400)
        ok = self.client.generic(
            "POST", "/api/portal/finance/razorpay/webhook/", body, content_type="application/json", HTTP_X_RAZORPAY_SIGNATURE=sign("hook_secret", body)
        )
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(Payment.objects.get(pk=payment_id).status, "paid")

    def test_access_rules(self):
        plan = self.create_plan().data
        self.as_student()
        self.assertEqual(self.client.get("/api/portal/admin/finance/summary/").status_code, 403)
        self.assertEqual(self.client.post("/api/portal/admin/finance/payments/", {}, format="json").status_code, 403)
        self.client.credentials()
        self.assertEqual(self.client.get("/api/portal/finance/summary/").status_code, 401)
        self.assertEqual(self.client.get("/api/portal/finance/receipt/forged-token/").status_code, 403)
        self.assertTrue(FeeAccount.objects.filter(pk=plan["id"]).exists())
