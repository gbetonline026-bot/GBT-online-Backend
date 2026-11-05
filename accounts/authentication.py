from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework import exceptions
from rest_framework.authentication import TokenAuthentication


class PortalTokenAuthentication(TokenAuthentication):
    """DRF token auth where non-staff (portal) tokens expire after PORTAL_TOKEN_TTL_HOURS."""

    def authenticate_credentials(self, key):
        user, token = super().authenticate_credentials(key)
        if not user.is_staff:
            ttl = timedelta(hours=settings.PORTAL_TOKEN_TTL_HOURS)
            if token.created < timezone.now() - ttl:
                token.delete()
                raise exceptions.AuthenticationFailed("Your session has expired. Please log in again.")
        return user, token
