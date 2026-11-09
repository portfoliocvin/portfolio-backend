
from django.db import models


class Project(models.Model):
    title = models.CharField(max_length=200)
    description = models.TextField()
    technologies = models.JSONField(default=list, blank=True)
    project_url = models.URLField(blank=True)
    github_url = models.URLField(blank=True)
    image = models.ImageField(
        upload_to="projects/",
        blank=True,
        null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title


class SiteSettings(models.Model):
    site_title = models.CharField(
        max_length=200,
        default="Vajrabilash Degapogu | Portfolio",
    )
    profile_image = models.ImageField(
        upload_to="profile/",
        blank=True,
        null=True,
    )
    resume = models.FileField(
        upload_to="resume/",
        blank=True,
        null=True,
    )
    favicon = models.ImageField(
        upload_to="favicon/",
        blank=True,
        null=True,
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.site_title


class ChangeHistory(models.Model):
    ACTION_CHOICES = [
        ("CREATE", "Create"),
        ("UPDATE", "Update"),
        ("DELETE", "Delete"),
    ]

    entity_type = models.CharField(max_length=50)
    entity_id = models.PositiveIntegerField(
        null=True,
        blank=True,
    )
    action = models.CharField(
        max_length=10,
        choices=ACTION_CHOICES,
    )
    description = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.action} {self.entity_type} at {self.created_at}"


class Skill(models.Model):
    name = models.CharField(max_length=100, unique=True)
    category = models.CharField(max_length=100, blank=True)
    display_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["display_order", "name"]

    def __str__(self):
        return self.name


class Certification(models.Model):
    name = models.CharField(max_length=200)
    issuer = models.CharField(max_length=200, blank=True)
    issue_date = models.DateField(null=True, blank=True)
    credential_id = models.CharField(max_length=200, blank=True)
    certificate_url = models.URLField(blank=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-issue_date", "-created_at"]

    def __str__(self):
        return self.name


class ProfileDetails(models.Model):
    full_name = models.CharField(
        max_length=200,
        default="Vajrabilash Degapogu",
    )
    mobile_number = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.full_name


class JobListing(models.Model):
    CATEGORY_CHOICES = [
        ("private", "Private Jobs"),
        ("government", "Government Jobs"),
    ]

    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    job_name = models.CharField(max_length=200)
    role = models.CharField(max_length=200)
    company_name = models.CharField(max_length=200)
    application_start_date = models.DateField()
    application_end_date = models.DateField()
    application_url = models.URLField(max_length=1000)
    is_published = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["application_end_date", "-created_at"]

    def __str__(self):
        return f"{self.job_name} - {self.company_name}"
