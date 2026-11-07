
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class CustomerInvitation(models.Model):
    email = models.EmailField(unique=True)
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="portfolio_invitations_sent",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)

    def is_valid(self):
        return self.accepted_at is None and timezone.now() < self.expires_at

    def __str__(self):
        return self.email


class PortfolioSite(models.Model):
    TEMPLATE_CHOICES = [
        ("minimal", "Minimal"),
        ("dark_developer", "Dark Developer"),
        ("creative", "Creative"),
        ("professional", "Professional"),
        ("modern_profile", "Modern Profile"),
        ("career_timeline", "Career Timeline"),
    ]

    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("in_review", "Awaiting Owner Review"),
        ("changes_requested", "Changes Requested"),
        ("published", "Published"),
    ]

    owner = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="customer_portfolio",
    )
    title = models.CharField(max_length=200, default="My Portfolio")
    slug = models.SlugField(max_length=100, unique=True)
    selected_template = models.CharField(
        max_length=50,
        choices=TEMPLATE_CHOICES,
        default="minimal",
    )
    published_template = models.CharField(
        max_length=50,
        choices=TEMPLATE_CHOICES,
        default="minimal",
    )
    status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        default="draft",
    )

    # Public pages will read this approved snapshot, not editable draft data.
    published_content = models.JSONField(default=dict, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.title} ({self.owner})"


class PortfolioProfile(models.Model):
    site = models.OneToOneField(
        PortfolioSite,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    full_name = models.CharField(max_length=200, blank=True)
    headline = models.CharField(max_length=250, blank=True)
    about = models.TextField(blank=True)
    email = models.EmailField(blank=True)
    mobile_number = models.CharField(max_length=30, blank=True)
    location = models.CharField(max_length=200, blank=True)
    profile_image = models.ImageField(
        upload_to="portfolio_builder/profiles/",
        blank=True,
        null=True,
    )
    resume = models.FileField(
        upload_to="portfolio_builder/resumes/",
        blank=True,
        null=True,
    )
    social_links = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.full_name or self.site.title


class PortfolioProject(models.Model):
    site = models.ForeignKey(
        PortfolioSite,
        on_delete=models.CASCADE,
        related_name="projects",
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    technologies = models.JSONField(default=list, blank=True)
    project_url = models.URLField(blank=True)
    github_url = models.URLField(blank=True)
    image = models.ImageField(
        upload_to="portfolio_builder/projects/",
        blank=True,
        null=True,
    )
    display_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["display_order", "-created_at"]

    def __str__(self):
        return self.title


class PortfolioSkill(models.Model):
    site = models.ForeignKey(
        PortfolioSite,
        on_delete=models.CASCADE,
        related_name="skills",
    )
    name = models.CharField(max_length=100)
    category = models.CharField(max_length=100, blank=True)
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["display_order", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["site", "name"],
                name="unique_skill_per_portfolio",
            )
        ]

    def __str__(self):
        return self.name


class PortfolioCertification(models.Model):
    site = models.ForeignKey(
        PortfolioSite,
        on_delete=models.CASCADE,
        related_name="certifications",
    )
    name = models.CharField(max_length=200)
    issuer = models.CharField(max_length=200, blank=True)
    issue_date = models.DateField(null=True, blank=True)
    credential_id = models.CharField(max_length=200, blank=True)
    certificate_url = models.URLField(blank=True)
    certificate_file = models.FileField(
    upload_to="portfolio_builder/certificates/",
    blank=True,
    null=True,
)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["-issue_date", "name"]

    def __str__(self):
        return self.name


import hashlib


class CustomerSession(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="portfolio_customer_sessions",
    )
    token_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)

    def is_valid(self):
        return (
            self.revoked_at is None
            and timezone.now() < self.expires_at
            and self.user.is_active
            and not self.user.is_superuser
        )

    @staticmethod
    def hash_token(token):
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def __str__(self):
        return f"Customer session for user {self.user_id}"


class PortfolioTemplate(models.Model):
    key = models.SlugField(max_length=50, unique=True)
    name = models.CharField(max_length=100)
    category = models.CharField(max_length=80, default="General")
    description = models.CharField(max_length=300, blank=True)
    preview_image_url = models.URLField(blank=True)
    is_active = models.BooleanField(default=True)
    is_system = models.BooleanField(default=False)
    display_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["display_order", "name"]

    def __str__(self):
        return self.name


class PortfolioReview(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("approved", "Approved"),
        ("changes_requested", "Changes requested"),
    ]

    site = models.ForeignKey(
        PortfolioSite,
        on_delete=models.CASCADE,
        related_name="reviews",
    )
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="portfolio_reviews_submitted",
    )
    template_key = models.CharField(max_length=50)
    content_snapshot = models.JSONField(default=dict)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="pending")
    review_notes = models.TextField(blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="portfolio_reviews_decided",
    )

    class Meta:
        ordering = ["-submitted_at"]

    def __str__(self):
        return f"Review #{self.pk} - {self.site.title} ({self.status})"


class CustomerResume(models.Model):
    """A customer's standalone resume; independent from portfolio profile files."""
    TEMPLATE_CHOICES = [
        ("classic", "Classic Professional"),
        ("modern", "Modern"),
        ("ats", "ATS Optimized"),
        ("compact", "Compact One-Page"),
        ("academic", "Academic CV"),
        ("technical", "Technical Specialist"),
        ("elegant", "Elegant Minimal"),
        ("bold", "Bold Contemporary"),
        ("timeline", "Professional Timeline Sidebar"),
        ("executive", "Executive"),
        ("creative", "Creative"),
    ]
    owner = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="customer_resume",
    )
    template = models.CharField(max_length=20, choices=TEMPLATE_CHOICES, default="classic")
    content = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Resume for {self.owner}"
