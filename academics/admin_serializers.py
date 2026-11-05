from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Max
from rest_framework import serializers

from .files import delete_stored_file, media_link
from .models import Batch, Lesson, Module, StudyMaterial


def run_model_clean(instance):
    try:
        instance.clean()
    except DjangoValidationError as error:
        raise serializers.ValidationError(getattr(error, "message_dict", None) or {"detail": error.messages})


class AdminModuleSerializer(serializers.ModelSerializer):
    number = serializers.IntegerField(min_value=1, required=False)

    class Meta:
        model = Module
        fields = ["id", "course", "number", "title", "outcome"]
        validators = []

    def validate(self, attrs):
        course = attrs.get("course") or self.instance.course
        if self.instance and "course" in attrs and attrs["course"] != self.instance.course:
            raise serializers.ValidationError({"course": "Modules cannot move between courses."})
        number = attrs.get("number")
        if number is None and self.instance is None:
            attrs["number"] = (course.modules.aggregate(top=Max("number"))["top"] or 0) + 1
        elif number is not None:
            clash = Module.objects.filter(course=course, number=number).exclude(pk=getattr(self.instance, "pk", None))
            if clash.exists():
                raise serializers.ValidationError({"number": f"Module {number} already exists in this course."})
        return attrs


class AdminLessonSerializer(serializers.ModelSerializer):
    order = serializers.IntegerField(min_value=1, required=False)
    video_file_name = serializers.SerializerMethodField()
    preview_url = serializers.SerializerMethodField()
    completions = serializers.SerializerMethodField()
    clear_video_file = serializers.BooleanField(write_only=True, required=False, default=False)

    class Meta:
        model = Lesson
        fields = [
            "id",
            "module",
            "order",
            "title",
            "description",
            "video_source",
            "video_url",
            "video_file",
            "clear_video_file",
            "video_file_name",
            "preview_url",
            "duration_minutes",
            "is_published",
            "completions",
            "updated_at",
        ]
        read_only_fields = ["updated_at"]
        validators = []
        extra_kwargs = {"video_file": {"write_only": True, "required": False, "allow_null": True}}

    def get_video_file_name(self, obj):
        return obj.video_file.name.rsplit("/", 1)[-1] if obj.video_file else None

    def get_preview_url(self, obj):
        if obj.video_source == Lesson.VideoSource.UPLOAD and obj.video_file:
            return media_link("lesson", obj.id, self.context["request"].user.id)
        return obj.embed_url

    def get_completions(self, obj):
        return obj.progress.count()

    def validate(self, attrs):
        clear = attrs.pop("clear_video_file", False)
        module = attrs.get("module") or self.instance.module
        if self.instance and "module" in attrs and attrs["module"].course_id != self.instance.module.course_id:
            raise serializers.ValidationError({"module": "Lessons can only move between modules of the same course."})
        order = attrs.get("order")
        if order is None and (self.instance is None or "module" in attrs and attrs["module"] != self.instance.module):
            attrs["order"] = (module.lessons.aggregate(top=Max("order"))["top"] or 0) + 1
        elif order is not None:
            clash = Lesson.objects.filter(module=module, order=order).exclude(pk=getattr(self.instance, "pk", None))
            if clash.exists():
                raise serializers.ValidationError({"order": f"Lesson {order} already exists in this module."})

        preview = Lesson(module=module)
        if self.instance:
            for field in ["title", "description", "video_source", "video_url", "video_file", "duration_minutes", "is_published"]:
                setattr(preview, field, getattr(self.instance, field))
        for field, value in attrs.items():
            setattr(preview, field, value)
        if clear and "video_file" not in attrs:
            preview.video_file = None
            attrs["video_file"] = None
        if preview.video_source != Lesson.VideoSource.UPLOAD and self.instance and self.instance.video_file:
            attrs["video_file"] = None
        if preview.video_source not in {Lesson.VideoSource.YOUTUBE, Lesson.VideoSource.VIMEO}:
            attrs["video_url"] = ""
        run_model_clean(preview)
        return attrs

    def update(self, instance, validated_data):
        old_file = instance.video_file.name if instance.video_file else None
        lesson = super().update(instance, validated_data)
        new_file = lesson.video_file.name if lesson.video_file else None
        if old_file and old_file != new_file:
            delete_stored_file(lesson.video_file.storage, old_file)
        return lesson


class AdminMaterialSerializer(serializers.ModelSerializer):
    download_url = serializers.SerializerMethodField()
    extension = serializers.CharField(read_only=True)

    class Meta:
        model = StudyMaterial
        fields = [
            "id",
            "course",
            "module",
            "title",
            "description",
            "file",
            "original_name",
            "size",
            "extension",
            "is_published",
            "uploaded_at",
            "download_url",
        ]
        read_only_fields = ["original_name", "size", "uploaded_at"]
        extra_kwargs = {"file": {"write_only": True}}

    def get_fields(self):
        fields = super().get_fields()
        if self.instance is not None:
            fields["file"].required = False
        return fields

    def get_download_url(self, obj):
        return media_link("material", obj.id, self.context["request"].user.id)

    def validate(self, attrs):
        course = attrs.get("course") or self.instance.course
        module = attrs.get("module", getattr(self.instance, "module", None))
        if module and module.course_id != course.id:
            raise serializers.ValidationError({"module": "The module must belong to the same course."})
        return attrs

    def update(self, instance, validated_data):
        old_file = instance.file.name if "file" in validated_data else None
        if old_file:
            instance.original_name = ""
        material = super().update(instance, validated_data)
        if old_file and old_file != material.file.name:
            delete_stored_file(material.file.storage, old_file)
        return material


class AdminBatchSerializer(serializers.ModelSerializer):
    course_title = serializers.CharField(source="course.title", read_only=True)
    students = serializers.IntegerField(source="enrollments.count", read_only=True)

    class Meta:
        model = Batch
        fields = ["id", "course", "course_title", "name", "faculty_name", "start_date", "end_date", "is_active", "students"]

    def validate(self, attrs):
        start = attrs.get("start_date", getattr(self.instance, "start_date", None))
        end = attrs.get("end_date", getattr(self.instance, "end_date", None))
        if start and end and end < start:
            raise serializers.ValidationError({"end_date": "The end date must be after the start date."})
        if self.instance and "course" in attrs and attrs["course"] != self.instance.course and self.instance.enrollments.exists():
            raise serializers.ValidationError({"course": "This batch already has students; it cannot move to another course."})
        return attrs
