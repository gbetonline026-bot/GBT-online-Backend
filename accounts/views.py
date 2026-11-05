import logging

from django.contrib.auth import get_user_model
from django.contrib.auth.models import update_last_login
from django.db.models import Q
from rest_framework import generics, mixins, status, viewsets
from rest_framework.authtoken.models import Token
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from . import emails
from .models import StudentProfile
from .permissions import IsActiveStudent
from .serializers import (
    AdminStudentSerializer,
    ChangePasswordSerializer,
    LoginSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetSerializer,
    RegisterSerializer,
    StudentProfileSerializer,
)

logger = logging.getLogger(__name__)
User = get_user_model()


def deliver(send, profile):
    try:
        send(profile)
        return True
    except Exception:
        logger.exception("Could not send portal email to %s", profile.user.email)
        return False


def new_token(user):
    Token.objects.filter(user=user).delete()
    return Token.objects.create(user=user).key


class PublicAuthView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "portal_auth"


class RegisterView(PublicAuthView):
    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(
            {"detail": "Your request has been received. You can log in once the admissions team verifies your admission."},
            status=status.HTTP_201_CREATED,
        )


class LoginView(PublicAuthView):
    def post(self, request):
        serializer = LoginSerializer(data=request.data, context={"request": request})
        if not serializer.is_valid():
            errors = serializer.errors
            detail = errors.get("detail", ["Enter your email and password."])
            code = getattr(detail[0], "code", "invalid") if detail else "invalid"
            return Response({"detail": str(detail[0]), "code": code}, status=status.HTTP_400_BAD_REQUEST)
        user = serializer.validated_data["user"]
        update_last_login(None, user)
        return Response({"token": new_token(user), "student": StudentProfileSerializer(user.student_profile).data})


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        Token.objects.filter(user=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class PasswordResetView(PublicAuthView):
    def post(self, request):
        serializer = PasswordResetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"].strip().lower()
        profile = (
            StudentProfile.objects.select_related("user")
            .filter(user__username__iexact=email, status=StudentProfile.Status.ACTIVE, user__is_active=True)
            .first()
        )
        if profile:
            deliver(emails.send_password_reset, profile)
        return Response({"detail": "If an active student account uses this email, a password reset link has been sent to it."})


class PasswordResetConfirmView(PublicAuthView):
    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        if not serializer.is_valid():
            errors = serializer.errors
            message = errors.get("detail") or errors.get("password") or ["Check the details and try again."]
            return Response({"detail": str(message[0]), "errors": errors}, status=status.HTTP_400_BAD_REQUEST)
        user = serializer.validated_data["user"]
        user.set_password(serializer.validated_data["password"])
        user.save(update_fields=["password"])
        Token.objects.filter(user=user).delete()
        return Response({"detail": "Your password has been set. You can now log in."})


class ChangePasswordView(APIView):
    permission_classes = [IsActiveStudent]

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        request.user.set_password(serializer.validated_data["new_password"])
        request.user.save(update_fields=["password"])
        return Response({"detail": "Your password has been changed.", "token": new_token(request.user)})


class MeView(generics.RetrieveUpdateAPIView):
    permission_classes = [IsActiveStudent]
    serializer_class = StudentProfileSerializer
    http_method_names = ["get", "patch", "head", "options"]

    def get_object(self):
        return self.request.user.student_profile


class AdminStudentViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [IsAdminUser]
    serializer_class = AdminStudentSerializer
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        queryset = StudentProfile.objects.select_related("user")
        status_filter = self.request.query_params.get("status")
        if status_filter in StudentProfile.Status.values:
            queryset = queryset.filter(status=status_filter)
        query = self.request.query_params.get("q", "").strip()
        if query:
            queryset = queryset.filter(
                Q(full_name__icontains=query)
                | Q(user__email__icontains=query)
                | Q(mobile__icontains=query)
                | Q(student_id__icontains=query)
                | Q(course_interest__icontains=query)
            )
        return queryset

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        profile = serializer.save()
        data = self.get_serializer(profile).data
        data["email_sent"] = deliver(emails.send_set_password, profile)
        return Response(data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        profile = self.get_object()
        before = profile.status
        serializer = self.get_serializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        profile = serializer.save()
        data = self.get_serializer(profile).data
        if profile.status != before:
            if profile.status == StudentProfile.Status.ACTIVE:
                sender = emails.send_activated if profile.user.has_usable_password() else emails.send_set_password
                data["email_sent"] = deliver(sender, profile)
            else:
                Token.objects.filter(user=profile.user).delete()
        return Response(data)

    @action(detail=True, methods=["post"], url_path="send-password-link")
    def send_password_link(self, request, pk=None):
        profile = self.get_object()
        if not profile.is_active_student:
            return Response({"detail": "Activate the student before sending a password link."}, status=status.HTTP_400_BAD_REQUEST)
        sent = deliver(emails.send_password_reset if profile.user.has_usable_password() else emails.send_set_password, profile)
        if not sent:
            return Response({"detail": "The email could not be sent. Check the email settings."}, status=status.HTTP_502_BAD_GATEWAY)
        return Response({"detail": f"A password link has been emailed to {profile.user.email}."})
