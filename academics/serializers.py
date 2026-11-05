from rest_framework import serializers

from .learning import course_state
from .models import Enrollment


class AdminEnrollmentSerializer(serializers.ModelSerializer):
    course_title = serializers.CharField(source="course.title", read_only=True)
    course_slug = serializers.CharField(source="course.slug", read_only=True)
    batch_name = serializers.CharField(source="batch.name", read_only=True, default=None)
    student_name = serializers.CharField(source="student.full_name", read_only=True)
    student_email = serializers.CharField(source="student.user.email", read_only=True)
    student_code = serializers.CharField(source="student.student_id", read_only=True, default=None)
    progress = serializers.SerializerMethodField()

    class Meta:
        model = Enrollment
        fields = [
            "id",
            "student",
            "student_name",
            "student_email",
            "student_code",
            "course",
            "course_title",
            "course_slug",
            "batch",
            "batch_name",
            "status",
            "start_date",
            "completed_at",
            "created_at",
            "progress",
        ]
        read_only_fields = ["id", "completed_at", "created_at"]
        validators = []

    def get_progress(self, obj):
        state = course_state(obj)
        return {"done": state.done, "total": state.total, "percent": state.percent}

    def validate(self, attrs):
        course = attrs.get("course") or getattr(self.instance, "course", None)
        batch = attrs.get("batch", getattr(self.instance, "batch", None))
        if batch and course and batch.course_id != course.id:
            raise serializers.ValidationError({"batch": "This batch belongs to a different course."})
        if self.instance is None:
            if Enrollment.objects.filter(student=attrs["student"], course=course).exists():
                raise serializers.ValidationError({"course": "The student is already enrolled in this course."})
        elif "course" in attrs and attrs["course"] != self.instance.course:
            raise serializers.ValidationError({"course": "Create a new enrolment instead of changing the course."})
        return attrs
