from django.contrib.auth import get_user_model
from django.core import signing
from django.db.models import Q
from django.http import Http404, HttpResponseForbidden, HttpResponseGone
from django.utils import timezone
from django.views.decorators.http import require_safe
from rest_framework import mixins, viewsets
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsActiveStudent

from .files import media_link, read_media_token, serve_file
from .learning import course_state
from .models import Course, Enrollment, Lesson, LessonProgress, StudyMaterial
from .serializers import AdminEnrollmentSerializer

User = get_user_model()


class LessonLocked(PermissionDenied):
    default_detail = "Complete the previous lesson to unlock this one."
    default_code = "locked"


def enrollments_for(profile):
    return Enrollment.objects.filter(student=profile, course__is_active=True).select_related("course", "batch")


def enrollment_or_404(request, course):
    enrollment = enrollments_for(request.user.student_profile).filter(course=course).first()
    if enrollment is None:
        raise NotFound("You are not enrolled in this course.")
    if not enrollment.can_learn:
        raise PermissionDenied("Access to this course is paused. Please contact the academic team.")
    return enrollment


def progress_dict(state):
    return {"done": state.done, "total": state.total, "percent": state.percent}


def course_card(enrollment, state):
    course, batch = enrollment.course, enrollment.batch
    start = enrollment.effective_start
    next_lesson = state.next_lesson
    return {
        "id": enrollment.id,
        "status": enrollment.status,
        "start_date": start.isoformat() if start else None,
        "course": {
            "slug": course.slug,
            "title": course.title,
            "short_title": course.short_title,
            "programme_type": course.programme_type,
            "duration": course.duration,
            "category_label": course.category_label,
            "image": course.image,
        },
        "batch": {"name": batch.name, "start_date": batch.start_date.isoformat(), "end_date": batch.end_date.isoformat() if batch.end_date else None}
        if batch
        else None,
        "faculty_name": (batch.faculty_name if batch else "") or None,
        "progress": progress_dict(state),
        "next_lesson_id": next_lesson.id if next_lesson else None,
    }


def material_dict(material, user):
    return {
        "id": material.id,
        "title": material.title,
        "description": material.description,
        "extension": material.extension,
        "size": material.size,
        "module": {"number": material.module.number, "title": material.module.title} if material.module_id else None,
        "download_url": media_link("material", material.id, user.id),
    }


class LearningSummaryView(APIView):
    permission_classes = [IsActiveStudent]

    def get(self, request):
        enrollments = list(enrollments_for(request.user.student_profile))
        done = total = 0
        for enrollment in enrollments:
            if enrollment.can_learn:
                state = course_state(enrollment)
                done += state.done
                total += state.total
        status = [enrollment.status for enrollment in enrollments]
        return Response(
            {
                "enrolled": len(enrollments),
                "active": status.count(Enrollment.Status.ACTIVE),
                "completed": status.count(Enrollment.Status.COMPLETED),
                "lessons_done": done,
                "lessons_total": total,
                "overall_percent": round(done * 100 / total) if total else 0,
            }
        )


class MyCoursesView(APIView):
    permission_classes = [IsActiveStudent]

    def get(self, request):
        return Response(
            [course_card(enrollment, course_state(enrollment)) for enrollment in enrollments_for(request.user.student_profile)]
        )


class CourseLearningView(APIView):
    permission_classes = [IsActiveStudent]

    def get(self, request, slug):
        course = Course.objects.filter(slug=slug, is_active=True).first()
        if course is None:
            raise NotFound("Course not found.")
        enrollment = enrollment_or_404(request, course)
        state = course_state(enrollment)
        by_module = {}
        for lesson in state.lessons:
            by_module.setdefault(lesson.module_id, []).append(lesson)
        materials = StudyMaterial.objects.filter(course=course, is_published=True).select_related("module")
        material_counts = {}
        for material in materials:
            material_counts[material.module_id] = material_counts.get(material.module_id, 0) + 1
        modules = []
        for module in course.modules.all():
            lessons = by_module.get(module.id, [])
            modules.append(
                {
                    "id": module.id,
                    "number": module.number,
                    "title": module.title,
                    "outcome": module.outcome,
                    "done": sum(1 for lesson in lessons if lesson.id in state.completed),
                    "total": len(lessons),
                    "materials": material_counts.get(module.id, 0),
                    "lessons": [
                        {
                            "id": lesson.id,
                            "title": lesson.title,
                            "duration_minutes": lesson.duration_minutes,
                            "kind": "video" if lesson.has_video else "reading",
                            "completed": lesson.id in state.completed,
                            "locked": lesson.id not in state.unlocked,
                        }
                        for lesson in lessons
                    ],
                }
            )
        data = course_card(enrollment, state)
        data["sequential"] = course.sequential
        data["modules"] = modules
        data["materials"] = [material_dict(material, request.user) for material in materials]
        return Response(data)


class LessonMixin:
    permission_classes = [IsActiveStudent]

    def load(self, request, pk):
        lesson = Lesson.objects.filter(pk=pk, is_published=True, module__course__is_active=True).select_related("module__course").first()
        if lesson is None:
            raise NotFound("Lesson not found.")
        enrollment = enrollment_or_404(request, lesson.module.course)
        state = course_state(enrollment)
        if lesson.id not in state.unlocked:
            raise LessonLocked()
        return lesson, enrollment, state


class LessonView(LessonMixin, APIView):
    def get(self, request, pk):
        lesson, enrollment, state = self.load(request, pk)
        prev_lesson, next_lesson = state.neighbours(lesson)
        if lesson.video_source == Lesson.VideoSource.UPLOAD and lesson.video_file:
            video = {"type": "file", "url": media_link("lesson", lesson.id, request.user.id)}
        elif lesson.embed_url:
            video = {"type": "embed", "provider": lesson.video_source, "url": lesson.embed_url}
        else:
            video = None
        return Response(
            {
                "id": lesson.id,
                "title": lesson.title,
                "description": lesson.description,
                "duration_minutes": lesson.duration_minutes,
                "module": {"number": lesson.module.number, "title": lesson.module.title},
                "course": {"slug": lesson.module.course.slug, "title": lesson.module.course.title},
                "video": video,
                "completed": lesson.id in state.completed,
                "prev_id": prev_lesson.id if prev_lesson else None,
                "next_id": next_lesson.id if next_lesson else None,
                "next_locked": bool(next_lesson and next_lesson.id not in state.unlocked),
                "progress": progress_dict(state),
            }
        )


class CompleteLessonView(LessonMixin, APIView):
    def post(self, request, pk):
        lesson, enrollment, _ = self.load(request, pk)
        LessonProgress.objects.get_or_create(enrollment=enrollment, lesson=lesson)
        state = course_state(enrollment)
        _, next_lesson = state.neighbours(lesson)
        return Response(
            {
                "completed": True,
                "progress": progress_dict(state),
                "next_id": next_lesson.id if next_lesson else None,
                "next_locked": bool(next_lesson and next_lesson.id not in state.unlocked),
            }
        )


class MaterialsView(APIView):
    permission_classes = [IsActiveStudent]

    def get(self, request):
        courses = []
        for enrollment in enrollments_for(request.user.student_profile):
            if not enrollment.can_learn:
                continue
            materials = StudyMaterial.objects.filter(course=enrollment.course, is_published=True).select_related("module")
            courses.append(
                {
                    "course": {"slug": enrollment.course.slug, "title": enrollment.course.title},
                    "materials": [material_dict(material, request.user) for material in materials],
                }
            )
        return Response(courses)


@require_safe
def media_view(request, token):
    try:
        claim = read_media_token(token)
    except signing.SignatureExpired:
        return HttpResponseGone("This link has expired. Reload the page to get a new one.")
    except signing.BadSignature:
        return HttpResponseForbidden("Invalid link.")

    user = User.objects.filter(pk=claim.get("u"), is_active=True).select_related("student_profile").first()
    if user and user.is_staff:
        if claim.get("k") == "lesson":
            lesson = Lesson.objects.filter(pk=claim.get("i")).first()
            if lesson is None or not lesson.video_file:
                raise Http404
            return serve_file(request, lesson.video_file, f"lesson-{lesson.id}.{lesson.video_file.name.rsplit('.', 1)[-1]}", attachment=False)
        if claim.get("k") == "material":
            material = StudyMaterial.objects.filter(pk=claim.get("i")).first()
            if material is None:
                raise Http404
            return serve_file(request, material.file, material.original_name or f"{material.title}.{material.extension}", attachment=True)
        raise Http404
    profile = getattr(user, "student_profile", None) if user else None
    if profile is None or not profile.is_active_student:
        return HttpResponseForbidden("Your account is not active.")

    if claim.get("k") == "lesson":
        lesson = Lesson.objects.filter(pk=claim.get("i"), is_published=True).select_related("module__course").first()
        if lesson is None or not lesson.video_file:
            raise Http404
        enrollment = enrollments_for(profile).filter(course=lesson.module.course).first()
        if enrollment is None or not enrollment.can_learn or lesson.id not in course_state(enrollment).unlocked:
            return HttpResponseForbidden("You do not have access to this lesson.")
        return serve_file(request, lesson.video_file, f"lesson-{lesson.id}.{lesson.video_file.name.rsplit('.', 1)[-1]}", attachment=False)

    if claim.get("k") == "material":
        material = StudyMaterial.objects.filter(pk=claim.get("i"), is_published=True).first()
        if material is None:
            raise Http404
        enrollment = enrollments_for(profile).filter(course_id=material.course_id).first()
        if enrollment is None or not enrollment.can_learn:
            return HttpResponseForbidden("You do not have access to this file.")
        name = material.original_name or f"{material.title}.{material.extension}"
        return serve_file(request, material.file, name, attachment=True)

    raise Http404


class AdminEnrollmentViewSet(mixins.ListModelMixin, mixins.CreateModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsAdminUser]
    serializer_class = AdminEnrollmentSerializer
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        queryset = Enrollment.objects.select_related("course", "batch", "student__user")
        params = self.request.query_params
        for key, field in (("student", "student_id"), ("course", "course_id"), ("batch", "batch_id")):
            value = params.get(key)
            if value and value.isdigit():
                queryset = queryset.filter(**{field: int(value)})
        if params.get("status") in Enrollment.Status.values:
            queryset = queryset.filter(status=params["status"])
        query = params.get("q", "").strip()
        if query:
            queryset = queryset.filter(
                Q(student__full_name__icontains=query)
                | Q(student__user__email__icontains=query)
                | Q(student__student_id__icontains=query)
                | Q(course__title__icontains=query)
            )
        return queryset

    def perform_create(self, serializer):
        serializer.save(enrolled_by=self.request.user)

    def perform_update(self, serializer):
        status = serializer.validated_data.get("status")
        extra = {}
        if status == Enrollment.Status.COMPLETED and not serializer.instance.completed_at:
            extra["completed_at"] = timezone.now()
        elif status and status != Enrollment.Status.COMPLETED:
            extra["completed_at"] = None
        serializer.save(**extra)
