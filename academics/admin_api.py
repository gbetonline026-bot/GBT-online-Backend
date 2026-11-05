from datetime import timedelta

from django.db.models import Count, Prefetch, Q
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import StudentProfile
from leads.models import Enquiry

from .files import delete_stored_file
from .admin_serializers import AdminBatchSerializer, AdminLessonSerializer, AdminMaterialSerializer, AdminModuleSerializer
from .models import Batch, Course, Enrollment, Lesson, Module, StudyMaterial

UPLOAD_PARSERS = [MultiPartParser, FormParser, JSONParser]


class AdminDashboardView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        week_ago = timezone.now() - timedelta(days=7)
        students = StudentProfile.objects.aggregate(
            total=Count("id"),
            pending=Count("id", filter=Q(status=StudentProfile.Status.PENDING)),
            active=Count("id", filter=Q(status=StudentProfile.Status.ACTIVE)),
            inactive=Count("id", filter=Q(status=StudentProfile.Status.INACTIVE)),
        )
        enquiries = Enquiry.objects.aggregate(
            total=Count("id"),
            new=Count("id", filter=Q(status=Enquiry.Status.NEW)),
            called=Count("id", filter=Q(status=Enquiry.Status.CALLED)),
            closed=Count("id", filter=Q(status=Enquiry.Status.CLOSED)),
            last_7_days=Count("id", filter=Q(created_at__gte=week_ago)),
        )
        enrollments = Enrollment.objects.aggregate(
            total=Count("id"),
            active=Count("id", filter=Q(status=Enrollment.Status.ACTIVE)),
            completed=Count("id", filter=Q(status=Enrollment.Status.COMPLETED)),
            suspended=Count("id", filter=Q(status=Enrollment.Status.SUSPENDED)),
        )
        content = {
            "courses": Course.objects.filter(is_active=True).count(),
            "lessons_total": Lesson.objects.count(),
            "lessons_published": Lesson.objects.filter(is_published=True).count(),
            "materials": StudyMaterial.objects.filter(is_published=True).count(),
            "batches_active": Batch.objects.filter(is_active=True).count(),
        }
        top_courses = (
            Course.objects.annotate(students=Count("enrollments"))
            .filter(students__gt=0)
            .order_by("-students", "title")
            .values("id", "title", "students")[:5]
        )
        return Response(
            {
                "students": students,
                "enquiries": enquiries,
                "enrollments": enrollments,
                "content": content,
                "top_courses": list(top_courses),
                "recent_enquiries": list(
                    Enquiry.objects.values("id", "full_name", "course", "status", "source", "created_at")[:5]
                ),
                "pending_students": list(
                    StudentProfile.objects.filter(status=StudentProfile.Status.PENDING)
                    .values("id", "full_name", "course_interest", "created_at")[:5]
                ),
            }
        )


class AdminCourseViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsAdminUser]
    http_method_names = ["get", "patch", "head", "options"]
    queryset = Course.objects.all()

    def list(self, request):
        courses = Course.objects.annotate(
            lessons_total=Count("modules__lessons", distinct=True),
            lessons_published=Count("modules__lessons", filter=Q(modules__lessons__is_published=True), distinct=True),
            modules_total=Count("modules", distinct=True),
            students=Count("enrollments", distinct=True),
        ).prefetch_related(Prefetch("batches", queryset=Batch.objects.filter(is_active=True)))
        return Response(
            [
                {
                    "id": course.id,
                    "slug": course.slug,
                    "title": course.title,
                    "programme_type": course.programme_type,
                    "category_label": course.category_label,
                    "duration": course.duration,
                    "image": course.image,
                    "is_active": course.is_active,
                    "sequential": course.sequential,
                    "modules_total": course.modules_total,
                    "lessons_total": course.lessons_total,
                    "lessons_published": course.lessons_published,
                    "students": course.students,
                    "batches": AdminBatchSerializer(course.batches.all(), many=True).data,
                }
                for course in courses
            ]
        )

    def detail_payload(self, course):
        context = {"request": self.request}
        modules = course.modules.prefetch_related("lessons__progress")
        return {
            "id": course.id,
            "slug": course.slug,
            "title": course.title,
            "short_title": course.short_title,
            "programme_type": course.programme_type,
            "category_label": course.category_label,
            "duration": course.duration,
            "image": course.image,
            "is_active": course.is_active,
            "sequential": course.sequential,
            "students": course.enrollments.count(),
            "modules": [
                {
                    **AdminModuleSerializer(module).data,
                    "lessons": AdminLessonSerializer(module.lessons.all(), many=True, context=context).data,
                }
                for module in modules
            ],
            "materials": AdminMaterialSerializer(course.materials.select_related("module"), many=True, context=context).data,
            "batches": AdminBatchSerializer(course.batches.all(), many=True).data,
        }

    def retrieve(self, request, pk=None):
        return Response(self.detail_payload(self.get_object()))

    def partial_update(self, request, pk=None):
        course = self.get_object()
        changed = []
        for field in ("sequential", "is_active"):
            if field in request.data:
                value = request.data[field]
                if not isinstance(value, bool):
                    return Response({field: ["Must be true or false."]}, status=status.HTTP_400_BAD_REQUEST)
                setattr(course, field, value)
                changed.append(field)
        if changed:
            course.save(update_fields=[*changed, "updated_at"])
        return Response(self.detail_payload(course))


class ProtectedDestroyMixin:
    blocked_message = "This item is in use and cannot be deleted."

    def is_blocked(self, instance):
        return False

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if self.is_blocked(instance):
            return Response({"detail": self.blocked_message}, status=status.HTTP_409_CONFLICT)
        self.perform_destroy(instance)
        return Response(status=status.HTTP_204_NO_CONTENT)


class AdminModuleViewSet(ProtectedDestroyMixin, mixins.CreateModelMixin, mixins.UpdateModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsAdminUser]
    http_method_names = ["post", "patch", "delete", "options"]
    serializer_class = AdminModuleSerializer
    queryset = Module.objects.all()
    blocked_message = "Students have progress in this module. Unpublish its lessons instead of deleting it."

    def is_blocked(self, module):
        return Lesson.objects.filter(module=module, progress__isnull=False).exists()

    def perform_destroy(self, module):
        files = [lesson.video_file for lesson in module.lessons.all() if lesson.video_file]
        module.delete()
        for field in files:
            delete_stored_file(field.storage, field.name)


class AdminLessonViewSet(ProtectedDestroyMixin, mixins.CreateModelMixin, mixins.UpdateModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsAdminUser]
    http_method_names = ["post", "patch", "delete", "options"]
    serializer_class = AdminLessonSerializer
    parser_classes = UPLOAD_PARSERS
    queryset = Lesson.objects.select_related("module")
    blocked_message = "Students have completed this lesson. Unpublish it instead of deleting it."

    def is_blocked(self, lesson):
        return lesson.progress.exists()

    def perform_destroy(self, lesson):
        field = lesson.video_file
        lesson.delete()
        if field:
            delete_stored_file(field.storage, field.name)


class AdminMaterialViewSet(mixins.CreateModelMixin, mixins.UpdateModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsAdminUser]
    http_method_names = ["post", "patch", "delete", "options"]
    serializer_class = AdminMaterialSerializer
    parser_classes = UPLOAD_PARSERS
    queryset = StudyMaterial.objects.all()

    def perform_destroy(self, material):
        field = material.file
        material.delete()
        delete_stored_file(field.storage, field.name)


class AdminBatchViewSet(ProtectedDestroyMixin, mixins.ListModelMixin, mixins.CreateModelMixin, mixins.UpdateModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsAdminUser]
    http_method_names = ["get", "post", "patch", "delete", "options"]
    serializer_class = AdminBatchSerializer
    blocked_message = "This batch has students. Move them to another batch or mark the batch inactive."

    def get_queryset(self):
        queryset = Batch.objects.select_related("course").prefetch_related("enrollments")
        course = self.request.query_params.get("course")
        if course and course.isdigit():
            queryset = queryset.filter(course_id=int(course))
        return queryset

    def is_blocked(self, batch):
        return batch.enrollments.exists()
