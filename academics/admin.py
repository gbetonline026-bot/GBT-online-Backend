from django.contrib import admin

from .models import Batch, Course, Enrollment, Lesson, LessonProgress, Module, StudyMaterial


class ModuleInline(admin.TabularInline):
    model = Module
    extra = 0
    fields = ["number", "title", "outcome"]
    show_change_link = True


class LessonInline(admin.StackedInline):
    model = Lesson
    extra = 0
    fields = ["order", "title", "description", "video_source", "video_url", "video_file", "duration_minutes", "is_published"]


class BatchInline(admin.TabularInline):
    model = Batch
    extra = 0
    fields = ["name", "faculty_name", "start_date", "end_date", "is_active"]


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ["title", "programme_type", "category_label", "duration", "sequential", "is_active"]
    list_filter = ["programme_type", "category_label", "is_active"]
    search_fields = ["title", "slug"]
    readonly_fields = ["slug"]
    inlines = [ModuleInline, BatchInline]


@admin.register(Module)
class ModuleAdmin(admin.ModelAdmin):
    list_display = ["__str__", "course", "number"]
    list_filter = ["course"]
    search_fields = ["title", "course__title"]
    inlines = [LessonInline]


@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ["title", "module", "order", "video_source", "duration_minutes", "is_published"]
    list_filter = ["is_published", "video_source", "module__course"]
    list_editable = ["is_published"]
    search_fields = ["title", "module__title", "module__course__title"]
    autocomplete_fields = ["module"]


@admin.register(StudyMaterial)
class StudyMaterialAdmin(admin.ModelAdmin):
    list_display = ["title", "course", "module", "size", "is_published", "uploaded_at"]
    list_filter = ["is_published", "course"]
    search_fields = ["title", "course__title"]
    autocomplete_fields = ["course", "module"]


@admin.register(Batch)
class BatchAdmin(admin.ModelAdmin):
    list_display = ["name", "course", "faculty_name", "start_date", "end_date", "is_active"]
    list_filter = ["is_active", "course"]
    search_fields = ["name", "course__title", "faculty_name"]
    autocomplete_fields = ["course"]


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = ["student", "course", "batch", "status", "start_date", "created_at"]
    list_filter = ["status", "course"]
    search_fields = ["student__full_name", "student__user__email", "course__title"]
    raw_id_fields = ["student"]
    autocomplete_fields = ["course", "batch"]
    readonly_fields = ["enrolled_by", "created_at"]


@admin.register(LessonProgress)
class LessonProgressAdmin(admin.ModelAdmin):
    list_display = ["enrollment", "lesson", "completed_at"]
    search_fields = ["enrollment__student__full_name", "lesson__title"]
    readonly_fields = ["enrollment", "lesson", "completed_at"]
