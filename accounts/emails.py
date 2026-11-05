from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode


def password_link(user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    return f"{settings.FRONTEND_URL}/student/reset-password?uid={uid}&token={token}"


def _send(subject, body, to):
    send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [to], fail_silently=False)


def send_password_reset(profile):
    _send(
        "Reset your GBET Online password",
        (
            f"Hello {profile.full_name},\n\n"
            "We received a request to reset the password for your GBET Online student account.\n"
            f"Open this link to choose a new password:\n{password_link(profile.user)}\n\n"
            "If you did not ask for this, you can ignore this email. The link stops working once it is used.\n\n"
            "GBET Online Admissions"
        ),
        profile.user.email,
    )


def send_set_password(profile):
    _send(
        "Your GBET Online student account",
        (
            f"Hello {profile.full_name},\n\n"
            "Your GBET Online student account has been created by the admissions team.\n"
            f"Student ID: {profile.student_id}\n"
            f"Login email: {profile.user.email}\n\n"
            f"Set your password here:\n{password_link(profile.user)}\n\n"
            "GBET Online Admissions"
        ),
        profile.user.email,
    )


def send_activated(profile):
    _send(
        "Your GBET Online account is active",
        (
            f"Hello {profile.full_name},\n\n"
            "Your admission has been verified and your student account is now active.\n"
            f"Student ID: {profile.student_id}\n\n"
            f"Log in at {settings.FRONTEND_URL}/student/login with your email and password.\n\n"
            "GBET Online Admissions"
        ),
        profile.user.email,
    )
