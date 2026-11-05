import json
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

from academics.models import Course, Lesson, Module

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "catalog.json"


class Command(BaseCommand):
    help = (
        "Create or update the 22 website courses, their modules and one draft lesson per curriculum topic. "
        "Existing lesson content (videos, descriptions, publish status) is never overwritten."
    )

    def add_arguments(self, parser):
        parser.add_argument("--file", default=str(FIXTURE))

    @transaction.atomic
    def handle(self, *args, **options):
        data = json.loads(Path(options["file"]).read_text(encoding="utf-8"))
        created_lessons = 0
        for item in data:
            course, created = Course.objects.update_or_create(
                slug=item["slug"],
                defaults={
                    "title": item["title"],
                    "short_title": item["short_title"],
                    "category": item["category"],
                    "category_label": item["category_label"],
                    "programme_type": item["programme_type"],
                    "duration": item["duration"],
                    "eligibility": item["eligibility"],
                    "summary": item["summary"],
                    "image": item["image"],
                },
            )
            for module_data in item["modules"]:
                module, _ = Module.objects.update_or_create(
                    course=course,
                    number=module_data["number"],
                    defaults={"title": module_data["title"], "outcome": module_data["outcome"]},
                )
                for order, topic in enumerate(module_data["topics"], start=1):
                    _, made = Lesson.objects.get_or_create(module=module, order=order, defaults={"title": topic})
                    created_lessons += made
            self.stdout.write(f"{'Created' if created else 'Updated'} {course.title}")
        self.stdout.write(self.style.SUCCESS(f"{len(data)} courses synced; {created_lessons} new draft lessons."))
