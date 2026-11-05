from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter()
router.register("admin/students", views.AdminStudentViewSet, basename="admin-student")

urlpatterns = [
    path("auth/register/", views.RegisterView.as_view()),
    path("auth/login/", views.LoginView.as_view()),
    path("auth/logout/", views.LogoutView.as_view()),
    path("auth/password-reset/", views.PasswordResetView.as_view()),
    path("auth/password-reset/confirm/", views.PasswordResetConfirmView.as_view()),
    path("auth/change-password/", views.ChangePasswordView.as_view()),
    path("me/", views.MeView.as_view()),
    *router.urls,
]
