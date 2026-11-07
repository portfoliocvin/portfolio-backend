
import secrets
from datetime import timedelta, datetime

from django.conf import settings
from django.core.cache import cache
from django.core.mail import send_mail
from django.utils import timezone

from .models import CustomerInvitation


OTP_LENGTH = 6
OTP_EXPIRY_MINUTES = 5
OTP_MAX_ATTEMPTS = 5


def _customer_otp_key(invitation_id):
    return f"portfolio_customer_otp_{invitation_id}"


def issue_customer_otp(invitation):
    """Send an OTP to the email address on a valid invitation."""
    if not invitation.is_valid():
        raise ValueError("This invitation is expired or already used.")

    otp = f"{secrets.randbelow(10 ** OTP_LENGTH):0{OTP_LENGTH}d}"

    cache.set(
        _customer_otp_key(invitation.pk),
        {
            "otp": otp,
            "expires_at": (
                timezone.now()
                + timedelta(minutes=OTP_EXPIRY_MINUTES)
            ).isoformat(),
            "attempts": 0,
        },
        timeout=OTP_EXPIRY_MINUTES * 60,
    )

    try:
        send_mail(
            subject="Your Portfolio Builder verification code",
            message=(
                f"Your verification code is {otp}.\n\n"
                f"It expires in {OTP_EXPIRY_MINUTES} minutes. "
                "Do not share this code with anyone."
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[invitation.email],
            fail_silently=False,
        )
    except Exception:
        cache.delete(_customer_otp_key(invitation.pk))
        raise


def verify_customer_otp(invitation, submitted_otp):
    """Verify a customer OTP, allowing at most five attempts."""
    if not invitation.is_valid():
        cache.delete(_customer_otp_key(invitation.pk))
        return False

    key = _customer_otp_key(invitation.pk)
    record = cache.get(key)

    if not record:
        return False

    if record["attempts"] >= OTP_MAX_ATTEMPTS:
        cache.delete(key)
        return False

    record["attempts"] += 1

    remaining_seconds = int(
        (
            datetime.fromisoformat(record["expires_at"])
            - timezone.now()
        ).total_seconds()
    )

    if remaining_seconds <= 0:
        cache.delete(key)
        return False

    cache.set(
        key,
        record,
        timeout=max(1, remaining_seconds),
    )

    submitted = str(submitted_otp).strip()

    if not secrets.compare_digest(record["otp"], submitted):
        if record["attempts"] >= OTP_MAX_ATTEMPTS:
            cache.delete(key)
        return False

    cache.delete(key)
    return True
