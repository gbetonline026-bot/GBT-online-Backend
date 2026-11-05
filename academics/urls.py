from django.urls import path
from rest_framework.routers import SimpleRouter

from . import admin_api, views

router = SimpleRouter()
router.register("admin/enrollments", views.AdminEnrollmentViewSet, basename="admin-enrollment")
router.register("admin/courses", admin_api.AdminCourseViewSet, basename="admin-course")
router.register("admin/modules", admin_api.AdminModuleViewSet, basename="admin-module")
router.register("admin/lessons", admin_api.AdminLessonViewSet, basename="admin-lesson")
router.register("admin/materials", admin_api.AdminMaterialViewSet, basename="admin-material")
router.register("admin/batches", admin_api.AdminBatchViewSet, basename="admin-batch")

urlpatterns = [
    path("learning/summary/", views.LearningSummaryView.as_view()),
    path("learning/courses/", views.MyCoursesView.as_view()),
    path("learning/courses/<slug:slug>/", views.CourseLearningView.as_view()),
    path("learning/lessons/<int:pk>/", views.LessonView.as_view()),
    path("learning/lessons/<int:pk>/complete/", views.CompleteLessonView.as_view()),
    path("learning/materials/", views.MaterialsView.as_view()),
    path("learning/media/<str:token>/", views.media_view),
    path("admin/dashboard/", admin_api.AdminDashboardView.as_view()),
    *router.urls,
]
