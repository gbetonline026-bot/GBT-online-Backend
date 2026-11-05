from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import SimpleTestCase, TestCase, override_settings

from accounts.models import StudentProfile

from .cloud_storage import CloudinaryPrivateStorage, resource_type
from .files import media_link
from .models import Course, Enrollment, Lesson, Module, StudyMaterial

CLOUD = {
    "STORAGES": {
        "default": {"BACKEND": "academics.cloud_storage.CloudinaryPrivateStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
    "CLOUDINARY_FOLDER": "test-folder",
}


class CloudStorageUnitTests(SimpleTestCase):
    def test_resource_types(self):
        self.assertEqual(resource_type("a/b.mp4"), "video")
        self.assertEqual(resource_type("a/b.PDF"), "raw")
        self.assertEqual(resource_type("a/b.webp"), "image")

    @mock.patch("academics.cloud_storage.cloudinary.uploader.upload_large")
    @mock.patch("academics.cloud_storage.cloudinary.uploader.upload")
    def test_uploads_are_private(self, upload, upload_large):
        storage = CloudinaryPrivateStorage(folder="gbet")
        storage.save("study-materials/2026/11/abc.pdf", ContentFile(b"%PDF", name="abc.pdf"))
        kwargs = upload.call_args.kwargs
        self.assertEqual((kwargs["public_id"], kwargs["resource_type"], kwargs["type"]), ("gbet/study-materials/2026/11/abc.pdf", "raw", "authenticated"))
        storage.save("lesson-videos/2026/11/xyz.mp4", ContentFile(b"0" * 10, name="xyz.mp4"))
        kwargs = upload_large.call_args.kwargs
        self.assertEqual((kwargs["public_id"], kwargs["resource_type"]), ("gbet/lesson-videos/2026/11/xyz", "video"))

    @mock.patch("academics.cloud_storage.cloudinary.uploader.destroy")
    def test_delete(self, destroy):
        CloudinaryPrivateStorage(folder="gbet").delete("lesson-videos/x.mp4")
        destroy.assert_called_once_with("gbet/lesson-videos/x", invalidate=True, resource_type="video", type="authenticated")

    @mock.patch("academics.cloud_storage.cloudinary.utils.private_download_url", return_value="https://api.cloudinary.com/download?sig=1")
    @mock.patch("academics.cloud_storage.cloudinary.utils.cloudinary_url", return_value=("https://res.cloudinary.com/x/video/authenticated/s--sig--/v1/gbet/v.mp4", {}))
    def test_delivery_urls(self, cloudinary_url, private_download_url):
        storage = CloudinaryPrivateStorage(folder="gbet")
        self.assertIn("authenticated", storage.delivery_url("lesson-videos/v.mp4"))
        self.assertEqual(cloudinary_url.call_args.kwargs["sign_url"], True)
        storage.delivery_url("study-materials/n.pdf", attachment=True)
        self.assertEqual(private_download_url.call_args.args, ("gbet/study-materials/n.pdf", ""))
        self.assertTrue(private_download_url.call_args.kwargs["attachment"])
        self.assertIn("expires_at", private_download_url.call_args.kwargs)


@override_settings(**CLOUD)
class CloudMediaViewTests(TestCase):
    @mock.patch("academics.cloud_storage.cloudinary.uploader.upload")
    def setUp(self, upload):
        course = Course.objects.create(slug="ai", title="AI", short_title="AI", category="ai", category_label="AI", programme_type="Diploma", duration="1 Year")
        module = Module.objects.create(course=course, number=1, title="M")
        self.material = StudyMaterial.objects.create(course=course, module=module, title="Notes", file=ContentFile(b"%PDF-1.4", name="notes.pdf"))
        self.assertEqual(self.material.size, 8)
        user = get_user_model().objects.create_user("s@example.com", "s@example.com", "Student-Pass-2027")
        self.student = StudentProfile.objects.create(user=user, full_name="Riya", mobile="9876543210", state="UP", city="Noida")
        self.student.activate()
        self.student.save()
        Enrollment.objects.create(student=self.student, course=course)
        self.lesson = Lesson.objects.create(module=module, order=1, title="L", description="Read", is_published=True)

    @mock.patch("academics.cloud_storage.cloudinary.utils.private_download_url", return_value="https://api.cloudinary.com/v1_1/demo/raw/download?sig=abc")
    def test_material_download_redirects_to_signed_cloudinary_url(self, private_download_url):
        response = self.client.get(media_link("material", self.material.id, self.student.user_id).split("8000")[1])
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "https://api.cloudinary.com/v1_1/demo/raw/download?sig=abc")
        self.assertEqual(response["Cache-Control"], "private, no-store")

    def test_no_redirect_without_access(self):
        self.student.status = StudentProfile.Status.INACTIVE
        self.student.save()
        response = self.client.get(media_link("material", self.material.id, self.student.user_id).split("8000")[1])
        self.assertEqual(response.status_code, 403)

    @mock.patch("academics.cloud_storage.cloudinary.api.resource")
    def test_resaving_material_does_not_call_cloudinary(self, resource):
        self.material.is_published = False
        self.material.save()
        resource.assert_not_called()


class HealthTests(TestCase):
    def test_health(self):
        response = self.client.get("/api/health/")
        self.assertEqual(response.json(), {"status": "ok", "database": "ok"})
