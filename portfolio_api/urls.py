
from django.urls import path

from .views import (
    health_check,
    public_config,
    csrf_token,
    admin_login,
    admin_verify_otp,
    admin_logout,
    public_portfolio_content,
    admin_skills,
    admin_skill_detail,
    admin_certifications,
    admin_certification_detail,
    admin_profile_details,
    admin_changes,
    admin_settings,
    admin_upload,
    admin_session,
    admin_projects,
    admin_project_detail,
    public_jobs,
    admin_jobs,
    admin_job_detail,
    admin_changes,
    admin_settings,
)

urlpatterns = [
    path("health/", health_check, name="health_check"),
    path("jobs/", public_jobs, name="public_jobs"),
    path("admin/jobs/", admin_jobs, name="admin_jobs"),
    path("admin/jobs/<int:job_id>/", admin_job_detail, name="admin_job_detail"),
    path("public", public_config, name="public_config"),
    path("admin/upload/<str:kind>", admin_upload, name="admin_upload"),
    path("csrf/", csrf_token, name="csrf_token"),
        path("public/content/", public_portfolio_content, name="public_portfolio_content"),

    path("admin/skills", admin_skills, name="admin_skills"),
    path("admin/skills/<int:skill_id>", admin_skill_detail, name="admin_skill_detail"),

    path("admin/certifications", admin_certifications, name="admin_certifications"),
    path(
        "admin/certifications/<int:certification_id>",
        admin_certification_detail,
        name="admin_certification_detail",
    ),

    path("admin/profile", admin_profile_details, name="admin_profile_details"),
    path("auth/login/", admin_login, name="admin_login"),
    path("auth/verify-otp/", admin_verify_otp, name="admin_verify_otp"),
    path("auth/logout/", admin_logout, name="admin_logout"),
    path("auth/session/", admin_session, name="admin_session"),

    path("admin/projects", admin_projects, name="admin_projects"),
    path(
        "admin/projects/<int:project_id>",
        admin_project_detail,
        name="admin_project_detail",
    ),
    path("admin/changes", admin_changes, name="admin_changes"),
    path("admin/settings", admin_settings, name="admin_settings"),
]
