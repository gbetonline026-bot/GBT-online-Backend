from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.text import slugify


class Post(models.Model):
    class Kind(models.TextChoices):
        NEWS = "news", "News"
        EVENT = "event", "Event"
        ANNOUNCEMENT = "announcement", "Announcement"

    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.NEWS)
    title = models.CharField(max_length=180)
    slug = models.SlugField(max_length=200, unique=True, blank=True)
    summary = models.CharField(max_length=300)
    body = models.TextField(blank=True)
    event_start = models.DateTimeField(null=True, blank=True, help_text="Events only.")
    event_end = models.DateTimeField(null=True, blank=True)
    location = models.CharField(max_length=180, blank=True, help_text="e.g. Online (Zoom) or C-77, Sector 63A, Noida")
    link_url = models.URLField(blank=True, help_text="Registration, webinar or reference link.")
    link_label = models.CharField(max_length=60, blank=True)
    is_published = models.BooleanField(default=False)
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-published_at", "-created_at"]

    def __str__(self):
        return self.title

    def clean(self):
        if self.kind == self.Kind.EVENT and not self.event_start:
            raise ValidationError({"event_start": "Add the event date and time."})
        if self.event_start and self.event_end and self.event_end < self.event_start:
            raise ValidationError({"event_end": "The event cannot end before it starts."})

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.title)[:180] or "post"
            slug, counter = base, 2
            while Post.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base}-{counter}"
                counter += 1
            self.slug = slug
        if self.is_published and not self.published_at:
            self.published_at = timezone.now()
        super().save(*args, **kwargs)
