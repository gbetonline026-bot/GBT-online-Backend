from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter()
router.register("news", views.PublicPostViewSet, basename="news")
router.register("portal/admin/news", views.AdminPostViewSet, basename="admin-news")

urlpatterns = router.urls
