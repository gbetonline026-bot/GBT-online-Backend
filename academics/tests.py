import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from accounts.models import StudentProfile

from .files import media_link
from .models import Batch, Course, Enrollment, Lesson, Module, StudyMaterial
from .video import embed_url

User = get_user_model()
MEDIA = tempfile.mkdtemp(prefix="gbet-lms-test-")


def make_student(email, status=StudentProfile.Status.ACTIVE):
    user = User.objects.create_user(email, email, "Student-Pass-2027")
    profile = StudentProfile.objects.create(user=user, full_name="Test Student", mobile="9876543210", state="UP", city="Noida", status=status)
    profile.activate()
    profile.save()
    return profile, Token.objects.create(user=user).key


@override_settings(MEDIA_ROOT=MEDIA)
class LearningApiTests(APITestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        self.course = Course.objects.create(
            slug="interior-design", title="Diploma in Interior Design", short_title="Interior Design", category="design",
            category_label="Design & Styling", programme_type="Diploma", duration="1 Year", image="/photos/interior.jpg",
        )
        self.other = Course.objects.create(
            slug="fashion-design", title="Diploma in Fashion Design", short_title="Fashion Design", category="design",
            category_label="Design & Styling", programme_type="Diploma", duration="1 Year",
        )
        m1 = Module.objects.create(course=self.course, number=1, title="Foundations")
        m2 = Module.objects.create(course=self.course, number=2, title="Drawing")
        self.l1 = Lesson.objects.create(module=m1, order=1, title="Intro", description="Welcome", is_published=True,
                                        video_source="youtube", video_url="https://youtu.be/dQw4w9WgXcQ", duration_minutes=12)
        self.l2 = Lesson.objects.create(
            module=m1, order=2, title="Uploaded", is_published=True, video_source="upload",
            video_file=SimpleUploadedFile("clip.mp4", b"0123456789" * 100, content_type="video/mp4"),
        )
        self.l3 = Lesson.objects.create(module=m2, order=1, title="Sketching", description="Read this", is_published=True)
        self.draft = Lesson.objects.create(module=m2, order=2, title="Draft lesson")
        self.material = StudyMaterial.objects.create(
            course=self.course, module=m1, title="Notes",
            file=SimpleUploadedFile("notes.pdf", b"%PDF-1.4 test", content_type="application/pdf"),
        )
        self.foreign_material = StudyMaterial.objects.create(
            course=self.other, title="Other notes", file=SimpleUploadedFile("other.pdf", b"%PDF-1.4 x"),
        )
        self.student, self.token = make_student("learner@example.com")
        self.batch = Batch.objects.create(course=self.course, name="Jan 2027", faculty_name="Ms. Asha Rao", start_date="2027-01-10")
        self.enrollment = Enrollment.objects.create(student=self.student, course=self.course, batch=self.batch)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token}")

    def test_my_courses_and_summary(self):
        courses = self.client.get("/api/portal/learning/courses/").data
        self.assertEqual(len(courses), 1)
        self.assertEqual(courses[0]["course"]["slug"], "interior-design")
        self.assertEqual(courses[0]["faculty_name"], "Ms. Asha Rao")
        self.assertEqual(courses[0]["start_date"], "2027-01-10")
        self.assertEqual(courses[0]["progress"], {"done": 0, "total": 3, "percent": 0})
        summary = self.client.get("/api/portal/learning/summary/").data
        self.assertEqual((summary["enrolled"], summary["active"], summary["overall_percent"]), (1, 1, 0))

    def test_course_outline_hides_drafts_and_locks_in_order(self):
        data = self.client.get("/api/portal/learning/courses/interior-design/").data
        lessons = [lesson for module in data["modules"] for lesson in module["lessons"]]
        self.assertEqual([lesson["title"] for lesson in lessons], ["Intro", "Uploaded", "Sketching"])
        self.assertEqual([lesson["locked"] for lesson in lessons], [False, True, True])
        self.assertEqual(data["modules"][0]["materials"], 1)
        self.assertEqual(len(data["materials"]), 1)

    def test_locked_lesson_cannot_be_opened_or_completed(self):
        self.assertEqual(self.client.get(f"/api/portal/learning/lessons/{self.l2.id}/").status_code, 403)
        self.assertEqual(self.client.post(f"/api/portal/learning/lessons/{self.l2.id}/complete/").status_code, 403)
        self.assertEqual(self.client.get(f"/api/portal/learning/lessons/{self.draft.id}/").status_code, 404)

    def test_completing_lessons_saves_progress_and_unlocks_next(self):
        lesson = self.client.get(f"/api/portal/learning/lessons/{self.l1.id}/").data
        self.assertEqual(lesson["video"]["type"], "embed")
        self.assertIn("youtube-nocookie.com/embed/dQw4w9WgXcQ", lesson["video"]["url"])
        self.assertEqual((lesson["prev_id"], lesson["next_id"], lesson["next_locked"]), (None, self.l2.id, True))

        done = self.client.post(f"/api/portal/learning/lessons/{self.l1.id}/complete/").data
        self.assertEqual(done["progress"], {"done": 1, "total": 3, "percent": 33})
        self.assertFalse(done["next_locked"])
        self.client.post(f"/api/portal/learning/lessons/{self.l1.id}/complete/")
        self.assertEqual(self.enrollment.progress.count(), 1)

        second = self.client.get(f"/api/portal/learning/lessons/{self.l2.id}/").data
        self.assertEqual(second["video"]["type"], "file")
        self.assertIn("/api/portal/learning/media/", second["video"]["url"])

    def test_other_students_and_suspended_enrolments_are_blocked(self):
        _, other_token = make_student("other@example.com")
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {other_token}")
        self.assertEqual(self.client.get("/api/portal/learning/courses/").data, [])
        self.assertEqual(self.client.get("/api/portal/learning/courses/interior-design/").status_code, 404)
        self.assertEqual(self.client.get(f"/api/portal/learning/lessons/{self.l1.id}/").status_code, 404)

        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token}")
        self.enrollment.status = Enrollment.Status.SUSPENDED
        self.enrollment.save()
        self.assertEqual(self.client.get("/api/portal/learning/courses/interior-design/").status_code, 403)
        self.client.credentials()
        self.assertEqual(self.client.get("/api/portal/learning/courses/").status_code, 401)

    def test_signed_media_links(self):
        self.client.post(f"/api/portal/learning/lessons/{self.l1.id}/complete/")
        self.client.credentials()
        video = media_link("lesson", self.l2.id, self.student.user_id).split("8000")[1]
        full = self.client.get(video)
        self.assertEqual(full.status_code, 200)
        self.assertEqual(b"".join(full.streaming_content), b"0123456789" * 100)
        part = self.client.get(video, HTTP_RANGE="bytes=10-19")
        self.assertEqual(part.status_code, 206)
        self.assertEqual(part["Content-Range"], "bytes 10-19/1000")
        self.assertEqual(b"".join(part.streaming_content), b"0123456789")
        self.assertEqual(self.client.get(video, HTTP_RANGE="bytes=5000-").status_code, 416)

        material = self.client.get(media_link("material", self.material.id, self.student.user_id).split("8000")[1])
        self.assertEqual(material.status_code, 200)
        self.assertIn("attachment", material["Content-Disposition"])

        foreign = media_link("material", self.foreign_material.id, self.student.user_id).split("8000")[1]
        self.assertEqual(self.client.get(foreign).status_code, 403)
        self.assertEqual(self.client.get(video[:-6] + "xxxxx/").status_code, 403)

        self.student.status = StudentProfile.Status.INACTIVE
        self.student.save()
        self.assertEqual(self.client.get(video).status_code, 403)

    def test_locked_video_link_is_refused(self):
        self.client.credentials()
        video = media_link("lesson", self.l2.id, self.student.user_id).split("8000")[1]
        self.assertEqual(self.client.get(video).status_code, 403)


class AdminEnrollmentTests(APITestCase):
    def setUp(self):
        admin = User.objects.create_superuser("desk", "desk@gbte.in", "desk-pass-123")
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=admin).key}")
        self.course = Course.objects.create(slug="ai", title="Diploma in AI", short_title="AI", category="ai",
                                            category_label="AI & Technology", programme_type="Diploma", duration="1 Year")
        self.other = Course.objects.create(slug="ml", title="ML", short_title="ML", category="ai",
                                           category_label="AI & Technology", programme_type="Certificate", duration="6 Months")
        self.batch = Batch.objects.create(course=self.other, name="Other batch", start_date="2027-01-01")
        self.student, self.student_token = make_student("s@example.com")

    def test_admin_assigns_course_once(self):
        courses = self.client.get("/api/portal/admin/courses/").data
        self.assertEqual(len(courses), 2)
        created = self.client.post("/api/portal/admin/enrollments/", {"student": self.student.id, "course": self.course.id}, format="json")
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.data["progress"]["percent"], 0)
        again = self.client.post("/api/portal/admin/enrollments/", {"student": self.student.id, "course": self.course.id}, format="json")
        self.assertEqual(again.status_code, 400)
        wrong_batch = self.client.post(
            "/api/portal/admin/enrollments/", {"student": self.student.id, "course": self.other.id, "batch": 999}, format="json"
        )
        self.assertEqual(wrong_batch.status_code, 400)
        mismatch = self.client.patch(f"/api/portal/admin/enrollments/{created.data['id']}/", {"batch": self.batch.id}, format="json")
        self.assertEqual(mismatch.status_code, 400)
        completed = self.client.patch(f"/api/portal/admin/enrollments/{created.data['id']}/", {"status": "completed"}, format="json")
        self.assertIsNotNone(completed.data["completed_at"])
        listed = self.client.get(f"/api/portal/admin/enrollments/?student={self.student.id}").data
        self.assertEqual(len(listed), 1)

    def test_students_cannot_use_admin_endpoints(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.student_token}")
        self.assertEqual(self.client.get("/api/portal/admin/courses/").status_code, 403)
        self.assertEqual(self.client.post("/api/portal/admin/enrollments/", {}, format="json").status_code, 403)


class ContentRulesTests(TestCase):
    def test_video_links(self):
        self.assertEqual(embed_url("youtube", "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=3"),
                         "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ?rel=0&modestbranding=1")
        self.assertIsNotNone(embed_url("vimeo", "https://vimeo.com/123456789"))
        self.assertIsNone(embed_url("youtube", "https://example.com/watch?v=dQw4w9WgXcQ"))

    def test_lesson_validation(self):
        course = Course.objects.create(slug="x", title="X", short_title="X", category="ai", category_label="AI",
                                       programme_type="Diploma", duration="1 Year")
        module = Module.objects.create(course=course, number=1, title="M")
        with self.assertRaises(ValidationError):
            Lesson(module=module, order=1, title="Bad", video_source="youtube", video_url="https://example.com").full_clean()
        with self.assertRaises(ValidationError):
            Lesson(module=module, order=2, title="Empty", is_published=True).full_clean()

    def test_import_catalog_is_idempotent(self):
        call_command("import_catalog", verbosity=0)
        call_command("import_catalog", verbosity=0)
        self.assertEqual(Course.objects.count(), 22)
        self.assertEqual(Module.objects.count(), 110)
        self.assertEqual(Lesson.objects.count(), 330)
        self.assertFalse(Lesson.objects.filter(is_published=True).exists())
