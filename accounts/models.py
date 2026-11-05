from django.conf import settings
from django.db import models
from django.utils import timezone


class StudentProfile(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending verification"
        ACTIVE = "active", "Active"
        INACTIVE = "inactive", "Inactive"

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="student_profile")
    full_name = models.CharField(max_length=120)
    student_id = models.CharField(max_length=20, unique=True, null=True, blank=True)
    mobile = models.CharField(max_length=10)
    state = models.CharField(max_length=80)
    city = models.CharField(max_length=80)
    address = models.TextField(blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    course_interest = models.CharField(max_length=180, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    enquiry = models.ForeignKey("leads.Enquiry", null=True, blank=True, on_delete=models.SET_NULL, related_name="students")
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="verified_students"
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "created_at"])]

    def __str__(self):
        return f"{self.full_name} <{self.user.email}>"

    @property
    def email(self):
        return self.user.email

    @property
    def is_active_student(self):
        return self.status == self.Status.ACTIVE and self.user.is_active

    def activate(self, by=None):
        self.status = self.Status.ACTIVE
        if not self.verified_at:
            self.verified_at = timezone.now()
            self.verified_by = by
        if not self.student_id:
            self.student_id = f"GBET{timezone.now():%y}-{self.pk:05d}"
