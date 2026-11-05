import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from accounts.models import StudentProfile
from leads.models import Enquiry

from .models import Batch, Course, Enrollment, Lesson, LessonProgress, Module, StudyMaterial

User = get_user_model()
MEDIA = tempfile.mkdtemp(prefix="gbet-admin-test-")


@override_settings(MEDIA_ROOT=MEDIA)
class AdminContentApiTests(APITestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        admin = User.objects.create_superuser("desk", "desk@gbte.in", "desk-pass-123")
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=admin).key}")
        self.course = Course.objects.create(slug="ai", title="Diploma in AI", short_title="AI", category="ai",
                                            category_label="AI & Technology", programme_type="Diploma", duration="1 Year")
        self.module = Module.objects.create(course=self.course, number=1, title="Python")
        user = User.objects.create_user("s@example.com", "s@example.com", "Student-Pass-2027")
        self.student = StudentProfile.objects.create(user=user, full_name="Riya Sharma", mobile="9876543210", state="UP", city="Noida")
        self.student.activate()
        self.student.save()
        self.student_token = Token.objects.create(user=user).key

    def test_dashboard_counts(self):
        Enquiry.objects.create(full_name="A", mobile="9876543210", email="a@example.com", state="UP", city="Noida", course="AI")
        Enrollment.objects.create(student=self.student, course=self.course)
        data = self.client.get("/api/portal/admin/dashboard/").data
        self.assertEqual(data["students"]["active"], 1)
        self.assertEqual(data["enquiries"]["new"], 1)
        self.assertEqual(data["enrollments"]["active"], 1)
        self.assertEqual(data["top_courses"][0]["students"], 1)

    def test_course_list_detail_and_settings(self):
        listed = self.client.get("/api/portal/admin/courses/").data
        self.assertEqual(listed[0]["modules_total"], 1)
        detail = self.client.get(f"/api/portal/admin/courses/{self.course.id}/").data
        self.assertEqual(detail["modules"][0]["title"], "Python")
        updated = self.client.patch(f"/api/portal/admin/courses/{self.course.id}/", {"sequential": False}, format="json")
        self.assertFalse(updated.data["sequential"])
        bad = self.client.patch(f"/api/portal/admin/courses/{self.course.id}/", {"is_active": "yes"}, format="json")
        self.assertEqual(bad.status_code, 400)

    def test_module_and_lesson_crud_with_validation(self):
        module = self.client.post("/api/portal/admin/modules/", {"course": self.course.id, "title": "Machine Learning"}, format="json")
        self.assertEqual(module.data["number"], 2)
        clash = self.client.patch(f"/api/portal/admin/modules/{module.data['id']}/", {"number": 1}, format="json")
        self.assertEqual(clash.status_code, 400)

        draft = self.client.post("/api/portal/admin/lessons/", {"module": self.module.id, "title": "Intro"}, format="json")
        self.assertEqual((draft.status_code, draft.data["order"]), (201, 1))
        unpublishable = self.client.patch(f"/api/portal/admin/lessons/{draft.data['id']}/", {"is_published": True}, format="json")
        self.assertEqual(unpublishable.status_code, 400)
        bad_link = self.client.patch(
            f"/api/portal/admin/lessons/{draft.data['id']}/", {"video_source": "youtube", "video_url": "https://example.com/x"}, format="json"
        )
        self.assertIn("video_url", bad_link.data)
        good = self.client.patch(
            f"/api/portal/admin/lessons/{draft.data['id']}/",
            {"video_source": "youtube", "video_url": "https://youtu.be/dQw4w9WgXcQ", "is_published": True, "duration_minutes": 9},
            format="json",
        )
        self.assertEqual(good.status_code, 200)
        self.assertIn("youtube-nocookie.com/embed/dQw4w9WgXcQ", good.data["preview_url"])

        uploaded = self.client.post(
            "/api/portal/admin/lessons/",
            {"module": self.module.id, "title": "Clip", "video_source": "upload", "is_published": "true",
             "video_file": SimpleUploadedFile("clip.mp4", b"0" * 200, content_type="video/mp4")},
            format="multipart",
        )
        self.assertEqual(uploaded.status_code, 201, uploaded.data)
        self.assertEqual(uploaded.data["order"], 2)
        self.assertTrue(uploaded.data["video_file_name"].endswith(".mp4"))
        preview = self.client.get(uploaded.data["preview_url"].split("8000")[1])
        self.assertEqual(preview.status_code, 200)
        preview.close()
        wrong_type = self.client.post(
            "/api/portal/admin/lessons/",
            {"module": self.module.id, "title": "Bad", "video_source": "upload",
             "video_file": SimpleUploadedFile("clip.exe", b"MZ", content_type="application/octet-stream")},
            format="multipart",
        )
        self.assertEqual(wrong_type.status_code, 400)

        switched = self.client.patch(
            f"/api/portal/admin/lessons/{uploaded.data['id']}/", {"video_source": "none", "description": "Now a reading lesson"}, format="json"
        )
        self.assertIsNone(switched.data["video_file_name"])

        enrollment = Enrollment.objects.create(student=self.student, course=self.course)
        LessonProgress.objects.create(enrollment=enrollment, lesson_id=draft.data["id"])
        self.assertEqual(self.client.delete(f"/api/portal/admin/lessons/{draft.data['id']}/").status_code, 409)
        self.assertEqual(self.client.delete(f"/api/portal/admin/modules/{self.module.id}/").status_code, 409)
        self.assertEqual(self.client.delete(f"/api/portal/admin/lessons/{uploaded.data['id']}/").status_code, 204)
        self.assertEqual(self.client.delete(f"/api/portal/admin/modules/{module.data['id']}/").status_code, 204)

    def test_materials_and_batches(self):
        created = self.client.post(
            "/api/portal/admin/materials/",
            {"course": self.course.id, "module": self.module.id, "title": "Notes",
             "file": SimpleUploadedFile("python-notes.pdf", b"%PDF-1.4", content_type="application/pdf")},
            format="multipart",
        )
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(created.data["original_name"], "python-notes.pdf")
        download = self.client.get(created.data["download_url"].split("8000")[1])
        self.assertEqual(download.status_code, 200)
        download.close()
        hidden = self.client.patch(f"/api/portal/admin/materials/{created.data['id']}/", {"is_published": False}, format="json")
        self.assertFalse(hidden.data["is_published"])
        bad = self.client.post(
            "/api/portal/admin/materials/",
            {"course": self.course.id, "title": "Virus", "file": SimpleUploadedFile("x.exe", b"MZ")},
            format="multipart",
        )
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(self.client.delete(f"/api/portal/admin/materials/{created.data['id']}/").status_code, 204)
        self.assertFalse(StudyMaterial.objects.exists())

        batch = self.client.post(
            "/api/portal/admin/batches/",
            {"course": self.course.id, "name": "Jan 2027", "start_date": "2027-01-10", "end_date": "2026-12-01"},
            format="json",
        )
        self.assertEqual(batch.status_code, 400)
        batch = self.client.post("/api/portal/admin/batches/", {"course": self.course.id, "name": "Jan 2027", "start_date": "2027-01-10"}, format="json")
        self.assertEqual(batch.status_code, 201)
        Enrollment.objects.create(student=self.student, course=self.course, batch_id=batch.data["id"])
        self.assertEqual(self.client.get(f"/api/portal/admin/batches/?course={self.course.id}").data[0]["students"], 1)
        self.assertEqual(self.client.delete(f"/api/portal/admin/batches/{batch.data['id']}/").status_code, 409)
        enrolments = self.client.get(f"/api/portal/admin/enrollments/?batch={batch.data['id']}&q=riya").data
        self.assertEqual(enrolments[0]["student_name"], "Riya Sharma")

    def test_students_are_blocked_from_admin_content_apis(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.student_token}")
        for method, url in [
            ("get", "/api/portal/admin/dashboard/"),
            ("get", f"/api/portal/admin/courses/{self.course.id}/"),
            ("post", "/api/portal/admin/lessons/"),
            ("post", "/api/portal/admin/materials/"),
            ("get", "/api/portal/admin/batches/"),
        ]:
            self.assertEqual(getattr(self.client, method)(url).status_code, 403, url)
