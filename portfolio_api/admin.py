
from django.contrib import admin
from .models import (
    Project,
    SiteSettings,
    ChangeHistory,
    Skill,
    Certification,
    ProfileDetails,
)


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("title", "created_at", "updated_at")
    search_fields = ("title", "description")


@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    list_display = ("site_title", "updated_at")


@admin.register(ChangeHistory)
class ChangeHistoryAdmin(admin.ModelAdmin):
    list_display = ("entity_type", "action", "created_at")
    list_filter = ("entity_type", "action")
    search_fields = ("description",)


@admin.register(Skill)
class SkillAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "display_order")
    list_editable = ("category", "display_order")
    search_fields = ("name", "category")
    ordering = ("display_order", "name")


@admin.register(Certification)
class CertificationAdmin(admin.ModelAdmin):
    list_display = ("name", "issuer", "issue_date")
    search_fields = ("name", "issuer", "credential_id")
    list_filter = ("issuer",)


@admin.register(ProfileDetails)
class ProfileDetailsAdmin(admin.ModelAdmin):
    list_display = ("full_name", "mobile_number", "email")
    search_fields = ("full_name", "email", "mobile_number")
