import secrets
import hashlib
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings
from django.core.cache import cache
from .models import EmailVerificationToken


def send_verification_email(request, user, ttl_minutes=30):
    raw_token, token_obj = EmailVerificationToken.generate_for_user(user, ttl_minutes=ttl_minutes)
    host = request.get_host()
    scheme = 'https' if request.is_secure() else 'http'
    verify_url = f"{scheme}://{host}/verify-email/?token={raw_token}"
    subject = 'Verify your account'
    message = f"Please verify your account by clicking the following link (valid for {ttl_minutes} minutes):\n\n{verify_url}\n\nIf you did not sign up, ignore this message."
    send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [user.email])
    return token_obj


def can_resend_verification(user, limit=3, period_seconds=3600):
    key = f"resend_verif:{user.pk}"
    data = cache.get(key, 0)
    if data >= limit:
        return False
    # increment
    cache.incr(key, delta=1) if cache.get(key) is not None else cache.set(key, 1, timeout=period_seconds)
    return True

*** End Patch