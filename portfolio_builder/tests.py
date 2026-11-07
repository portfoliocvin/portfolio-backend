
from django.test import TestCase

from .models import PortfolioTemplate
from .views import _available_portfolio_templates


class AvailablePortfolioTemplatesTests(TestCase):

    def test_builtin_templates_are_available_without_seed_rows(self):
        templates = _available_portfolio_templates()
        keys = {item["key"] for item in templates}

        expected_keys = {
            "minimal",
            "dark_developer",
            "creative",
            "professional",
            "modern_profile",
            "career_timeline",
        }

        self.assertTrue(
            expected_keys.issubset(keys),
            f"Missing built-in templates: {expected_keys - keys}",
        )

    def test_inactive_builtin_template_is_not_returned(self):
        PortfolioTemplate.objects.update_or_create(
            key="minimal",
            defaults={
                "name": "Minimal",
                "is_active": False,
                "is_system": True,
            },
        )

        templates = _available_portfolio_templates()
        keys = {item["key"] for item in templates}

        self.assertNotIn("minimal", keys)

    def test_active_custom_template_is_returned(self):
        PortfolioTemplate.objects.update_or_create(
            key="custom_clean",
            defaults={
                "name": "Custom Clean",
                "is_active": True,
                "is_system": False,
            },
        )

        templates = _available_portfolio_templates()

        custom = next(
            (
                item
                for item in templates
                if item["key"] == "custom_clean"
            ),
            None,
        )

        self.assertIsNotNone(custom)
        self.assertEqual(custom["name"], "Custom Clean")


class CustomerUsernameAvailabilityTests(TestCase):
    def test_available_username_returns_available(self):
        response = self.client.get(
            "/api/builder/customer/username-availability/?username=NewCustomer_1"
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["available"])

    def test_existing_username_is_reported_case_insensitively(self):
        from django.contrib.auth import get_user_model

        User = get_user_model()
        User.objects.create_user(username="Owntag", password="test-password-123")

        response = self.client.get(
            "/api/builder/customer/username-availability/?username=owntag"
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["available"])

    def test_invalid_username_is_rejected(self):
        response = self.client.get(
            "/api/builder/customer/username-availability/?username=ab"
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["available"])


from datetime import timedelta
import json
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone
from .models import CustomerInvitation


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class CustomerInvitationPasswordTests(TestCase):
    def setUp(self):
        cache.clear()
        self.invitation = CustomerInvitation.objects.create(
            email="newcustomer@example.com",
            expires_at=timezone.now() + timedelta(hours=24),
        )

    def test_invitation_password_is_saved_and_customer_can_login(self):
        from .customer_auth import issue_customer_otp
        from django.core.cache import cache
        import secrets

        # Exercise the real invitation OTP service while using local test email.
        issue_customer_otp(self.invitation)
        otp = mail.outbox[-1].body.split("verification code is ", 1)[1].split(".", 1)[0]
        password = "Strong-Portfolio-Password-482!"
        response = self.client.post(
            "/api/builder/customer/verify-otp/",
            data=json.dumps({
                "token": str(self.invitation.token),
                "otp": otp,
                "username": "newcustomer",
                "password": password,
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        customer = get_user_model().objects.get(username="newcustomer")
        self.assertTrue(customer.check_password(password))
        self.assertTrue(customer.has_usable_password())

    def test_invitation_requires_a_password(self):
        response = self.client.post(
            "/api/builder/customer/verify-otp/",
            data=json.dumps({
                "token": str(self.invitation.token),
                "otp": "123456",
                "username": "newcustomer",
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class CustomerRecoveryTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="recoverycustomer",
            email="recovery@example.com",
            password="Old-Portfolio-Password-482!",
        )

    def test_recovery_can_reset_customer_password(self):
        request = self.client.post(
            "/api/builder/customer/recovery/request-otp/",
            data=json.dumps({
                "email": self.user.email,
                "purpose": "password",
            }),
            content_type="application/json",
        )
        self.assertEqual(request.status_code, 200)
        otp = mail.outbox[-1].body.split("verification code is ", 1)[1].split(".", 1)[0]
        new_password = "New-Portfolio-Password-593!"
        response = self.client.post(
            "/api/builder/customer/recovery/verify-otp/",
            data=json.dumps({
                "email": self.user.email,
                "purpose": "password",
                "otp": otp,
                "newPassword": new_password,
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(new_password))

    def test_recovery_can_reveal_username_after_email_otp(self):
        self.client.post(
            "/api/builder/customer/recovery/request-otp/",
            data=json.dumps({
                "email": self.user.email,
                "purpose": "username",
            }),
            content_type="application/json",
        )
        otp = mail.outbox[-1].body.split("verification code is ", 1)[1].split(".", 1)[0]
        response = self.client.post(
            "/api/builder/customer/recovery/verify-otp/",
            data=json.dumps({
                "email": self.user.email,
                "purpose": "username",
                "otp": otp,
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["username"], "recoverycustomer")
