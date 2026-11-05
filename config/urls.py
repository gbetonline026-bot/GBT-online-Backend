from django.contrib import admin
from django.urls import include, path
from rest_framework.authtoken.views import obtain_auth_token

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/token/", obtain_auth_token),
    path("api/portal/", include("accounts.urls")),
    path("api/portal/", include("academics.urls")),
    path("api/portal/", include("finance.urls")),
    path("api/", include("cms.urls")),
    path("api/", include("leads.urls")),
]
