from django.contrib import admin

from .models import Post


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ["title", "kind", "event_start", "is_published", "published_at"]
    list_filter = ["kind", "is_published"]
    search_fields = ["title", "summary"]
    readonly_fields = ["slug", "published_at"]
