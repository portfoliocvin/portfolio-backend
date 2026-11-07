
import json
import re
from datetime import timedelta
from django.views.decorators.csrf import ensure_csrf_cookie
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from django.core.cache import cache
from .models import CustomerInvitation
import secrets

from datetime import timedelta

from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .models import CustomerSession

import secrets

from django.contrib.auth import get_user_model, login
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.text import slugify

from .models import (
    CustomerInvitation,
    PortfolioSite,
    PortfolioProfile,
)
from .customer_auth import (
    issue_customer_otp,
    verify_customer_otp,
)



def owner_is_allowed(request):
    return (
        request.user.is_authenticated
        and request.user.is_active
        and request.user.is_superuser
    )


@login_required
@require_GET
def owner_invitations(request):
    if not owner_is_allowed(request):
        return JsonResponse({"error": "Forbidden."}, status=403)

    invitations = CustomerInvitation.objects.order_by("-created_at")

    # Include accounts created through both public signup and invitations.
    customer_sites = (
        PortfolioSite.objects
        .select_related("owner", "profile")
        .filter(owner__is_superuser=False)
        .order_by("-created_at")
    )
    customers = []
    for site in customer_sites:
        customer = site.owner
        invitation = CustomerInvitation.objects.filter(
            email__iexact=customer.email,
            accepted_at__isnull=False,
        ).order_by("-accepted_at").first()
        profile = getattr(site, "profile", None)
        customers.append({
            "id": site.id,
            "name": (
                profile.full_name.strip()
                if profile and profile.full_name
                else customer.get_full_name().strip() or customer.username
            ),
            "username": customer.username,
            "email": customer.email,
            "slug": site.slug,
            "portfolioUrl": f"/portfolio/{site.slug}",
            "status": site.status,
            "createdAt": site.created_at.isoformat(),
            "registrationMethod": "invitation" if invitation else "direct",
        })

    return JsonResponse({
        "customers": customers,
        "invitations": [
            {
                "id": invitation.id,
                "email": invitation.email,
                "createdAt": invitation.created_at.isoformat(),
                "expiresAt": invitation.expires_at.isoformat(),
                "acceptedAt": (
                    invitation.accepted_at.isoformat()
                    if invitation.accepted_at else None
                ),
                "valid": invitation.is_valid(),
            }
            for invitation in invitations
        ]
    })


@login_required
@require_POST
def owner_customer_update(request, site_id):
    """Allow the owner to edit a customer's account identity and display name."""
    if not owner_is_allowed(request):
        return JsonResponse({"error": "Forbidden."}, status=403)

    try:
        data = json.loads(request.body or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    from django.contrib.auth import get_user_model
    from django.core.validators import validate_email
    from django.core.exceptions import ValidationError
    from django.shortcuts import get_object_or_404
    from django.db import transaction

    site = get_object_or_404(PortfolioSite.objects.select_related("owner", "profile"), pk=site_id)
    customer = site.owner
    if customer.is_superuser:
        return JsonResponse({"error": "The administrator account cannot be edited here."}, status=400)

    full_name = str(data.get("name", "")).strip()
    email = str(data.get("email", "")).strip().lower()
    username = str(data.get("username", "")).strip()
    if not full_name or len(full_name) > 200:
        return JsonResponse({"error": "Enter a name of 1–200 characters."}, status=400)
    if not username or len(username) > 150:
        return JsonResponse({"error": "Enter a valid username (up to 150 characters)."}, status=400)
    try:
        validate_email(email)
    except ValidationError:
        return JsonResponse({"error": "Enter a valid email address."}, status=400)

    UserModel = get_user_model()
    if UserModel.objects.filter(username__iexact=username).exclude(pk=customer.pk).exists():
        return JsonResponse({"error": "That username is already in use."}, status=409)
    if UserModel.objects.filter(email__iexact=email).exclude(pk=customer.pk).exists():
        return JsonResponse({"error": "That email address is already in use."}, status=409)

    with transaction.atomic():
        customer.username = username
        customer.email = email
        customer.save(update_fields=["username", "email"])
        profile, _ = PortfolioProfile.objects.get_or_create(site=site)
        profile.full_name = full_name
        profile.email = email
        profile.save(update_fields=["full_name", "email", "updated_at"])

    return JsonResponse({"message": "Customer details updated."})


@login_required
@require_POST
def owner_customer_stop_live(request, site_id):
    """Take a published customer portfolio offline without deleting its content."""
    if not owner_is_allowed(request):
        return JsonResponse({"error": "Forbidden."}, status=403)

    from django.shortcuts import get_object_or_404
    site = get_object_or_404(PortfolioSite, pk=site_id)
    if site.owner.is_superuser:
        return JsonResponse({"error": "The administrator portfolio cannot be stopped here."}, status=400)
    if site.status != "published" or not site.published_at:
        return JsonResponse({"message": "This portfolio is already offline."})

    # The public endpoint requires published_at to be set. Preserve the approved
    # snapshot, but clear its live marker so the URL no longer serves it publicly.
    site.status = "draft"
    site.published_at = None
    site.save(update_fields=["status", "published_at", "updated_at"])
    return JsonResponse({"message": "Portfolio taken offline. Customer data and approved content were preserved."})


@login_required
@require_POST
def owner_customer_delete(request, site_id):
    """Permanently delete a customer account and its cascading portfolio records."""
    if not owner_is_allowed(request):
        return JsonResponse({"error": "Forbidden."}, status=403)

    from django.shortcuts import get_object_or_404
    site = get_object_or_404(PortfolioSite.objects.select_related("owner"), pk=site_id)
    customer = site.owner
    if customer.is_superuser:
        return JsonResponse({"error": "The administrator account cannot be deleted here."}, status=400)

    username = customer.username
    # PortfolioSite.owner is OneToOne with CASCADE. Deleting the user removes
    # the site, profile, projects, skills, certifications, sessions and reviews
    # according to their model foreign-key cascade rules.
    customer.delete()
    return JsonResponse({"message": f"Customer account @{username} and its portfolio records were deleted."})


@login_required
@require_POST
def owner_create_invitation(request):
    if not owner_is_allowed(request):
        return JsonResponse({"error": "Forbidden."}, status=403)

    try:
        data = json.loads(request.body or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    email = str(data.get("email", "")).strip().lower()

    from django.core.validators import validate_email
    from django.core.exceptions import ValidationError

    try:
        validate_email(email)
    except ValidationError:
        return JsonResponse({"error": "Enter a valid email address."}, status=400)

    User = settings.AUTH_USER_MODEL
    from django.contrib.auth import get_user_model
    UserModel = get_user_model()

    existing_user = UserModel.objects.filter(email__iexact=email).first()
    if existing_user:
        return JsonResponse({
            "error": "An account already exists with this email address."
        }, status=409)

    existing_invitation = CustomerInvitation.objects.filter(
        email__iexact=email,
        accepted_at__isnull=True,
    ).first()

    if existing_invitation and existing_invitation.is_valid():
        invitation = existing_invitation
    else:
        if existing_invitation:
            existing_invitation.delete()

        invitation = CustomerInvitation.objects.create(
            email=email,
            invited_by=request.user,
            expires_at=timezone.now() + timedelta(hours=48),
        )

    frontend_url = getattr(
        settings,
        "FRONTEND_URL",
        "http://localhost:3000",
    ).rstrip("/")

    invite_url = (
        f"{frontend_url}/customer/accept-invitation"
        f"?token={invitation.token}"
    )

    try:
        send_mail(
            subject="Your portfolio website invitation",
            message=(
                "You have been invited to create your portfolio website.\n\n"
                f"Open this link within 48 hours to accept your invitation:\n"
                f"{invite_url}\n\n"
                "If you were not expecting this invitation, you can ignore "
                "this email."
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
            fail_silently=False,
        )
    except Exception:
        return JsonResponse({
            "error": (
                "The invitation email could not be sent. "
                "Check your local email configuration and try again."
            )
        }, status=503)

    return JsonResponse({
        "message": "Invitation email sent successfully.",
        "email": email,
    }, status=201)


@require_GET
def customer_username_availability(request):
    """Public, read-only username check used while accepting an invitation."""
    username = str(request.GET.get("username", "")).strip()

    if not username:
        return JsonResponse(
            {"available": False, "message": "Enter a username."},
            status=400,
        )

    if len(username) < 4 or len(username) > 150 or not re.fullmatch(r"[A-Za-z0-9_-]+", username):
        return JsonResponse({
            "available": False,
            "message": "Use 4–150 characters: letters, numbers, hyphens or underscores.",
        })

    User = get_user_model()
    taken = User.objects.filter(username__iexact=username).exists()
    return JsonResponse({
        "available": not taken,
        "message": "Username is available." if not taken else "That username is already taken.",
    })


@require_POST
def customer_request_otp(request):
    try:
        data = json.loads(request.body or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    token = str(data.get("token", "")).strip()

    try:
        invitation = CustomerInvitation.objects.get(token=token)
    except (CustomerInvitation.DoesNotExist, ValueError):
        return JsonResponse(
            {"error": "Invalid or expired invitation."},
            status=400,
        )

    if not invitation.is_valid():
        return JsonResponse(
            {"error": "Invalid or expired invitation."},
            status=400,
        )

    User = get_user_model()
    if User.objects.filter(email__iexact=invitation.email).exists():
        return JsonResponse(
            {"error": "An account already exists for this invitation."},
            status=409,
        )

    try:
        issue_customer_otp(invitation)
    except Exception:
        return JsonResponse(
            {"error": "Unable to send the verification email."},
            status=503,
        )

    return JsonResponse({
        "message": "Verification code sent to the invited email address."
    })



def _public_registration_cache_key(email):
    import hashlib
    digest = hashlib.sha256(email.lower().encode("utf-8")).hexdigest()
    return f"webresume_public_registration_{digest}"


@require_POST
def customer_public_registration_request_otp(request):
    """Start the public self-service registration flow; invitation flow is unchanged."""
    try:
        data = json.loads(request.body or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    email = str(data.get("email", "")).strip().lower()
    from django.core.validators import validate_email
    try:
        validate_email(email)
    except ValidationError:
        return JsonResponse({"error": "Enter a valid email address."}, status=400)

    User = get_user_model()
    if User.objects.filter(email__iexact=email).exists():
        return JsonResponse({"error": "An account already exists with this email. Please sign in instead."}, status=409)

    key = _public_registration_cache_key(email)
    existing = cache.get(key)
    if existing and existing.get("sent_at") and (timezone.now().timestamp() - existing["sent_at"] < 60):
        return JsonResponse({"error": "Please wait one minute before requesting another code."}, status=429)

    otp = f"{secrets.randbelow(1000000):06d}"
    record = {"otp": otp, "attempts": 0, "sent_at": timezone.now().timestamp()}
    cache.set(key, record, timeout=600)
    try:
        send_mail(
            subject="Verify your WebResume account",
            message=(
                f"Your WebResume verification code is {otp}.\n\n"
                "This code expires in 10 minutes. If you did not request an account, "
                "you can ignore this email."
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
            fail_silently=False,
        )
    except Exception:
        cache.delete(key)
        return JsonResponse({"error": "Unable to send the verification email. Please try again later."}, status=503)

    return JsonResponse({"message": "Verification code sent. Check your email."}, status=200)


@require_POST
def customer_public_registration_verify_otp(request):
    """Verify email and create a customer account, portfolio and customer session."""
    try:
        data = json.loads(request.body or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    email = str(data.get("email", "")).strip().lower()
    full_name = str(data.get("fullName", "")).strip()
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    otp = str(data.get("otp", "")).strip()

    from django.core.validators import validate_email
    try:
        validate_email(email)
    except ValidationError:
        return JsonResponse({"error": "Enter a valid email address."}, status=400)
    if not full_name or len(full_name) > 200:
        return JsonResponse({"error": "Enter your name (up to 200 characters)."}, status=400)
    if len(username) < 4 or len(username) > 150 or not re.fullmatch(r"[A-Za-z0-9_-]+", username):
        return JsonResponse({"error": "Use 4–150 characters for username: letters, numbers, hyphens or underscores."}, status=400)
    if not otp or len(otp) != 6 or not otp.isdigit():
        return JsonResponse({"error": "Enter the six-digit verification code."}, status=400)
    try:
        validate_password(password)
    except ValidationError as exc:
        return JsonResponse({"error": " ".join(exc.messages)}, status=400)

    key = _public_registration_cache_key(email)
    record = cache.get(key)
    if not record:
        return JsonResponse({"error": "Your verification code has expired. Request a new one."}, status=400)
    if record.get("attempts", 0) >= 5:
        cache.delete(key)
        return JsonResponse({"error": "Too many incorrect attempts. Request a new verification code."}, status=429)
    if not secrets.compare_digest(str(record.get("otp", "")), otp):
        record["attempts"] = record.get("attempts", 0) + 1
        cache.set(key, record, timeout=600)
        return JsonResponse({"error": "Incorrect verification code."}, status=400)

    User = get_user_model()
    try:
        with transaction.atomic():
            if User.objects.filter(email__iexact=email).exists():
                return JsonResponse({"error": "An account already exists with this email. Please sign in."}, status=409)
            if User.objects.filter(username__iexact=username).exists():
                return JsonResponse({"error": "That username is already taken. Choose another."}, status=409)

            customer = User.objects.create_user(
                username=username, email=email, password=password,
                first_name=full_name[:150],
            )
            base_slug = slugify(username) or "portfolio"
            slug = f"{base_slug}-{secrets.token_hex(3)}"
            while PortfolioSite.objects.filter(slug=slug).exists():
                slug = f"{base_slug}-{secrets.token_hex(3)}"
            site = PortfolioSite.objects.create(
                owner=customer, title=f"{full_name}'s Portfolio",
                slug=slug, status="draft",
            )
            PortfolioProfile.objects.create(
                site=site, full_name=full_name, email=email,
            )
            session_token = secrets.token_urlsafe(32)
            CustomerSession.objects.create(
                user=customer,
                token_hash=CustomerSession.hash_token(session_token),
                expires_at=timezone.now() + timedelta(days=7),
            )
    except Exception:
        # Keep the OTP available for a retry if a transient database error occurs.
        raise

    cache.delete(key)
    response = JsonResponse({
        "message": "Your WebResume account is ready.",
        "customer": {"email": customer.email, "portfolioSlug": site.slug, "status": site.status},
    }, status=201)
    response.set_cookie(
        "customer_session", session_token, max_age=7 * 24 * 60 * 60,
        httponly=True, secure=not settings.DEBUG, samesite="Lax", path="/",
    )
    return response


@ensure_csrf_cookie
@require_GET
def customer_csrf(request):
    return JsonResponse({"message": "CSRF cookie set."})
@require_POST
def customer_verify_otp(request):
    try:
        data = json.loads(request.body or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    token = str(data.get("token", "")).strip()
    otp = str(data.get("otp", "")).strip()
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))

    if not token or not otp or not username or not password:
        return JsonResponse(
            {"error": "Invitation token, OTP, username and password are required."},
            status=400,
        )

    try:
        validate_password(password)
    except ValidationError as exc:
        return JsonResponse(
            {"error": " ".join(exc.messages)},
            status=400,
        )

    if len(username) < 4 or len(username) > 150 or not re.fullmatch(r"[A-Za-z0-9_-]+", username):
        return JsonResponse(
            {"error": "Use 4–150 characters: letters, numbers, hyphens or underscores."},
            status=400,
        )

    try:
        invitation = CustomerInvitation.objects.get(token=token)
    except (CustomerInvitation.DoesNotExist, ValueError):
        return JsonResponse(
            {"error": "Invalid or expired invitation."},
            status=400,
        )

    if not invitation.is_valid():
        return JsonResponse(
            {"error": "Invalid or expired invitation."},
            status=400,
        )

    if not verify_customer_otp(invitation, otp):
        return JsonResponse(
            {"error": "Invalid or expired verification code."},
            status=400,
        )

    User = get_user_model()

    with transaction.atomic():
        # Lock the invitation to prevent two simultaneous account creations.
        invitation = CustomerInvitation.objects.select_for_update().get(
            pk=invitation.pk
        )

        if not invitation.is_valid():
            return JsonResponse(
                {"error": "This invitation has already been used."},
                status=409,
            )

        if User.objects.filter(email__iexact=invitation.email).exists():
            return JsonResponse(
                {"error": "An account already exists for this email."},
                status=409,
            )

        if User.objects.filter(username__iexact=username).exists():
            return JsonResponse(
                {"error": "That username is already taken. Please choose another."},
                status=409,
            )

        # The invitation form collects the customer's chosen password.
        # Store it using Django's configured password hasher so customer
        # password login works immediately after email verification.
        customer = User.objects.create_user(
            username=username,
            email=invitation.email,
            password=password,
        )

        title = f"{invitation.email.split('@')[0]}'s Portfolio"
        base_slug = slugify(invitation.email.split("@")[0]) or "portfolio"
        slug = f"{base_slug}-{secrets.token_hex(3)}"

        site = PortfolioSite.objects.create(
            owner=customer,
            title=title,
            slug=slug,
            status="draft",
        )

        PortfolioProfile.objects.create(
            site=site,
            email=invitation.email,
            full_name=invitation.email.split("@")[0],
        )

        invitation.accepted_at = timezone.now()
        invitation.save(update_fields=["accepted_at"])

        # Create a separate session for the customer.
        session_token = secrets.token_urlsafe(32)

        CustomerSession.objects.create(
            user=customer,
            token_hash=CustomerSession.hash_token(session_token),
            expires_at=timezone.now() + timedelta(days=7),
        )

    response = JsonResponse({
        "message": "Account created successfully.",
        "customer": {
            "email": customer.email,
            "portfolioSlug": site.slug,
            "status": site.status,
        },
    }, status=201)

    response.set_cookie(
        "customer_session",
        session_token,
        max_age=7 * 24 * 60 * 60,
        httponly=True,
        secure=not settings.DEBUG,
        samesite="Lax",
        path="/",
    )

    return response



def _customer_login_otp_key(user_id):
    return f"portfolio_customer_login_otp_{user_id}"


@require_POST
def customer_login_request_otp(request):
    try:
        data = json.loads(request.body or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    identifier = str(data.get("identifier", "")).strip()
    password = str(data.get("password", ""))

    if not identifier or not password:
        return JsonResponse(
            {"error": "Username/email and password are required."},
            status=400,
        )

    User = get_user_model()

    if "@" in identifier:
        user = User.objects.filter(email__iexact=identifier).first()
    else:
        user = User.objects.filter(username__iexact=identifier).first()

    if (
        not user
        or not user.is_active
        or user.is_superuser
        or not user.check_password(password)
    ):
        return JsonResponse({"error": "Invalid login details."}, status=401)

    if not user.email:
        return JsonResponse(
            {"error": "Your account has no verified email address. Contact the owner."},
            status=400,
        )

    otp = f"{secrets.randbelow(1000000):06d}"
    key = _customer_login_otp_key(user.pk)

    cache.set(
        key,
        {"otp": otp, "attempts": 0},
        timeout=300,
    )

    try:
        send_mail(
            subject="Your Portfolio Builder login code",
            message=(
                f"Your login verification code is {otp}. "
                "It expires in 5 minutes. Do not share it."
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )
    except Exception:
        cache.delete(key)
        return JsonResponse(
            {"error": "Unable to send the verification email."},
            status=503,
        )

    return JsonResponse({
        "message": "A verification code has been sent to your registered email."
    })


@require_POST
def customer_login_verify_otp(request):
    try:
        data = json.loads(request.body or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    identifier = str(data.get("identifier", "")).strip()
    password = str(data.get("password", ""))
    otp = str(data.get("otp", "")).strip()

    User = get_user_model()

    if "@" in identifier:
        user = User.objects.filter(email__iexact=identifier).first()
    else:
        user = User.objects.filter(username__iexact=identifier).first()

    if (
        not user
        or not user.is_active
        or user.is_superuser
        or not user.check_password(password)
    ):
        return JsonResponse({"error": "Invalid login details."}, status=401)

    key = _customer_login_otp_key(user.pk)
    record = cache.get(key)

    if not record or record.get("attempts", 0) >= 5:
        cache.delete(key)
        return JsonResponse(
            {"error": "Verification code expired. Request a new code."},
            status=400,
        )

    record["attempts"] += 1

    if not secrets.compare_digest(str(record.get("otp", "")), otp):
        cache.set(key, record, timeout=300)
        return JsonResponse(
            {"error": "Incorrect verification code."},
            status=400,
        )

    cache.delete(key)

    session_token = secrets.token_urlsafe(32)

    CustomerSession.objects.create(
        user=user,
        token_hash=CustomerSession.hash_token(session_token),
        expires_at=timezone.now() + timedelta(days=7),
    )

    response = JsonResponse({"message": "Login successful."})

    response.set_cookie(
        "customer_session",
        session_token,
        max_age=7 * 24 * 60 * 60,
        httponly=True,
        secure=not settings.DEBUG,
        samesite="Lax",
        path="/",
    )

    return response

def get_customer_session(request):
    token = request.COOKIES.get("customer_session")

    if not token:
        return None

    token_hash = CustomerSession.hash_token(token)

    try:
        session = CustomerSession.objects.select_related(
            "user",
            "user__customer_portfolio",
        ).get(token_hash=token_hash)
    except CustomerSession.DoesNotExist:
        return None

    if not session.is_valid():
        return None

    return session



def _available_portfolio_templates():
    """Return built-in templates plus active owner-managed templates.

    Built-in templates remain available even when the database
    has not been seeded. An inactive database row can disable
    a built-in template. Active custom templates are included.
    """
    from .models import PortfolioSite, PortfolioTemplate

    configured = {
        item.key: item
        for item in PortfolioTemplate.objects.all()
    }

    templates = []

    # Include the six built-in templates.
    for key, label in PortfolioSite.TEMPLATE_CHOICES:
        row = configured.get(key)

        # An inactive database record disables this built-in template.
        if row is not None and not row.is_active:
            continue

        templates.append({
            "key": key,
            "name": row.name if row else label,
            "category": row.category if row else "General",
            "description": row.description if row else "",
            "previewImageUrl": row.preview_image_url if row else "",
        })

    # Include active custom templates.
    builtin_keys = [
        key for key, label in PortfolioSite.TEMPLATE_CHOICES
    ]

    custom_templates = (
        PortfolioTemplate.objects
        .filter(is_active=True)
        .exclude(key__in=builtin_keys)
        .order_by("display_order", "name")
    )

    for row in custom_templates:
        templates.append({
            "key": row.key,
            "name": row.name,
            "category": row.category,
            "description": row.description,
            "previewImageUrl": row.preview_image_url,
        })

    return templates



def _customer_recovery_otp_key(user_id, purpose):
    return f"portfolio_customer_recovery_{purpose}_{user_id}"


@require_POST
def customer_recovery_request_otp(request):
    """Issue a short-lived OTP for username recovery or password reset."""
    try:
        data = json.loads(request.body or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    email = str(data.get("email", "")).strip().lower()
    purpose = str(data.get("purpose", "")).strip().lower()
    if purpose not in {"username", "password"} or not email:
        return JsonResponse(
            {"error": "A registered email address and recovery type are required."},
            status=400,
        )

    User = get_user_model()
    user = User.objects.filter(
        email__iexact=email, is_active=True, is_superuser=False
    ).first()

    # Keep the response identical whether or not the email exists.
    generic_message = (
        "If an active customer account matches that email, "
        "a verification code has been sent."
    )
    if not user:
        return JsonResponse({"message": generic_message})

    otp = f"{secrets.randbelow(1000000):06d}"
    cache.set(
        _customer_recovery_otp_key(user.pk, purpose),
        {"otp": otp, "attempts": 0},
        timeout=300,
    )
    try:
        send_mail(
            subject=(
                "Your Portfolio Builder username recovery code"
                if purpose == "username"
                else "Your Portfolio Builder password reset code"
            ),
            message=(
                f"Your verification code is {otp}. "
                "It expires in 5 minutes. Do not share it."
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )
    except Exception:
        cache.delete(_customer_recovery_otp_key(user.pk, purpose))
        return JsonResponse(
            {"error": "Unable to send the verification email. Please try again later."},
            status=503,
        )

    return JsonResponse({"message": generic_message})


@require_POST
def customer_recovery_verify_otp(request):
    """Verify recovery OTP; reveal username or securely reset password."""
    try:
        data = json.loads(request.body or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    email = str(data.get("email", "")).strip().lower()
    purpose = str(data.get("purpose", "")).strip().lower()
    otp = str(data.get("otp", "")).strip()
    new_password = str(data.get("newPassword", ""))

    if purpose not in {"username", "password"} or not email or not otp:
        return JsonResponse(
            {"error": "Email, recovery type and verification code are required."},
            status=400,
        )

    User = get_user_model()
    user = User.objects.filter(
        email__iexact=email, is_active=True, is_superuser=False
    ).first()
    if not user:
        return JsonResponse(
            {"error": "Invalid or expired verification code."},
            status=400,
        )

    key = _customer_recovery_otp_key(user.pk, purpose)
    record = cache.get(key)
    if not record or record.get("attempts", 0) >= 5:
        cache.delete(key)
        return JsonResponse(
            {"error": "Verification code expired. Request a new code."},
            status=400,
        )

    record["attempts"] = record.get("attempts", 0) + 1
    if not secrets.compare_digest(str(record.get("otp", "")), otp):
        if record["attempts"] >= 5:
            cache.delete(key)
        else:
            cache.set(key, record, timeout=300)
        return JsonResponse(
            {"error": "Incorrect verification code."},
            status=400,
        )

    if purpose == "password":
        if not new_password:
            return JsonResponse(
                {"error": "Enter a new password after verifying your email code."},
                status=400,
            )
        try:
            validate_password(new_password, user=user)
        except ValidationError as exc:
            return JsonResponse({"error": " ".join(exc.messages)}, status=400)
        user.set_password(new_password)
        user.save(update_fields=["password"])

    cache.delete(key)
    if purpose == "username":
        return JsonResponse({
            "message": "Email verified. Your username is shown below.",
            "username": user.username,
        })
    return JsonResponse({"message": "Your password has been reset successfully."})


def customer_me(request):
    session = get_customer_session(request)

    if not session:
        return JsonResponse(
            {"error": "Customer authentication required."},
            status=401,
        )

    site = session.user.customer_portfolio

    try:
        profile = site.profile

        profile_image_url = ""
        if profile.profile_image:
            profile_image_url = request.build_absolute_uri(
                profile.profile_image.url
            )

        resume_url = ""
        if profile.resume:
            resume_url = request.build_absolute_uri(profile.resume.url)

        profile_data = {
            "fullName": profile.full_name,
            "headline": profile.headline,
            "about": profile.about,
            "email": profile.email,
            "mobileNumber": profile.mobile_number,
            "location": profile.location,
            "socialLinks": profile.social_links,
            "profileImageUrl": profile_image_url,
            "resumeUrl": resume_url,
        }
    except site.profile.RelatedObjectDoesNotExist:
        profile_data = {}

    from .models import PortfolioReview
    latest_review = site.reviews.order_by("-submitted_at").first()
    templates = _available_portfolio_templates()
    return JsonResponse({
        "customer": {
            "email": session.user.email,
            "username": session.user.username,
        },
        "portfolio": {
            "id": site.id,
            "title": site.title,
            "slug": site.slug,
            "selectedTemplate": site.selected_template,
            "publishedTemplate": site.published_template,
            "status": site.status,
            "publishedAt": site.published_at.isoformat() if site.published_at else None,
            "review": ({
                "id": latest_review.id,
                "status": latest_review.status,
                "submittedAt": latest_review.submitted_at.isoformat(),
                "reviewedAt": latest_review.reviewed_at.isoformat() if latest_review.reviewed_at else None,
                "notes": latest_review.review_notes,
            } if latest_review else None),
            "templates": templates,
            "profile": profile_data,
        },
    })


@require_POST
def customer_logout(request):
    token = request.COOKIES.get("customer_session")

    if token:
        token_hash = CustomerSession.hash_token(token)

        CustomerSession.objects.filter(
            token_hash=token_hash,
            revoked_at__isnull=True,
        ).update(revoked_at=timezone.now())

    response = JsonResponse({"message": "Customer signed out."})
    response.delete_cookie(
        "customer_session",
        path="/",
        samesite="Lax",
    )
    return response

@require_POST
def customer_portfolio(request):
    session = get_customer_session(request)

    if not session:
        return JsonResponse(
            {"error": "Customer authentication required."},
            status=401,
        )

    site = session.user.customer_portfolio

    try:
        data = json.loads(request.body or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    allowed_templates = {
        item["key"] for item in _available_portfolio_templates()
    }

    title = data.get("title", site.title)
    selected_template = data.get(
        "selectedTemplate", site.selected_template
    )

    if not isinstance(title, str) or not title.strip():
        return JsonResponse(
            {"error": "Portfolio title is required."},
            status=400,
        )

    if len(title.strip()) > 200:
        return JsonResponse(
            {"error": "Portfolio title must be 200 characters or fewer."},
            status=400,
        )

    if selected_template not in allowed_templates:
        return JsonResponse(
            {"error": "Invalid portfolio template."},
            status=400,
        )

    # Keep public content unchanged until the owner approves changes.
    site.title = title.strip()
    site.selected_template = selected_template

    if site.status == "published":
        site.status = "draft"

    site.save(
        update_fields=[
            "title",
            "selected_template",
            "status",
            "updated_at",
        ]
    )

    return JsonResponse({
        "message": "Portfolio settings saved.",
        "portfolio": {
            "title": site.title,
            "selectedTemplate": site.selected_template,
            "status": site.status,
        },
    })


@require_POST
def customer_profile_save(request):
    session = get_customer_session(request)

    if not session:
        return JsonResponse(
            {"error": "Customer authentication required."},
            status=401,
        )

    # Continue supporting existing JSON saves while also accepting file uploads.
    is_multipart = (
        request.content_type
        and request.content_type.startswith("multipart/form-data")
    )

    if is_multipart:
        data = request.POST
    else:
        try:
            data = json.loads(request.body or "{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JsonResponse({"error": "Invalid JSON."}, status=400)

    site = session.user.customer_portfolio

    try:
        profile = site.profile
    except PortfolioProfile.DoesNotExist:
        profile = PortfolioProfile(site=site, email=session.user.email)

    fields = {
        "fullName": ("full_name", 200),
        "headline": ("headline", 250),
        "about": ("about", 10000),
        "email": ("email", 254),
        "mobileNumber": ("mobile_number", 30),
        "location": ("location", 200),
    }

    for request_field, (model_field, max_length) in fields.items():
        if request_field not in data:
            continue

        value = data[request_field]

        if not isinstance(value, str):
            return JsonResponse(
                {"error": f"{request_field} must be text."},
                status=400,
            )

        if len(value) > max_length:
            return JsonResponse(
                {"error": f"{request_field} is too long."},
                status=400,
            )

        setattr(profile, model_field, value.strip())

    if "socialLinks" in data:
        social_links = data["socialLinks"]

        # FormData transmits object values as strings.
        if isinstance(social_links, str):
            try:
                social_links = json.loads(social_links or "{}")
            except (json.JSONDecodeError, TypeError):
                return JsonResponse(
                    {"error": "Social links must be valid JSON."},
                    status=400,
                )

        if not isinstance(social_links, dict):
            return JsonResponse(
                {"error": "Social links must be an object."},
                status=400,
            )

        if len(social_links) > 20 or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in social_links.items()
        ):
            return JsonResponse(
                {"error": "Invalid social links."},
                status=400,
            )

        profile.social_links = social_links

    profile_image = request.FILES.get("profileImage")
    resume_file = request.FILES.get("resumeFile")

    # Validate profile photo extension, size, and image readability.
    if profile_image:
        import os
        from PIL import Image

        allowed_image_extensions = {".jpg", ".jpeg", ".png", ".webp"}
        image_extension = os.path.splitext(profile_image.name)[1].lower()

        if image_extension not in allowed_image_extensions:
            return JsonResponse(
                {"error": "Profile photo must be JPG, JPEG, PNG, or WEBP."},
                status=400,
            )

        if profile_image.size > 5 * 1024 * 1024:
            return JsonResponse(
                {"error": "Profile photo must be 5 MB or smaller."},
                status=400,
            )

        try:
            image = Image.open(profile_image)
            image.verify()
            if image.format not in {"JPEG", "PNG", "WEBP"}:
                raise ValueError("Unsupported image format.")
            profile_image.seek(0)
        except Exception:
            return JsonResponse(
                {"error": "The selected profile photo is not a valid image."},
                status=400,
            )

    # Resume uploads are restricted to PDF files.
    if resume_file:
        import os

        resume_extension = os.path.splitext(resume_file.name)[1].lower()
        if resume_extension != ".pdf":
            return JsonResponse(
                {"error": "Resume must be a PDF file."},
                status=400,
            )

        if resume_file.size > 10 * 1024 * 1024:
            return JsonResponse(
                {"error": "Resume must be 10 MB or smaller."},
                status=400,
            )

        if not resume_file.read(5).startswith(b"%PDF-"):
            return JsonResponse(
                {"error": "The selected resume does not appear to be a valid PDF."},
                status=400,
            )
        resume_file.seek(0)

    # Remember old storage names so replaced files can be cleaned up after save.
    old_image_name = profile.profile_image.name if profile.profile_image else ""
    old_resume_name = profile.resume.name if profile.resume else ""

    if profile_image:
        profile.profile_image = profile_image
    if resume_file:
        profile.resume = resume_file

    profile.save()

    # Delete only replaced files, never the file currently referenced by the model.
    if (
        old_image_name
        and profile.profile_image
        and old_image_name != profile.profile_image.name
    ):
        profile.profile_image.storage.delete(old_image_name)

    if (
        old_resume_name
        and profile.resume
        and old_resume_name != profile.resume.name
    ):
        profile.resume.storage.delete(old_resume_name)

    if site.status == "published":
        site.status = "draft"
        site.save(update_fields=["status", "updated_at"])

    profile_image_url = ""
    if profile.profile_image:
        profile_image_url = request.build_absolute_uri(
            profile.profile_image.url
        )

    resume_url = ""
    if profile.resume:
        resume_url = request.build_absolute_uri(profile.resume.url)

    return JsonResponse({
        "message": "Profile saved successfully.",
        "profile": {
            "fullName": profile.full_name,
            "headline": profile.headline,
            "about": profile.about,
            "email": profile.email,
            "mobileNumber": profile.mobile_number,
            "location": profile.location,
            "socialLinks": profile.social_links,
            "profileImageUrl": profile_image_url,
            "resumeUrl": resume_url,
        },
        "status": site.status,
    })


@require_GET
def customer_projects(request):
    session = get_customer_session(request)

    if not session:
        return JsonResponse(
            {"error": "Customer authentication required."},
            status=401,
        )

    site = session.user.customer_portfolio

    projects = [
        {
            "id": project.id,
            "title": project.title,
            "description": project.description,
            "technologies": project.technologies,
            "projectUrl": project.project_url,
            "githubUrl": project.github_url,
            "displayOrder": project.display_order,
        }
        for project in site.projects.all()
    ]

    return JsonResponse({"projects": projects})


@require_POST
def customer_project_save(request):
    session = get_customer_session(request)

    if not session:
        return JsonResponse(
            {"error": "Customer authentication required."},
            status=401,
        )

    try:
        data = json.loads(request.body or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    title = data.get("title", "")
    description = data.get("description", "")
    technologies = data.get("technologies", [])
    project_url = data.get("projectUrl", "")
    github_url = data.get("githubUrl", "")
    project_id = data.get("id")

    if not isinstance(title, str) or not title.strip():
        return JsonResponse(
            {"error": "Project title is required."},
            status=400,
        )

    if len(title) > 200:
        return JsonResponse(
            {"error": "Project title is too long."},
            status=400,
        )

    if not isinstance(description, str) or len(description) > 10000:
        return JsonResponse(
            {"error": "Project description is invalid or too long."},
            status=400,
        )

    if not isinstance(technologies, list) or not all(
        isinstance(item, str) and len(item) <= 100
        for item in technologies
    ):
        return JsonResponse(
            {"error": "Technologies must be a list of text values."},
            status=400,
        )

    if len(technologies) > 50:
        return JsonResponse(
            {"error": "Too many technologies."},
            status=400,
        )

    if not isinstance(project_url, str) or len(project_url) > 200:
        return JsonResponse({"error": "Invalid project URL."}, status=400)

    if not isinstance(github_url, str) or len(github_url) > 200:
        return JsonResponse({"error": "Invalid GitHub URL."}, status=400)

    from .models import PortfolioProject
    from django.core.exceptions import ValidationError

    site = session.user.customer_portfolio

    if project_id:
        try:
            project = site.projects.get(pk=project_id)
        except (PortfolioProject.DoesNotExist, ValueError, TypeError):
            return JsonResponse({"error": "Project not found."}, status=404)
    else:
        project = PortfolioProject(site=site)

    project.title = title.strip()
    project.description = description.strip()
    project.technologies = technologies
    project.project_url = project_url.strip()
    project.github_url = github_url.strip()

    try:
        project.full_clean()
        project.save()
    except ValidationError as exc:
        details = exc.message_dict if hasattr(exc, "message_dict") else {
            "project": exc.messages
        }
        readable = "; ".join(
            f"{field.replace('_', ' ').capitalize()}: {', '.join(messages)}"
            for field, messages in details.items()
        )
        return JsonResponse(
            {"error": readable or "Please check the project details and try again.",
             "details": details},
            status=400,
        )

    if site.status == "published":
        site.status = "draft"
        site.save(update_fields=["status", "updated_at"])

    return JsonResponse({
        "message": "Project saved successfully.",
        "project": {
            "id": project.id,
            "title": project.title,
            "description": project.description,
            "technologies": project.technologies,
            "projectUrl": project.project_url,
            "githubUrl": project.github_url,
            "displayOrder": project.display_order,
        },
        "status": site.status,
    }, status=201 if not project_id else 200)


@require_POST
def customer_project_delete(request):
    session = get_customer_session(request)

    if not session:
        return JsonResponse(
            {"error": "Customer authentication required."},
            status=401,
        )

    try:
        data = json.loads(request.body or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    project_id = data.get("id")

    if not project_id:
        return JsonResponse(
            {"error": "Project ID is required."},
            status=400,
        )

    site = session.user.customer_portfolio

    from .models import PortfolioProject

    try:
        project = site.projects.get(pk=project_id)
    except (PortfolioProject.DoesNotExist, ValueError, TypeError):
        return JsonResponse(
            {"error": "Project not found."},
            status=404,
        )

    project.delete()

    if site.status == "published":
        site.status = "draft"
        site.save(update_fields=["status", "updated_at"])

    return JsonResponse({
        "message": "Project deleted successfully.",
        "projectId": project_id,
        "status": site.status,
    })


@require_GET
def customer_skills(request):
    session = get_customer_session(request)

    if not session:
        return JsonResponse(
            {"error": "Customer authentication required."},
            status=401,
        )

    site = session.user.customer_portfolio

    skills = [
        {
            "id": skill.id,
            "name": skill.name,
            "category": skill.category,
            "displayOrder": skill.display_order,
        }
        for skill in site.skills.all()
    ]

    return JsonResponse({"skills": skills})


@require_POST
def customer_skill_save(request):
    session = get_customer_session(request)

    if not session:
        return JsonResponse(
            {"error": "Customer authentication required."},
            status=401,
        )

    try:
        data = json.loads(request.body or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    name = data.get("name", "")
    category = data.get("category", "")
    skill_id = data.get("id")

    if not isinstance(name, str) or not name.strip():
        return JsonResponse(
            {"error": "Skill name is required."},
            status=400,
        )

    if len(name.strip()) > 100:
        return JsonResponse(
            {"error": "Skill name must be 100 characters or fewer."},
            status=400,
        )

    if not isinstance(category, str) or len(category.strip()) > 100:
        return JsonResponse(
            {"error": "Category must be 100 characters or fewer."},
            status=400,
        )

    site = session.user.customer_portfolio

    from .models import PortfolioSkill
    from django.db import IntegrityError, transaction

    try:
        with transaction.atomic():
            if skill_id:
                try:
                    skill = site.skills.get(pk=skill_id)
                except (PortfolioSkill.DoesNotExist, ValueError, TypeError):
                    return JsonResponse(
                        {"error": "Skill not found."},
                        status=404,
                    )
            else:
                skill = PortfolioSkill(site=site)

            skill.name = name.strip()
            skill.category = category.strip()
            skill.full_clean()
            skill.save()

    except IntegrityError:
        return JsonResponse(
            {"error": "This skill already exists in your portfolio."},
            status=409,
        )
    except Exception as exc:
        from django.core.exceptions import ValidationError

        if isinstance(exc, ValidationError):
            return JsonResponse(
                {"error": exc.message_dict},
                status=400,
            )
        raise

    if site.status == "published":
        site.status = "draft"
        site.save(update_fields=["status", "updated_at"])

    return JsonResponse(
        {
            "message": "Skill saved successfully.",
            "skill": {
                "id": skill.id,
                "name": skill.name,
                "category": skill.category,
                "displayOrder": skill.display_order,
            },
            "status": site.status,
        },
        status=201 if not skill_id else 200,
    )


@require_POST
def customer_skill_delete(request):
    session = get_customer_session(request)

    if not session:
        return JsonResponse(
            {"error": "Customer authentication required."},
            status=401,
        )

    try:
        data = json.loads(request.body or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    skill_id = data.get("id")

    if not skill_id:
        return JsonResponse(
            {"error": "Skill ID is required."},
            status=400,
        )

    site = session.user.customer_portfolio

    from .models import PortfolioSkill

    try:
        skill = site.skills.get(pk=skill_id)
    except (PortfolioSkill.DoesNotExist, ValueError, TypeError):
        return JsonResponse({"error": "Skill not found."}, status=404)

    skill.delete()

    if site.status == "published":
        site.status = "draft"
        site.save(update_fields=["status", "updated_at"])

    return JsonResponse({
        "message": "Skill deleted successfully.",
        "skillId": skill_id,
        "status": site.status,
    })



@require_GET
def customer_certifications(request):
    session = get_customer_session(request)

    if not session:
        return JsonResponse(
            {"error": "Customer authentication required."},
            status=401,
        )

    site = session.user.customer_portfolio

    certifications = []
    for item in site.certifications.all():
        file_url = ""
        if item.certificate_file:
            file_url = request.build_absolute_uri(
                item.certificate_file.url
            )

        certifications.append({
            "id": item.id,
            "name": item.name,
            "issuer": item.issuer,
            "issueDate": (
                item.issue_date.isoformat()
                if item.issue_date else ""
            ),
            "credentialId": item.credential_id,
            "certificateUrl": item.certificate_url,
            "certificateFileUrl": file_url,
            "description": item.description,
        })

    return JsonResponse({"certifications": certifications})


@require_POST
def customer_certification_save(request):
    session = get_customer_session(request)

    if not session:
        return JsonResponse(
            {"error": "Customer authentication required."},
            status=401,
        )

    # Support both existing JSON requests and file-upload FormData.
    if request.content_type and request.content_type.startswith(
        "multipart/form-data"
    ):
        data = request.POST
    else:
        try:
            data = json.loads(request.body or "{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JsonResponse({"error": "Invalid JSON."}, status=400)

    name = data.get("name", "")
    issuer = data.get("issuer", "")
    issue_date = data.get("issueDate", "")
    credential_id = data.get("credentialId", "")
    certificate_url = data.get("certificateUrl", "")
    description = data.get("description", "")
    certification_id = data.get("id")
    uploaded_file = request.FILES.get("certificateFile")

    text_fields = {
        "name": (name, 200, True),
        "issuer": (issuer, 200, False),
        "credentialId": (credential_id, 200, False),
        "description": (description, 10000, False),
    }

    for field, (value, max_length, required) in text_fields.items():
        if not isinstance(value, str):
            return JsonResponse(
                {"error": f"{field} must be text."},
                status=400,
            )

        if required and not value.strip():
            return JsonResponse(
                {"error": "Certification name is required."},
                status=400,
            )

        if len(value) > max_length:
            return JsonResponse(
                {"error": f"{field} is too long."},
                status=400,
            )

    if not isinstance(issue_date, str) or not isinstance(
        certificate_url, str
    ):
        return JsonResponse(
            {"error": "Issue date and certificate URL must be text."},
            status=400,
        )

    if len(certificate_url) > 200:
        return JsonResponse(
            {"error": "Certificate URL is too long."},
            status=400,
        )

    # Accept PDF and common certificate image formats only.
    if uploaded_file:
        allowed_extensions = {".pdf", ".png", ".jpg", ".jpeg"}
        import os

        extension = os.path.splitext(uploaded_file.name)[1].lower()

        if extension not in allowed_extensions:
            return JsonResponse(
                {"error": "Upload a PDF, PNG, JPG, or JPEG file."},
                status=400,
            )

        if uploaded_file.size > 5 * 1024 * 1024:
            return JsonResponse(
                {"error": "Certificate file must be 5 MB or smaller."},
                status=400,
            )

    from datetime import date
    from django.core.exceptions import ValidationError
    from django.db import IntegrityError, transaction
    from .models import PortfolioCertification

    parsed_date = None
    if issue_date:
        try:
            parsed_date = date.fromisoformat(issue_date)
        except ValueError:
            return JsonResponse(
                {
                    "error": (
                        "Enter a valid issue date in YYYY-MM-DD format."
                    )
                },
                status=400,
            )

    site = session.user.customer_portfolio

    try:
        with transaction.atomic():
            if certification_id:
                try:
                    item = site.certifications.get(pk=certification_id)
                except (
                    PortfolioCertification.DoesNotExist,
                    ValueError,
                    TypeError,
                ):
                    return JsonResponse(
                        {"error": "Certification not found."},
                        status=404,
                    )
            else:
                item = PortfolioCertification(site=site)

            item.name = name.strip()
            item.issuer = issuer.strip()
            item.issue_date = parsed_date
            item.credential_id = credential_id.strip()
            item.certificate_url = certificate_url.strip()
            item.description = description.strip()

            # If no new file is uploaded, keep the existing file.
            if uploaded_file:
                item.certificate_file = uploaded_file

            item.full_clean()
            item.save()

    except ValidationError as exc:
        return JsonResponse({"error": exc.message_dict}, status=400)
    except IntegrityError:
        return JsonResponse(
            {"error": "Unable to save this certification."},
            status=400,
        )

    if site.status == "published":
        site.status = "draft"
        site.save(update_fields=["status", "updated_at"])

    file_url = ""
    if item.certificate_file:
        file_url = request.build_absolute_uri(
            item.certificate_file.url
        )

    return JsonResponse(
        {
            "message": "Certification saved successfully.",
            "certification": {
                "id": item.id,
                "name": item.name,
                "issuer": item.issuer,
                "issueDate": (
                    item.issue_date.isoformat()
                    if item.issue_date else ""
                ),
                "credentialId": item.credential_id,
                "certificateUrl": item.certificate_url,
                "certificateFileUrl": file_url,
                "description": item.description,
            },
            "status": site.status,
        },
        status=200 if certification_id else 201,
    )



@require_POST
def customer_certification_delete(request):
    session = get_customer_session(request)

    if not session:
        return JsonResponse(
            {"error": "Customer authentication required."},
            status=401,
        )

    try:
        data = json.loads(request.body or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    certification_id = data.get("id")
    if not certification_id:
        return JsonResponse(
            {"error": "Certification ID is required."},
            status=400,
        )

    site = session.user.customer_portfolio

    from .models import PortfolioCertification

    try:
        item = site.certifications.get(pk=certification_id)
    except (PortfolioCertification.DoesNotExist, ValueError, TypeError):
        return JsonResponse(
            {"error": "Certification not found."},
            status=404,
        )

    item.delete()

    if site.status == "published":
        site.status = "draft"
        site.save(update_fields=["status", "updated_at"])

    return JsonResponse({
        "message": "Certification deleted successfully.",
        "certificationId": certification_id,
        "status": site.status,
    })


@require_GET
def public_customer_portfolio(request, slug):
    """Return only the approved snapshot for a published customer portfolio."""
    from django.shortcuts import get_object_or_404

    site = get_object_or_404(
        PortfolioSite.objects.only(
            "id", "title", "slug", "status", "published_template",
            "published_content", "published_at"
        ),
        slug=slug,
        published_at__isnull=False,
    )

    published_title = (site.published_content or {}).get("title") or site.title
    return JsonResponse({
        "portfolio": {
            "title": published_title,
            "slug": site.slug,
            "template": site.published_template,
            "publishedAt": site.published_at.isoformat() if site.published_at else None,
            "content": site.published_content or {},
        }
    })


# ---------------------------------------------------------------------------
# Customer portfolio review and expandable template library
# ---------------------------------------------------------------------------
def _portfolio_file_url(request, field_file):
    try:
        return request.build_absolute_uri(field_file.url) if field_file else ""
    except (ValueError, OSError):
        return ""


def build_portfolio_snapshot(request, site):
    """Build a JSON-safe immutable version for owner review/public publishing."""
    from .models import (
        PortfolioProject, PortfolioSkill, PortfolioCertification,
    )

    try:
        profile = site.profile
        profile_data = {
            "fullName": profile.full_name,
            "headline": profile.headline,
            "about": profile.about,
            "email": profile.email,
            "mobileNumber": profile.mobile_number,
            "location": profile.location,
            "socialLinks": profile.social_links or {},
            "profileImageUrl": _portfolio_file_url(request, profile.profile_image),
        }
        resume_url = _portfolio_file_url(request, profile.resume)
    except PortfolioProfile.DoesNotExist:
        profile_data = {}
        resume_url = ""

    projects = []
    for item in site.projects.all():
        projects.append({
            "id": item.pk,
            "title": item.title,
            "description": item.description,
            "technologies": item.technologies or [],
            "projectUrl": item.project_url,
            "githubUrl": item.github_url,
            "url": item.project_url,
            "imageUrl": _portfolio_file_url(request, item.image),
        })

    skills = [
        {"id": item.pk, "name": item.name, "category": item.category}
        for item in site.skills.all()
    ]

    certifications = []
    for item in site.certifications.all():
        certifications.append({
            "id": item.pk,
            "name": item.name,
            "issuer": item.issuer,
            "issueDate": item.issue_date.isoformat() if item.issue_date else "",
            "credentialId": item.credential_id,
            "certificateUrl": item.certificate_url,
            "url": item.certificate_url,
            "certificateFileUrl": _portfolio_file_url(request, item.certificate_file),
            "description": item.description,
        })

    return {
        "title": site.title,
        "profile": profile_data,
        "about": profile_data.get("about", ""),
        "resumeUrl": resume_url,
        "projects": projects,
        "skills": skills,
        "certifications": certifications,
    }


@require_POST
def customer_submit_for_approval(request):
    session = get_customer_session(request)
    if not session:
        return JsonResponse({"error": "Customer authentication required."}, status=401)

    from .models import PortfolioReview, PortfolioSite
    from django.db import transaction

    # Serialize submissions for this portfolio to prevent duplicate pending reviews.
    with transaction.atomic():
        site = PortfolioSite.objects.select_for_update().get(owner=session.user)
        if PortfolioReview.objects.filter(site=site, status="pending").exists():
            return JsonResponse({
                "error": "Your portfolio is already waiting for owner review.",
            }, status=409)

        available_templates = {
            item["key"] for item in _available_portfolio_templates()
        }
        if site.selected_template not in available_templates:
            return JsonResponse({"error": "Please select an available template before submitting."}, status=400)

        snapshot = build_portfolio_snapshot(request, site)
        review = PortfolioReview.objects.create(
            site=site,
            submitted_by=session.user,
            template_key=site.selected_template,
            content_snapshot=snapshot,
        )
        site.status = "in_review"
        site.save(update_fields=["status", "updated_at"])

    return JsonResponse({
        "message": "Your portfolio has been submitted for owner approval.",
        "review": {
            "id": review.id,
            "status": review.status,
            "submittedAt": review.submitted_at.isoformat(),
        },
        "portfolioStatus": site.status,
    }, status=201)


@login_required
@require_GET
def owner_portfolio_reviews(request):
    if not owner_is_allowed(request):
        return JsonResponse({"error": "Forbidden."}, status=403)
    from .models import PortfolioReview
    reviews = PortfolioReview.objects.select_related(
        "site", "site__owner", "submitted_by"
    ).order_by("-submitted_at")
    return JsonResponse({
        "reviews": [{
            "id": item.id,
            "status": item.status,
            "customerEmail": item.site.owner.email,
            "customerUsername": item.site.owner.username,
            "portfolioTitle": item.content_snapshot.get("title", item.site.title),
            "slug": item.site.slug,
            "template": item.template_key,
            "submittedAt": item.submitted_at.isoformat(),
            "reviewedAt": item.reviewed_at.isoformat() if item.reviewed_at else None,
            "reviewNotes": item.review_notes,
            "content": item.content_snapshot,
        } for item in reviews]
    })


@login_required
@require_POST
def owner_review_decision(request, review_id):
    if not owner_is_allowed(request):
        return JsonResponse({"error": "Forbidden."}, status=403)
    try:
        data = json.loads(request.body or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    decision = str(data.get("decision", "")).strip().lower()
    notes = str(data.get("notes", "")).strip()
    if decision not in {"approve", "request_changes"}:
        return JsonResponse({"error": "Choose approve or request_changes."}, status=400)
    if len(notes) > 3000:
        return JsonResponse({"error": "Review notes are too long."}, status=400)

    from .models import PortfolioReview
    from django.db import transaction
    try:
        with transaction.atomic():
            review = PortfolioReview.objects.select_for_update().select_related("site").get(pk=review_id)
            if review.status != "pending":
                return JsonResponse({"error": "This submission has already been reviewed."}, status=409)
            site = review.site
            review.reviewed_by = request.user
            review.reviewed_at = timezone.now()
            review.review_notes = notes
            if decision == "approve":
                review.status = "approved"
                site.published_content = review.content_snapshot
                site.published_template = review.template_key
                site.status = "published"
                site.published_at = timezone.now()
                site.save(update_fields=[
                    "published_content", "published_template", "status",
                    "published_at", "updated_at",
                ])
            else:
                review.status = "changes_requested"
                site.status = "changes_requested"
                site.save(update_fields=["status", "updated_at"])
            review.save(update_fields=[
                "status", "reviewed_by", "reviewed_at", "review_notes",
            ])
    except PortfolioReview.DoesNotExist:
        return JsonResponse({"error": "Submission not found."}, status=404)

    return JsonResponse({
        "message": "Portfolio published successfully." if decision == "approve" else "Changes requested successfully.",
        "reviewId": review.id,
        "status": review.status,
    })


@require_GET
def available_portfolio_templates(request):
    return JsonResponse({
    "templates": _available_portfolio_templates()
})


@login_required
@require_GET
def owner_portfolio_templates(request):
    if not owner_is_allowed(request):
        return JsonResponse({"error": "Forbidden."}, status=403)
    from .models import PortfolioTemplate
    templates = PortfolioTemplate.objects.all().order_by("display_order", "name")
    return JsonResponse({"templates": [{
        "id": item.id, "key": item.key, "name": item.name,
        "category": item.category, "description": item.description,
        "previewImageUrl": item.preview_image_url,
        "isActive": item.is_active, "isSystem": item.is_system,
        "displayOrder": item.display_order,
    } for item in templates]})


@login_required
@require_POST
def owner_save_portfolio_template(request):
    if not owner_is_allowed(request):
        return JsonResponse({"error": "Forbidden."}, status=403)
    try:
        data = json.loads(request.body or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    from django.utils.text import slugify
    from .models import PortfolioTemplate
    template_id = data.get("id")
    if template_id:
        try:
            template = PortfolioTemplate.objects.get(pk=template_id)
        except (PortfolioTemplate.DoesNotExist, ValueError, TypeError):
            return JsonResponse({"error": "Template not found."}, status=404)
        key = template.key
    else:
        key = slugify(str(data.get("key") or data.get("name") or ""))[:50]
        if not key:
            return JsonResponse({"error": "Template key/name is required."}, status=400)
        if PortfolioTemplate.objects.filter(key=key).exists():
            return JsonResponse({"error": "That template key already exists."}, status=409)
        template = PortfolioTemplate(key=key)

    name = str(data.get("name", template.name if template.pk else "")).strip()
    category = str(data.get("category", template.category if template.pk else "General")).strip()
    description = str(data.get("description", template.description if template.pk else "")).strip()
    preview = str(data.get("previewImageUrl", template.preview_image_url if template.pk else "")).strip()
    if not name or len(name) > 100 or len(category) > 80 or len(description) > 300:
        return JsonResponse({"error": "Check template name, category and description lengths."}, status=400)
    if preview and not preview.startswith(("https://", "http://")):
        return JsonResponse({"error": "Preview image must be an HTTP(S) URL."}, status=400)
    template.name, template.category, template.description = name, category or "General", description
    template.preview_image_url = preview
    template.is_active = bool(data.get("isActive", template.is_active if template.pk else True))
    template.display_order = max(0, int(data.get("displayOrder", template.display_order if template.pk else 0)))
    template.save()
    return JsonResponse({"message": "Template saved.", "template": {
        "id": template.id, "key": template.key, "name": template.name,
        "category": template.category, "description": template.description,
        "previewImageUrl": template.preview_image_url,
        "isActive": template.is_active, "isSystem": template.is_system,
        "displayOrder": template.display_order,
    }}, status=201 if not template_id else 200)


# ---------------- Standalone customer Resume Builder ----------------
@require_GET
def customer_resume_get(request):
    session = get_customer_session(request)
    if not session:
        return JsonResponse({"error": "Please log in to continue."}, status=401)
    from .models import CustomerResume
    resume = CustomerResume.objects.filter(owner=session.user).first()
    return JsonResponse({
        "resume": ({"template": resume.template, "content": resume.content,
                    "updatedAt": resume.updated_at.isoformat()} if resume else None),
        "templates": [
    {"key": "classic", "name": "Classic Professional", "description": "Clean, ATS-friendly layout"},
    {"key": "modern", "name": "Modern", "description": "Contemporary two-column layout"},
    {"key": "executive", "name": "Executive", "description": "Formal, structured presentation"},
    {"key": "creative", "name": "Creative", "description": "Accent-led personal style"},
    {"key": "ats", "name": "ATS Optimized", "description": "Simple, recruiter-friendly layout"},
    {"key": "compact", "name": "Compact One-Page", "description": "Space-saving and concise"},
    {"key": "academic", "name": "Academic CV", "description": "Education and research focused"},
    {"key": "technical", "name": "Technical Specialist", "description": "Skills and projects forward"},
    {"key": "elegant", "name": "Elegant Minimal", "description": "Refined typography and spacing"},
    {"key": "bold", "name": "Bold Contemporary", "description": "Strong header and modern accents"},
    {"key": "timeline", "name": "Professional Timeline Sidebar", "description": "Photo-style header and timeline layout"},
],
    })


@require_POST
def customer_resume_save(request):
    session = get_customer_session(request)
    if not session:
        return JsonResponse({"error": "Please log in to continue."}, status=401)
    try:
        data = json.loads(request.body or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON."}, status=400)
    template = str(data.get("template", "classic"))
    allowed = {
    "classic",
    "modern",
    "executive",
    "creative",
    "ats",
    "compact",
    "academic",
    "technical",
    "elegant",
    "bold",
    "timeline",
}
    content = data.get("content", {})
    if template not in allowed:
        return JsonResponse({"error": "Choose a valid resume template."}, status=400)
    if not isinstance(content, dict):
        return JsonResponse({"error": "Resume content must be an object."}, status=400)
    # Bound payload size and ensure the JSON can be safely stored.
    if len(json.dumps(content, ensure_ascii=False)) > 200000:
        return JsonResponse({"error": "Resume content is too large."}, status=413)
    from .models import CustomerResume
    resume, _ = CustomerResume.objects.update_or_create(
        owner=session.user,
        defaults={"template": template, "content": content},
    )
    return JsonResponse({"message": "Resume draft saved.", "updatedAt": resume.updated_at.isoformat()})
