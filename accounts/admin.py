from django.contrib import admin

from .models import StudentProfile


@admin.register(StudentProfile)
class StudentProfileAdmin(admin.ModelAdmin):
    list_display = ["full_name", "email", "student_id", "mobile", "status", "created_at"]
    list_filter = ["status", "state"]
    search_fields = ["full_name", "user__email", "mobile", "student_id"]
    readonly_fields = ["student_id", "verified_by", "verified_at", "created_at", "updated_at"]
    raw_id_fields = ["user", "enquiry"]
