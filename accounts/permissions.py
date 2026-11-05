from rest_framework.permissions import BasePermission


def student_profile(user):
    return getattr(user, "student_profile", None) if user and user.is_authenticated else None


class IsActiveStudent(BasePermission):
    message = "Only active students can use the student portal."

    def has_permission(self, request, view):
        profile = student_profile(request.user)
        return bool(profile and profile.is_active_student)
