import re

from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.db import transaction
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from rest_framework import serializers

from leads.models import Enquiry

from .models import StudentProfile

User = get_user_model()
MOBILE = re.compile(r"^[6-9]\d{9}$")
NAME = re.compile(r"^[A-Za-z][A-Za-z .'-]{1,118}$")


def clean_name(value):
    value = " ".join(value.split())
    if not NAME.fullmatch(value):
        raise serializers.ValidationError("Enter the full name using letters only.")
    return value


def clean_mobile(value):
    value = re.sub(r"\D", "", value)
    if not MOBILE.fullmatch(value):
        raise serializers.ValidationError("Enter a valid 10-digit mobile number.")
    return value


def clean_place(value, label):
    value = " ".join(value.split())
    if len(value) < 2:
        raise serializers.ValidationError(f"Enter the {label}.")
    return value


def email_taken(email, exclude_user=None):
    users = User.objects.filter(username__iexact=email) | User.objects.filter(email__iexact=email)
    if exclude_user is not None:
        users = users.exclude(pk=exclude_user.pk)
    return users.exists()


class ProfileFieldsMixin:
    def validate_full_name(self, value):
        return clean_name(value)

    def validate_mobile(self, value):
        return clean_mobile(value)

    def validate_state(self, value):
        return clean_place(value, "state")

    def validate_city(self, value):
        return clean_place(value, "city")


class RegisterSerializer(ProfileFieldsMixin, serializers.Serializer):
    full_name = serializers.CharField(max_length=120)
    email = serializers.EmailField(max_length=254)
    mobile = serializers.CharField(max_length=14)
    state = serializers.CharField(max_length=80)
    city = serializers.CharField(max_length=80)
    course_interest = serializers.CharField(max_length=180, required=False, allow_blank=True)
    password = serializers.CharField(write_only=True, trim_whitespace=False, max_length=128)

    def validate_email(self, value):
        value = value.strip().lower()
        if email_taken(value):
            raise serializers.ValidationError("An account with this email already exists. Log in or reset your password.")
        return value

    def validate(self, attrs):
        candidate = User(username=attrs["email"], email=attrs["email"], first_name=attrs["full_name"])
        try:
            validate_password(attrs["password"], candidate)
        except Exception as error:
            raise serializers.ValidationError({"password": list(getattr(error, "messages", [str(error)]))})
        return attrs

    @transaction.atomic
    def create(self, data):
        user = User(username=data["email"], email=data["email"], first_name=data["full_name"][:150])
        user.set_password(data["password"])
        user.save()
        enquiry = (
            Enquiry.objects.filter(email__iexact=data["email"]).first()
            or Enquiry.objects.filter(mobile=data["mobile"]).first()
        )
        return StudentProfile.objects.create(
            user=user,
            full_name=data["full_name"],
            mobile=data["mobile"],
            state=data["state"],
            city=data["city"],
            course_interest=data.get("course_interest", "").strip(),
            enquiry=enquiry,
        )


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate(self, attrs):
        email = attrs["email"].strip().lower()
        user = authenticate(self.context.get("request"), username=email, password=attrs["password"])
        profile = getattr(user, "student_profile", None) if user else None
        if profile is None:
            raise serializers.ValidationError({"detail": "Email or password is incorrect."}, code="invalid")
        if profile.status == StudentProfile.Status.PENDING:
            raise serializers.ValidationError(
                {"detail": "Your account is waiting for admission verification. You can log in once the admissions team activates it."},
                code="pending",
            )
        if not profile.is_active_student:
            raise serializers.ValidationError(
                {"detail": "This student account is not active. Please contact the admissions team."},
                code="inactive",
            )
        attrs["user"] = user
        return attrs


class PasswordResetSerializer(serializers.Serializer):
    email = serializers.EmailField()


class SetPasswordMixin:
    def check_new_password(self, password, user):
        try:
            validate_password(password, user)
        except Exception as error:
            raise serializers.ValidationError({"password": list(getattr(error, "messages", [str(error)]))})


class PasswordResetConfirmSerializer(SetPasswordMixin, serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    password = serializers.CharField(write_only=True, trim_whitespace=False, max_length=128)

    def validate(self, attrs):
        invalid = serializers.ValidationError({"detail": "This password link is invalid or has expired. Request a new one."})
        try:
            user = User.objects.get(pk=force_str(urlsafe_base64_decode(attrs["uid"])))
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            raise invalid
        if not hasattr(user, "student_profile") or not default_token_generator.check_token(user, attrs["token"]):
            raise invalid
        self.check_new_password(attrs["password"], user)
        attrs["user"] = user
        return attrs


class ChangePasswordSerializer(SetPasswordMixin, serializers.Serializer):
    current_password = serializers.CharField(write_only=True, trim_whitespace=False)
    new_password = serializers.CharField(write_only=True, trim_whitespace=False, max_length=128)

    def validate(self, attrs):
        user = self.context["request"].user
        if not user.check_password(attrs["current_password"]):
            raise serializers.ValidationError({"current_password": ["The current password is incorrect."]})
        if attrs["current_password"] == attrs["new_password"]:
            raise serializers.ValidationError({"new_password": ["Choose a password different from the current one."]})
        try:
            validate_password(attrs["new_password"], user)
        except Exception as error:
            raise serializers.ValidationError({"new_password": list(getattr(error, "messages", [str(error)]))})
        return attrs


class StudentProfileSerializer(ProfileFieldsMixin, serializers.ModelSerializer):
    email = serializers.EmailField(source="user.email", read_only=True)

    class Meta:
        model = StudentProfile
        fields = [
            "full_name",
            "email",
            "student_id",
            "mobile",
            "state",
            "city",
            "address",
            "date_of_birth",
            "course_interest",
            "status",
            "verified_at",
            "created_at",
        ]
        read_only_fields = ["full_name", "email", "student_id", "course_interest", "status", "verified_at", "created_at"]


class AdminStudentSerializer(ProfileFieldsMixin, serializers.ModelSerializer):
    email = serializers.EmailField(source="user.email")
    last_login = serializers.DateTimeField(source="user.last_login", read_only=True)
    has_password = serializers.SerializerMethodField()

    class Meta:
        model = StudentProfile
        fields = [
            "id",
            "full_name",
            "email",
            "student_id",
            "mobile",
            "state",
            "city",
            "address",
            "date_of_birth",
            "course_interest",
            "status",
            "verified_at",
            "created_at",
            "last_login",
            "has_password",
        ]
        read_only_fields = ["id", "student_id", "verified_at", "created_at", "last_login", "has_password"]

    def get_has_password(self, obj):
        return obj.user.has_usable_password()

    def validate_email(self, value):
        value = value.strip().lower()
        if email_taken(value, exclude_user=self.instance.user if self.instance else None):
            raise serializers.ValidationError("Another account already uses this email.")
        return value

    @transaction.atomic
    def create(self, data):
        user_data = data.pop("user")
        email = user_data["email"]
        user = User(username=email, email=email, first_name=data["full_name"][:150])
        user.set_unusable_password()
        user.save()
        data.pop("status", None)
        profile = StudentProfile.objects.create(user=user, **data)
        profile.activate(by=self.context["request"].user)
        profile.save()
        return profile

    @transaction.atomic
    def update(self, profile, data):
        user_data = data.pop("user", None)
        if user_data and user_data.get("email"):
            profile.user.username = profile.user.email = user_data["email"]
        if "full_name" in data:
            profile.user.first_name = data["full_name"][:150]
        profile.user.save()
        status = data.pop("status", None)
        for field, value in data.items():
            setattr(profile, field, value)
        if status == StudentProfile.Status.ACTIVE:
            profile.activate(by=self.context["request"].user)
        elif status:
            profile.status = status
        profile.save()
        return profile
