from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import mixins, serializers, viewsets
from rest_framework.permissions import AllowAny, IsAdminUser

from .models import Post


class PostSerializer(serializers.ModelSerializer):
    class Meta:
        model = Post
        fields = [
            "id",
            "kind",
            "title",
            "slug",
            "summary",
            "body",
            "event_start",
            "event_end",
            "location",
            "link_url",
            "link_label",
            "is_published",
            "published_at",
            "updated_at",
        ]
        read_only_fields = ["slug", "published_at", "updated_at"]

    def validate(self, attrs):
        preview = Post()
        if self.instance:
            for field in ("kind", "event_start", "event_end"):
                setattr(preview, field, getattr(self.instance, field))
        for field, value in attrs.items():
            setattr(preview, field, value)
        try:
            preview.clean()
        except DjangoValidationError as error:
            raise serializers.ValidationError(error.message_dict)
        return attrs


class PublicPostSerializer(PostSerializer):
    class Meta(PostSerializer.Meta):
        fields = [field for field in PostSerializer.Meta.fields if field not in {"is_published", "updated_at"}]


class PublicPostViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    permission_classes = [AllowAny]
    authentication_classes = []
    serializer_class = PublicPostSerializer
    lookup_field = "slug"

    def get_queryset(self):
        queryset = Post.objects.filter(is_published=True)
        kind = self.request.query_params.get("kind")
        if kind in Post.Kind.values:
            queryset = queryset.filter(kind=kind)
        return queryset


class AdminPostViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAdminUser]
    serializer_class = PostSerializer
    queryset = Post.objects.all()
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
