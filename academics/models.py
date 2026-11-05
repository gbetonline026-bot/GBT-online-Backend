import os
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models
from django.utils import timezone

from .video import embed_url

VIDEO_EXTENSIONS = ["mp4", "webm"]
MATERIAL_EXTENSIONS = ["pdf", "doc", "docx", "ppt", "pptx", "xls", "xlsx", "zip"]


def _check_size(file, megabytes):
    if file.size > megabytes * 1024 * 1024:
        raise ValidationError(f"The file is larger than {megabytes} MB.")


def validate_video_size(file):
    _check_size(file, settings.LMS_MAX_VIDEO_MB)


def validate_material_size(file):
    _check_size(file, settings.LMS_MAX_MATERIAL_MB)


def _private_name(folder, filename):
    ext = os.path.splitext(filename)[1].lower()
    return f"{folder}/{timezone.now():%Y/%m}/{uuid.uuid4().hex}{ext}"


def lesson_video_path(instance, filename):
    return _private_name("lesson-videos", filename)


def study_material_path(instance, filename):
    return _private_name("study-materials", filename)


class Course(models.Model):
    class ProgrammeType(models.TextChoices):
        DIPLOMA = "Diploma", "Diploma"
        CERTIFICATE = "Certificate", "Certificate"

    slug = models.SlugField(max_length=80, unique=True, help_text="Must match the website URL /courses/<slug>.")
    title = models.CharField(max_length=180)
    short_title = models.CharField(max_length=120)
    category = models.CharField(max_length=40)
    category_label = models.CharField(max_length=80)
    programme_type = models.CharField(max_length=20, choices=ProgrammeType.choices)
    duration = models.CharField(max_length=40)
    eligibility = models.CharField(max_length=200, blank=True)
    summary = models.TextField(blank=True)
    image = models.CharField(max_length=200, blank=True, help_text="Website image path, e.g. /photos/interior.jpg")
    sequential = models.BooleanField(default=True, help_text="Lessons unlock one after another.")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["title"]

    def __str__(self):
        return self.title


class Module(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="modules")
    number = models.PositiveSmallIntegerField()
    title = models.CharField(max_length=180)
    outcome = models.TextField(blank=True)

    class Meta:
        ordering = ["course", "number"]
        constraints = [models.UniqueConstraint(fields=["course", "number"], name="unique_module_number")]

    def __str__(self):
        return f"{self.course.short_title} · Module {self.number}: {self.title}"


class Lesson(models.Model):
    class VideoSource(models.TextChoices):
        NONE = "none", "No video"
        YOUTUBE = "youtube", "YouTube link"
        VIMEO = "vimeo", "Vimeo link"
        UPLOAD = "upload", "Uploaded file"

    module = models.ForeignKey(Module, on_delete=models.CASCADE, related_name="lessons")
    order = models.PositiveSmallIntegerField()
    title = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    video_source = models.CharField(max_length=10, choices=VideoSource.choices, default=VideoSource.NONE)
    video_url = models.URLField(blank=True, help_text="YouTube or Vimeo link (use unlisted / private-with-embed videos).")
    video_file = models.FileField(
        upload_to=lesson_video_path,
        blank=True,
        validators=[FileExtensionValidator(VIDEO_EXTENSIONS), validate_video_size],
    )
    duration_minutes = models.PositiveSmallIntegerField(null=True, blank=True)
    is_published = models.BooleanField(default=False, help_text="Only published lessons are visible to students.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["module__number", "order"]
        constraints = [models.UniqueConstraint(fields=["module", "order"], name="unique_lesson_order")]

    def __str__(self):
        return f"{self.module} · {self.order}. {self.title}"

    @property
    def course(self):
        return self.module.course

    @property
    def embed_url(self):
        return embed_url(self.video_source, self.video_url)

    @property
    def has_video(self):
        if self.video_source == self.VideoSource.UPLOAD:
            return bool(self.video_file)
        return bool(self.embed_url)

    def clean(self):
        if self.video_source in {self.VideoSource.YOUTUBE, self.VideoSource.VIMEO} and not self.embed_url:
            raise ValidationError({"video_url": f"Enter a valid {self.get_video_source_display()}."})
        if self.video_source == self.VideoSource.UPLOAD and not self.video_file:
            raise ValidationError({"video_file": "Upload an MP4 or WebM file."})
        if self.is_published and not (self.has_video or self.description.strip()):
            raise ValidationError("Add a video or a written description before publishing this lesson.")


class StudyMaterial(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="materials")
    module = models.ForeignKey(Module, on_delete=models.CASCADE, related_name="materials", null=True, blank=True)
    title = models.CharField(max_length=180)
    description = models.CharField(max_length=300, blank=True)
    file = models.FileField(
        upload_to=study_material_path,
        validators=[FileExtensionValidator(MATERIAL_EXTENSIONS), validate_material_size],
    )
    original_name = models.CharField(max_length=200, blank=True, editable=False)
    size = models.PositiveBigIntegerField(default=0, editable=False)
    is_published = models.BooleanField(default=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["module__number", "title"]

    def __str__(self):
        return self.title

    def clean(self):
        if self.module_id and self.course_id and self.module.course_id != self.course_id:
            raise ValidationError({"module": "The module must belong to the selected course."})

    def save(self, *args, **kwargs):
        if self.file and not self.original_name:
            self.original_name = os.path.basename(getattr(self.file, "name", ""))[:200]
        if self.file:
            self.size = self.file.size
        super().save(*args, **kwargs)

    @property
    def extension(self):
        return os.path.splitext(self.file.name)[1].lstrip(".").lower()


class Batch(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="batches")
    name = models.CharField(max_length=120, help_text="e.g. Jan 2027 Weekend")
    faculty_name = models.CharField(max_length=120, blank=True, help_text="Real faculty name; leave blank until confirmed.")
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-start_date"]
        verbose_name_plural = "batches"

    def __str__(self):
        return f"{self.course.short_title} · {self.name}"

    def clean(self):
        if self.end_date and self.start_date and self.end_date < self.start_date:
            raise ValidationError({"end_date": "The end date must be after the start date."})


class Enrollment(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        COMPLETED = "completed", "Completed"
        SUSPENDED = "suspended", "Suspended"

    student = models.ForeignKey("accounts.StudentProfile", on_delete=models.CASCADE, related_name="enrollments")
    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name="enrollments")
    batch = models.ForeignKey(Batch, on_delete=models.SET_NULL, null=True, blank=True, related_name="enrollments")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    start_date = models.DateField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    enrolled_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["student", "course"], name="unique_enrollment")]

    def __str__(self):
        return f"{self.student.full_name} → {self.course.short_title}"

    def clean(self):
        if self.batch_id and self.course_id and self.batch.course_id != self.course_id:
            raise ValidationError({"batch": "The batch must belong to the selected course."})

    @property
    def can_learn(self):
        return self.status in {self.Status.ACTIVE, self.Status.COMPLETED}

    @property
    def effective_start(self):
        return self.start_date or (self.batch.start_date if self.batch_id else None)


class LessonProgress(models.Model):
    enrollment = models.ForeignKey(Enrollment, on_delete=models.CASCADE, related_name="progress")
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="progress")
    completed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["enrollment", "lesson"], name="unique_lesson_progress")]

    def __str__(self):
        return f"{self.enrollment} · {self.lesson.title}"
