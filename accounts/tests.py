import re
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from leads.models import Enquiry

from .models import StudentProfile

User = get_user_model()
PASSWORD = "Learn-Online-2027"


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class PortalAuthTests(APITestCase):
    def setUp(self):
        cache.clear()
        admin = User.objects.create_superuser("desk", "desk@gbte.in", "desk-pass-123")
        self.admin_token = Token.objects.create(user=admin).key

    def register(self, **extra):
        data = {
            "full_name": "Riya Sharma",
            "email": "Riya@Example.com",
            "mobile": "9876543210",
            "state": "Uttar Pradesh",
            "city": "Noida",
            "course_interest": "Diploma in Interior Design",
            "password": PASSWORD,
        }
        data.update(extra)
        return self.client.post("/api/portal/auth/register/", data, format="json")

    def login(self, email="riya@example.com", password=PASSWORD):
        return self.client.post("/api/portal/auth/login/", {"email": email, "password": password}, format="json")

    def as_admin(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.admin_token}")

    def activate(self, profile):
        self.as_admin()
        res = self.client.patch(f"/api/portal/admin/students/{profile.pk}/", {"status": "active"}, format="json")
        self.client.credentials()
        return res

    def test_registration_is_pending_until_admin_activates(self):
        Enquiry.objects.create(
            full_name="Riya Sharma", mobile="9876543210", email="riya@example.com", state="UP", city="Noida", course="Interior"
        )
        self.assertEqual(self.register().status_code, 201)
        profile = StudentProfile.objects.get()
        self.assertEqual(profile.status, StudentProfile.Status.PENDING)
        self.assertEqual(profile.user.username, "riya@example.com")
        self.assertIsNotNone(profile.enquiry)
        self.assertNotEqual(profile.user.password, PASSWORD)

        pending = self.login()
        self.assertEqual(pending.status_code, 400)
        self.assertEqual(pending.data["code"], "pending")

        self.assertEqual(self.activate(profile).status_code, 200)
        profile.refresh_from_db()
        self.assertTrue(profile.student_id.startswith("GBET"))
        self.assertEqual(len(mail.outbox), 1)

        ok = self.login()
        self.assertEqual(ok.status_code, 200)
        self.assertIn("token", ok.data)
        self.assertEqual(ok.data["student"]["student_id"], profile.student_id)

    def test_registration_validation(self):
        res = self.register(mobile="12345", password="123", full_name="R1")
        self.assertEqual(res.status_code, 400)
        self.assertIn("mobile", res.data)
        self.assertIn("full_name", res.data)
        self.register()
        duplicate = self.register(email="riya@example.com")
        self.assertEqual(duplicate.status_code, 400)
        self.assertIn("email", duplicate.data)

    def test_wrong_password_and_staff_cannot_use_portal_login(self):
        self.register()
        self.activate(StudentProfile.objects.get())
        self.assertEqual(self.login(password="wrong-password").data["code"], "invalid")
        self.assertEqual(self.login(email="desk@gbte.in", password="desk-pass-123").status_code, 400)

    def test_profile_is_private_and_editable(self):
        self.register()
        self.activate(StudentProfile.objects.get())
        token = self.login().data["token"]

        self.assertEqual(self.client.get("/api/portal/me/").status_code, 401)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token}")
        me = self.client.get("/api/portal/me/")
        self.assertEqual(me.data["email"], "riya@example.com")

        patched = self.client.patch(
            "/api/portal/me/", {"city": "Greater Noida", "full_name": "Hacker", "status": "active"}, format="json"
        )
        self.assertEqual(patched.status_code, 200)
        self.assertEqual(patched.data["city"], "Greater Noida")
        self.assertEqual(patched.data["full_name"], "Riya Sharma")

        self.assertEqual(self.client.get("/api/enquiries/").status_code, 403)
        self.assertEqual(self.client.get("/api/portal/admin/students/").status_code, 403)

    def test_logout_and_change_password_rotate_tokens(self):
        self.register()
        self.activate(StudentProfile.objects.get())
        token = self.login().data["token"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token}")

        wrong = self.client.post(
            "/api/portal/auth/change-password/", {"current_password": "nope", "new_password": "Another-Pass-2027"}, format="json"
        )
        self.assertEqual(wrong.status_code, 400)
        changed = self.client.post(
            "/api/portal/auth/change-password/",
            {"current_password": PASSWORD, "new_password": "Another-Pass-2027"},
            format="json",
        )
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(self.client.get("/api/portal/me/").status_code, 401)

        self.client.credentials(HTTP_AUTHORIZATION=f"Token {changed.data['token']}")
        self.assertEqual(self.client.post("/api/portal/auth/logout/").status_code, 204)
        self.assertEqual(self.client.get("/api/portal/me/").status_code, 401)
        self.client.credentials()
        self.assertEqual(self.login(password="Another-Pass-2027").status_code, 200)

    def test_password_reset_flow_does_not_reveal_accounts(self):
        unknown = self.client.post("/api/portal/auth/password-reset/", {"email": "nobody@example.com"}, format="json")
        self.register()
        pending = self.client.post("/api/portal/auth/password-reset/", {"email": "riya@example.com"}, format="json")
        self.assertEqual(unknown.data, pending.data)
        self.assertEqual(len(mail.outbox), 0)

        self.activate(StudentProfile.objects.get())
        mail.outbox.clear()
        self.client.post("/api/portal/auth/password-reset/", {"email": "riya@example.com"}, format="json")
        self.assertEqual(len(mail.outbox), 1)
        uid, token = re.search(r"uid=([^&\s]+)&token=(\S+)", mail.outbox[0].body).groups()

        bad = self.client.post(
            "/api/portal/auth/password-reset/confirm/", {"uid": uid, "token": "bad-token", "password": "Fresh-Pass-2027"}, format="json"
        )
        self.assertEqual(bad.status_code, 400)
        weak = self.client.post(
            "/api/portal/auth/password-reset/confirm/", {"uid": uid, "token": token, "password": "12345678"}, format="json"
        )
        self.assertEqual(weak.status_code, 400)
        good = self.client.post(
            "/api/portal/auth/password-reset/confirm/", {"uid": uid, "token": token, "password": "Fresh-Pass-2027"}, format="json"
        )
        self.assertEqual(good.status_code, 200)
        reused = self.client.post(
            "/api/portal/auth/password-reset/confirm/", {"uid": uid, "token": token, "password": "Other-Pass-2027"}, format="json"
        )
        self.assertEqual(reused.status_code, 400)
        self.assertEqual(self.login(password="Fresh-Pass-2027").status_code, 200)

    def test_student_tokens_expire_but_admin_tokens_do_not(self):
        self.register()
        self.activate(StudentProfile.objects.get())
        token = self.login().data["token"]
        Token.objects.filter(key=token).update(created=timezone.now() - timedelta(hours=13))
        Token.objects.filter(key=self.admin_token).update(created=timezone.now() - timedelta(days=30))

        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token}")
        self.assertEqual(self.client.get("/api/portal/me/").status_code, 401)
        self.as_admin()
        self.assertEqual(self.client.get("/api/enquiries/").status_code, 200)

    def test_admin_adds_student_and_deactivation_ends_session(self):
        self.as_admin()
        created = self.client.post(
            "/api/portal/admin/students/",
            {"full_name": "Aman Verma", "email": "aman@example.com", "mobile": "9123456780", "state": "Delhi", "city": "Delhi"},
            format="json",
        )
        self.assertEqual(created.status_code, 201)
        self.assertTrue(created.data["email_sent"])
        self.assertFalse(created.data["has_password"])
        self.assertEqual(created.data["status"], "active")
        self.assertIn("/student/reset-password?uid=", mail.outbox[0].body)

        uid, token = re.search(r"uid=([^&\s]+)&token=(\S+)", mail.outbox[0].body).groups()
        self.client.credentials()
        self.client.post(
            "/api/portal/auth/password-reset/confirm/", {"uid": uid, "token": token, "password": "Aman-Learns-2027"}, format="json"
        )
        student_token = self.login("aman@example.com", "Aman-Learns-2027").data["token"]

        self.as_admin()
        listed = self.client.get("/api/portal/admin/students/?q=aman")
        self.assertEqual(len(listed.data), 1)
        self.client.patch(f"/api/portal/admin/students/{created.data['id']}/", {"status": "inactive"}, format="json")

        self.client.credentials(HTTP_AUTHORIZATION=f"Token {student_token}")
        self.assertEqual(self.client.get("/api/portal/me/").status_code, 401)
        self.client.credentials()
        self.assertEqual(self.login("aman@example.com", "Aman-Learns-2027").data["code"], "inactive")

    def test_public_cannot_manage_students(self):
        self.assertEqual(self.client.get("/api/portal/admin/students/").status_code, 401)
        self.assertEqual(self.client.post("/api/portal/admin/students/", {}, format="json").status_code, 401)
