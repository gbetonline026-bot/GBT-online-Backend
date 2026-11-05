from django.contrib.auth import get_user_model
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from leads.models import Enquiry

User = get_user_model()


class NewsTests(APITestCase):
    def setUp(self):
        admin = User.objects.create_superuser("desk", "desk@gbte.in", "desk-pass-123")
        self.admin = {"HTTP_AUTHORIZATION": f"Token {Token.objects.create(user=admin).key}"}

    def test_admin_publishes_and_public_reads(self):
        event_without_date = self.client.post("/api/portal/admin/news/", {"kind": "event", "title": "Webinar", "summary": "Intro"}, format="json", **self.admin)
        self.assertIn("event_start", event_without_date.data)

        draft = self.client.post(
            "/api/portal/admin/news/",
            {"kind": "event", "title": "Career Webinar", "summary": "Live Q&A", "event_start": "2027-01-20T11:00:00+05:30"},
            format="json",
            **self.admin,
        )
        self.assertEqual(draft.status_code, 201)
        self.assertEqual(draft.data["slug"], "career-webinar")
        self.assertEqual(self.client.get("/api/news/").data, [])
        self.assertEqual(self.client.get("/api/news/career-webinar/").status_code, 404)

        published = self.client.patch(f"/api/portal/admin/news/{draft.data['id']}/", {"is_published": True}, format="json", **self.admin)
        self.assertIsNotNone(published.data["published_at"])
        listed = self.client.get("/api/news/").data
        self.assertEqual(len(listed), 1)
        self.assertNotIn("is_published", listed[0])
        self.assertEqual(self.client.get("/api/news/?kind=news").data, [])
        self.assertEqual(self.client.get("/api/news/career-webinar/").data["title"], "Career Webinar")

        again = self.client.post("/api/portal/admin/news/", {"title": "Career Webinar", "summary": "x"}, format="json", **self.admin)
        self.assertEqual(again.data["slug"], "career-webinar-2")

    def test_public_cannot_write(self):
        self.assertEqual(self.client.post("/api/portal/admin/news/", {}, format="json").status_code, 401)
        self.assertEqual(self.client.post("/api/news/", {}, format="json").status_code, 405)

    def test_new_enquiry_sources(self):
        for source in ("application", "counselling", "scholarship"):
            res = self.client.post(
                "/api/enquiries/",
                {"full_name": "Riya Sharma", "mobile": "9876543210", "email": "r@example.com", "state": "UP", "city": "Noida", "course": "AI", "source": source},
                format="json",
            )
            self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(Enquiry.objects.filter(source="counselling").count(), 1)
