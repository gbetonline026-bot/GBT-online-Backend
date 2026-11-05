from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from academics.models import Batch, Course, Enrollment, Lesson, LessonProgress, StudyMaterial
from accounts.models import StudentProfile
from finance.models import FeeAccount, Installment, Payment, Refund

User = get_user_model()

MARKER = "(Demo content – replace before launch.)"
COURSE = "interior-design"
BATCH = "Demo Batch"
MATERIAL = "Module 1 notes (Demo)"
STUDENT = {"email": "demo.student@example.com", "password": "Demo-Student-2027", "name": "Demo Student"}
APPLICANT = {"email": "demo.applicant@example.com", "password": "Demo-Applicant-2027", "name": "Demo Applicant"}

LESSONS = {
    1: {
        "video_source": "youtube",
        "video_url": "https://www.youtube.com/watch?v=kM75uk9oG9I",
        "description": (
            "The elements of design are the tools a designer works with: space, shape and form, line, texture, "
            "pattern, colour and light. The principles – balance, scale and proportion, rhythm, emphasis and "
            "harmony – are the rules for combining them.\n\n"
            "While you watch, note one example of positive and negative space in a room you know."
        ),
    },
    2: {
        "description": (
            "A client brief records what the client needs before any drawing starts.\n\n"
            "Read every brief for: who uses the space and how; must-have and nice-to-have items; budget and "
            "timeline; style references the client likes and dislikes; and fixed constraints such as structure, "
            "services or rental rules.\n\n"
            "Practice: write five questions you would ask a client who wants a home office in a spare bedroom."
        ),
    },
    3: {
        "description": (
            "Accurate site notes save time later in drawing and estimating.\n\n"
            "1. Sketch the room outline first, not to scale.\n"
            "2. Measure each wall clockwise from one corner and write the figure on the sketch.\n"
            "3. Record door and window widths, heights and sill levels.\n"
            "4. Mark switches, sockets, beams, pipes and ceiling height.\n"
            "5. Take photos of every wall and check two diagonals to confirm the room is square.\n\n"
            "Practice: measure one room at home and record it using these steps."
        ),
    },
}

PDF_LINES = [
    "GBET Online - Diploma in Interior Design",
    "Module 1: Foundations of Interior Design (Demo notes)",
    "",
    "Elements of design: space, shape and form, line, texture, pattern, colour, light.",
    "Principles of design: balance, scale and proportion, rhythm, emphasis, harmony.",
    "",
    "Client brief checklist: users and activities, must-haves, budget, timeline,",
    "style references, fixed constraints.",
    "",
    "Site measurement: sketch, measure clockwise, openings, services, photos, diagonals.",
]


def simple_pdf(lines):
    text = ["BT /F1 12 Tf 56 780 Td 16 TL"]
    for line in lines:
        escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        text.append(f"({escaped}) Tj T*")
    text.append("ET")
    stream = "\n".join(text).encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def make_student(data, active):
    user = User.objects.filter(username=data["email"]).first() or User(username=data["email"], email=data["email"])
    user.first_name = data["name"]
    user.set_password(data["password"])
    user.save()
    profile, _ = StudentProfile.objects.get_or_create(
        user=user,
        defaults={"full_name": data["name"], "mobile": "9000000001" if active else "9000000002", "state": "Uttar Pradesh", "city": "Noida"},
    )
    profile.course_interest = "Diploma in Interior Design"
    if active:
        profile.activate()
    else:
        profile.status = StudentProfile.Status.PENDING
    profile.save()
    return profile


class Command(BaseCommand):
    help = "Create (or with --remove, delete) clearly labelled demo data for trying the student portal locally."

    def add_arguments(self, parser):
        parser.add_argument("--remove", action="store_true", help="Delete all demo data and return demo lessons to draft.")

    def handle(self, *args, **options):
        if options["remove"]:
            self.remove()
        else:
            self.create()

    @transaction.atomic
    def create(self):
        if not Course.objects.filter(slug=COURSE).exists():
            call_command("import_catalog", verbosity=0)
        course = Course.objects.get(slug=COURSE)
        lessons = {lesson.order: lesson for lesson in Lesson.objects.filter(module__course=course, module__number=1)}
        for order, content in LESSONS.items():
            lesson = lessons[order]
            if lesson.is_published and MARKER not in lesson.description:
                self.stdout.write(f"Skipped '{lesson.title}' – it already has real published content.")
                continue
            lesson.video_source = content.get("video_source", Lesson.VideoSource.NONE)
            lesson.video_url = content.get("video_url", "")
            lesson.description = f"{content['description']}\n\n{MARKER}"
            lesson.is_published = True
            lesson.full_clean()
            lesson.save()

        if not StudyMaterial.objects.filter(title=MATERIAL).exists():
            StudyMaterial.objects.create(
                course=course,
                module=lessons[1].module,
                title=MATERIAL,
                description="Summary of module 1 for the demo.",
                file=ContentFile(simple_pdf(PDF_LINES), name="module-1-demo-notes.pdf"),
            )
        batch, _ = Batch.objects.get_or_create(course=course, name=BATCH, defaults={"start_date": timezone.localdate()})

        student = make_student(STUDENT, active=True)
        make_student(APPLICANT, active=False)
        enrollment, _ = Enrollment.objects.get_or_create(student=student, course=course, defaults={"batch": batch})
        LessonProgress.objects.get_or_create(enrollment=enrollment, lesson=lessons[1])
        if not FeeAccount.objects.filter(enrollment=enrollment).exists():
            account = FeeAccount.objects.create(enrollment=enrollment, total_fee=Decimal("30000"), note="Demo fee plan")
            today = timezone.localdate()
            for number in (1, 2, 3):
                Installment.objects.create(
                    account=account,
                    number=number,
                    title=f"Installment {number}",
                    amount=Decimal("10000"),
                    due_date=today + timedelta(days=30 * (number - 1)),
                )

        self.stdout.write(self.style.SUCCESS("Demo data is ready."))
        self.stdout.write(
            f"  Student login: {STUDENT['email']} / {STUDENT['password']}  (enrolled in {course.title}, 1 of 3 lessons done, demo fee plan Rs. 30,000)"
        )
        self.stdout.write(f"  Pending applicant: {APPLICANT['email']} / {APPLICANT['password']}  (activate from Admin > Students)")
        self.stdout.write("  Remove everything with: python manage.py demo_data --remove")

    @transaction.atomic
    def remove(self):
        for lesson in Lesson.objects.filter(description__contains=MARKER):
            lesson.video_source, lesson.video_url, lesson.description, lesson.is_published = Lesson.VideoSource.NONE, "", "", False
            lesson.save()
        for material in StudyMaterial.objects.filter(title=MATERIAL):
            material.file.delete(save=False)
            material.delete()
        demo_accounts = FeeAccount.objects.filter(enrollment__student__user__username__in=[STUDENT["email"], APPLICANT["email"]])
        Refund.objects.filter(payment__account__in=demo_accounts).delete()
        Payment.objects.filter(account__in=demo_accounts).delete()
        demo_accounts.delete()
        User.objects.filter(username__in=[STUDENT["email"], APPLICANT["email"]]).delete()
        Batch.objects.filter(name=BATCH, enrollments__isnull=True).delete()
        self.stdout.write(self.style.SUCCESS("Demo data removed."))
