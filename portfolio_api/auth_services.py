
import secrets
from datetime import timedelta
from datetime import datetime
from django.conf import settings
from django.core.cache import cache
from django.core.mail import send_mail
from django.utils import timezone


OTP_LENGTH = 6
OTP_EXPIRY_MINUTES = 5
OTP_MAX_ATTEMPTS = 5


def _otp_cache_key(user_id):
    return f"portfolio_admin_otp_{user_id}"


def issue_admin_otp(user):
    """Create and email a short-lived login OTP."""
    otp = f"{secrets.randbelow(10 ** OTP_LENGTH):0{OTP_LENGTH}d}"

    cache.set(
        _otp_cache_key(user.pk),
        {
            "otp": otp,
            "expires_at": (timezone.now() + timedelta(
                minutes=OTP_EXPIRY_MINUTES
            )).isoformat(),
            "attempts": 0,
        },
        timeout=OTP_EXPIRY_MINUTES * 60,
    )

    send_mail(
        subject="Your Portfolio Admin Login OTP",
        message=(
            f"Your login verification code is {otp}.\n\n"
            f"It expires in {OTP_EXPIRY_MINUTES} minutes. "
            "Do not share this code with anyone."
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=False,
    )


def verify_admin_otp(user, submitted_otp):
    """Verify the OTP and allow up to five attempts."""
    key = _otp_cache_key(user.pk)
    record = cache.get(key)

    if not record:
        return False

    if record["attempts"] >= OTP_MAX_ATTEMPTS:
        cache.delete(key)
        return False

    record["attempts"] += 1
    cache.set(
        key,
        record,
        timeout=max(
            1,
            int(
                (
                    datetime.fromisoformat(record["expires_at"])
                    - timezone.now()
                ).total_seconds()
            ),
        ),
    )

    if not secrets.compare_digest(
        record["otp"],
        str(submitted_otp).strip(),
    ):
        if record["attempts"] >= OTP_MAX_ATTEMPTS:
            cache.delete(key)
        return False

    cache.delete(key)
    return True
