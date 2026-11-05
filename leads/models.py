from django.db import models


class Enquiry(models.Model):
    class Status(models.TextChoices):
        NEW = "new", "New"
        CALLED = "called", "Called"
        CLOSED = "closed", "Closed"

    class Source(models.TextChoices):
        WEBSITE = "website", "Website form"
        BROCHURE = "brochure", "Brochure"
        APPLICATION = "application", "Online application"
        COUNSELLING = "counselling", "Counselling booking"
        SCHOLARSHIP = "scholarship", "Scholarship request"

    full_name = models.CharField(max_length=120)
    mobile = models.CharField(max_length=10)
    email = models.EmailField()
    state = models.CharField(max_length=80)
    city = models.CharField(max_length=80)
    course = models.CharField(max_length=180)
    message = models.TextField(blank=True)
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.WEBSITE)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "enquiry"
        verbose_name_plural = "enquiries"
        indexes = [
            models.Index(fields=["status", "created_at"]),
        ]

    def __str__(self):
        return f"{self.full_name} · {self.course}"
