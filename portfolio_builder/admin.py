
from django.contrib import admin
from .models import CustomerSession
from .models import (
    CustomerInvitation,
    PortfolioSite,
    PortfolioProfile,
    PortfolioProject,
    PortfolioSkill,
    PortfolioCertification,
)


@admin.register(CustomerInvitation)
class CustomerInvitationAdmin(admin.ModelAdmin):
    list_display = ("email", "invited_by", "created_at", "expires_at", "accepted_at")
    search_fields = ("email",)
    readonly_fields = ("token", "created_at")


@admin.register(PortfolioSite)
class PortfolioSiteAdmin(admin.ModelAdmin):
    list_display = ("title", "owner", "slug", "selected_template", "status")
    list_filter = ("status", "selected_template")
    search_fields = ("title", "slug", "owner__email", "owner__username")
    readonly_fields = ("created_at", "updated_at", "published_at")


admin.site.register(PortfolioProfile)
admin.site.register(PortfolioProject)
admin.site.register(PortfolioSkill)
admin.site.register(PortfolioCertification)
admin.site.register(CustomerSession)
