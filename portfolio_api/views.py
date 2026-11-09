
import secrets
from django_ratelimit.decorators import ratelimit
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.core.cache import cache
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import ensure_csrf_cookie
from django.utils.decorators import method_decorator
import json
from django.http import JsonResponse
from .models import Project, SiteSettings
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.core.files.storage import default_storage
from django.conf import settings
from .models import (
    SiteSettings,
    ChangeHistory,
    Skill,
    Certification,
    ProfileDetails,
)
from django.core.serializers.json import DjangoJSONEncoder
from django.core.exceptions import ValidationError
from PIL import Image
from .models import Project

from .auth_services import issue_admin_otp, verify_admin_otp


User = get_user_model()


@require_GET
def health_check(request):
    return JsonResponse({
        "status": "success",
        "message": "Portfolio Django API is running",
    })


@require_GET
def public_config(request):
    return JsonResponse(get_public_config())


@require_GET
@ensure_csrf_cookie
def csrf_token(request):
    return JsonResponse({"detail": "CSRF cookie set"})

@ratelimit(key="ip", rate="5/m", method="POST", block=True)
@require_POST
def admin_login(request):
    import json

    try:
        data = json.loads(request.body or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    identifier = str(data.get("username_or_email", "")).strip()
    password = str(data.get("password", ""))

    if not identifier or not password:
        return JsonResponse(
            {"error": "Username/email and password are required."},
            status=400,
        )

    # Only one active superuser administrator is allowed to log in.
    user = User.objects.filter(
        is_superuser=True,
        is_active=True,
    ).filter(
        username__iexact=identifier
    ).first()

    if user is None and "@" in identifier:
        user = User.objects.filter(
            is_superuser=True,
            is_active=True,
            email__iexact=identifier,
        ).first()

    if user is None:
        return JsonResponse(
            {"error": "Invalid credentials."},
            status=401,
        )

    authenticated_user = authenticate(
        request,
        username=user.get_username(),
        password=password,
    )

    if authenticated_user is None or not authenticated_user.is_superuser:
        return JsonResponse(
            {"error": "Invalid credentials."},
            status=401,
        )

    if not authenticated_user.email:
        return JsonResponse(
            {"error": "Administrator email is not configured."},
            status=400,
        )

    # Replace any previous pending OTP for this administrator.
    try:
        issue_admin_otp(authenticated_user)
    except Exception:
        return JsonResponse(
            {"error": "Could not send verification email. Try again later."},
            status=503,
        )

    return JsonResponse({
        "detail": "Verification code sent to the registered administrator email.",
        "otp_required": True,
    })


@ratelimit(key="ip", rate="5/m", method="POST", block=True)
@require_POST
def admin_verify_otp(request):
    import json

    try:
        data = json.loads(request.body or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    identifier = str(data.get("username_or_email", "")).strip()
    password = str(data.get("password", ""))
    otp = str(data.get("otp", "")).strip()

    if not identifier or not password or not otp:
        return JsonResponse(
            {"error": "Username/email, password and OTP are required."},
            status=400,
        )

    user = User.objects.filter(
        is_superuser=True,
        is_active=True,
        username__iexact=identifier,
    ).first()

    if user is None and "@" in identifier:
        user = User.objects.filter(
            is_superuser=True,
            is_active=True,
            email__iexact=identifier,
        ).first()

    if user is None:
        return JsonResponse(
            {"error": "Invalid credentials or OTP."},
            status=401,
        )

    authenticated_user = authenticate(
        request,
        username=user.get_username(),
        password=password,
    )

    if authenticated_user is None:
        return JsonResponse(
            {"error": "Invalid credentials or OTP."},
            status=401,
        )

    if not verify_admin_otp(authenticated_user, otp):
        return JsonResponse(
            {"error": "Invalid or expired OTP."},
            status=400,
        )

    login(request, authenticated_user)

    return JsonResponse({
        "detail": "Login successful.",
        "username": authenticated_user.get_username(),
    })



@require_POST
def admin_logout(request):
    logout(request)
    return JsonResponse({"detail": "Logged out successfully."})


@require_GET
def admin_session(request):
    if not request.user.is_authenticated or not request.user.is_superuser:
        return JsonResponse({"authenticated": False}, status=401)

    return JsonResponse({
    "authenticated": True,
    "username": request.user.get_username(),
    "email": request.user.email,
})

def project_to_dict(project):
    return {
        "id": project.id,
        "title": project.title,
        "description": project.description,
        "technologies": project.technologies,
        "projectUrl": project.project_url,
        "githubUrl": project.github_url,
        "createdAt": project.created_at.isoformat(),
        "updatedAt": project.updated_at.isoformat(),
    }


@login_required
@require_http_methods(["GET", "POST"])
def admin_projects(request):
    if not request.user.is_superuser or not request.user.is_active:
        return JsonResponse({"error": "Forbidden"}, status=403)

    if request.method == "GET":
        projects = Project.objects.all()
        return JsonResponse({
            "projects": [project_to_dict(p) for p in projects]
        })

    try:
        data = json.loads(request.body or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    title = str(data.get("title", "")).strip()
    if not title:
        return JsonResponse({"error": "Project title is required"}, status=400)

    project = Project.objects.create(
        title=title,
        description=str(data.get("description", "")),
        technologies=data.get("technologies", []),
        project_url=data.get("projectUrl", ""),
        github_url=data.get("githubUrl", ""),
    )

    return JsonResponse({"project": project_to_dict(project)}, status=201)


@login_required
@require_http_methods(["PUT", "DELETE"])
def admin_project_detail(request, project_id):
    if not request.user.is_superuser or not request.user.is_active:
        return JsonResponse({"error": "Forbidden"}, status=403)

    try:
        project = Project.objects.get(pk=project_id)
    except Project.DoesNotExist:
        return JsonResponse({"error": "Project not found"}, status=404)

    if request.method == "DELETE":
        project.delete()
        return JsonResponse({"detail": "Project deleted"}, status=200)

    try:
        data = json.loads(request.body or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    project.title = str(data.get("title", project.title)).strip()
    project.description = str(data.get("description", project.description))
    project.technologies = data.get("technologies", project.technologies)
    project.project_url = data.get("projectUrl", project.project_url)
    project.github_url = data.get("githubUrl", project.github_url)

    if not project.title:
        return JsonResponse({"error": "Project title is required"}, status=400)

    project.save()
    return JsonResponse({"project": project_to_dict(project)})

def get_site_settings():
    return SiteSettings.objects.first()




def public_config(request):
    site = SiteSettings.objects.first()

    if site:
        config = {
            "siteTitle": site.site_title,
            "siteDescription": "",
            "faviconUrl": site.favicon.url if site.favicon else "",
            "profileImage": site.profile_image.url if site.profile_image else "",
            "resumeUrl": site.resume.url if site.resume else "",
        }
    else:
        config = {
            "siteTitle": "Vajrabilash Degapogu | Portfolio",
            "siteDescription": "",
            "faviconUrl": "",
            "profileImage": "",
            "resumeUrl": "",
        }

    projects = Project.objects.all().order_by("-created_at")

    config["projects"] = [
        {
            "id": project.id,
            "title": project.title,
            "type": getattr(project, "project_type", "") or "PROJECT",
            "description": project.description,
            "technologies": project.technologies or [],
            "projectUrl": project.project_url,
            "githubUrl": project.github_url,
        }
        for project in projects
    ]

    return JsonResponse(config)




@login_required
@require_GET
def admin_changes(request):
    if not request.user.is_superuser or not request.user.is_active:
        return JsonResponse({"error": "Forbidden"}, status=403)

    changes = ChangeHistory.objects.all()[:50]

    return JsonResponse({
        "changes": [
            {
                "id": item.id,
                "action": item.action,
                "detail": item.description,
                "createdAt": item.created_at.isoformat(),
            }
            for item in changes
        ]
    })


@login_required
@require_http_methods(["GET", "PUT"])
def admin_settings(request):
    if not request.user.is_superuser or not request.user.is_active:
        return JsonResponse({"error": "Forbidden"}, status=403)

    site = get_site_settings()

    if request.method == "GET":
        return JsonResponse({"config": get_public_config()})

    try:
        data = json.loads(request.body or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    if site is None:
        site = SiteSettings.objects.create()

    title = str(data.get("siteTitle", site.site_title)).strip()
    if not title:
        return JsonResponse({"error": "Site title is required"}, status=400)

    site.site_title = title
    site.save()

    ChangeHistory.objects.create(
        entity_type="SiteSettings",
        entity_id=site.pk,
        action="UPDATE",
        description="Updated website metadata",
    )

    return JsonResponse({"config": get_public_config()})

@login_required
@require_POST
def admin_upload(request, kind):
    if not request.user.is_superuser or not request.user.is_active:
        return JsonResponse({"error": "Forbidden"}, status=403)

    uploaded = request.FILES.get("file")
    if not uploaded:
        return JsonResponse({"error": "Choose a file to upload."}, status=400)

    if uploaded.size > 5 * 1024 * 1024:
        return JsonResponse({"error": "Maximum file size is 5 MB."}, status=400)

    site = get_site_settings()
    if site is None:
        site = SiteSettings.objects.create()

    if kind == "resume":
        if not uploaded.name.lower().endswith(".pdf"):
            return JsonResponse({"error": "Upload a PDF resume."}, status=400)

        if uploaded.content_type != "application/pdf":
            return JsonResponse({"error": "Invalid PDF content type."}, status=400)

        field = site.resume

    elif kind in ("profile", "favicon"):
        allowed_extensions = {
            "profile": {".jpg", ".jpeg", ".png", ".webp"},
            "favicon": {".jpg", ".jpeg", ".png", ".webp", ".ico"},
        }

        import os
        extension = os.path.splitext(uploaded.name)[1].lower()

        if extension not in allowed_extensions[kind]:
            return JsonResponse({"error": "Unsupported image file type."}, status=400)

        if extension == ".ico":
            if kind != "favicon":
                return JsonResponse({"error": "ICO is only allowed for favicons."}, status=400)
        else:
            try:
                image = Image.open(uploaded)
                image.verify()
            except Exception:
                return JsonResponse({"error": "Invalid image file."}, status=400)
            finally:
                uploaded.seek(0)

        field = site.profile_image if kind == "profile" else site.favicon

    else:
        return JsonResponse({"error": "Unknown upload type."}, status=400)

    field.save(uploaded.name, uploaded, save=False)

    if kind == "resume":
        site.resume = field
    elif kind == "profile":
        site.profile_image = field
    else:
        site.favicon = field

    site.save()

    ChangeHistory.objects.create(
        entity_type="SiteSettings",
        entity_id=site.pk,
        action="UPDATE",
        description=f"Updated {kind} upload",
    )

    return JsonResponse({"config": get_public_config()})


# ---------- Skills, Certifications and Profile API ----------

def is_portfolio_admin(request):
    return (
        request.user.is_authenticated
        and request.user.is_active
        and request.user.is_superuser
    )


def skill_to_dict(skill):
    return {
        "id": skill.id,
        "name": skill.name,
        "category": skill.category,
        "displayOrder": skill.display_order,
    }


def certification_to_dict(cert):
    return {
        "id": cert.id,
        "name": cert.name,
        "issuer": cert.issuer,
        "issueDate": cert.issue_date.isoformat() if cert.issue_date else "",
        "credentialId": cert.credential_id,
        "certificateUrl": cert.certificate_url,
        "description": cert.description,
    }


def profile_to_dict(profile):
    return {
        "fullName": profile.full_name,
        "mobileNumber": profile.mobile_number,
        "email": profile.email,
        "address": profile.address,
    }


@require_GET
def public_portfolio_content(request):
    profile = ProfileDetails.objects.first()

    return JsonResponse({
        "skills": [
            skill_to_dict(item)
            for item in Skill.objects.all()
        ],
        "certifications": [
            certification_to_dict(item)
            for item in Certification.objects.all()
        ],
        "profile": profile_to_dict(profile) if profile else {
            "fullName": "Vajrabilash Degapogu",
            "mobileNumber": "",
            "email": "",
            "address": "",
        },
    })


@require_http_methods(["GET", "POST"])
def admin_skills(request):
    if not is_portfolio_admin(request):
        return JsonResponse({"error": "Authentication required."}, status=401)

    if request.method == "GET":
        return JsonResponse({
            "skills": [
                skill_to_dict(item)
                for item in Skill.objects.all()
            ]
        })

    try:
        data = json.loads(request.body or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    name = str(data.get("name", "")).strip()
    if not name:
        return JsonResponse({"error": "Skill name is required."}, status=400)

    if Skill.objects.filter(name__iexact=name).exists():
        return JsonResponse({"error": "This skill already exists."}, status=400)

    skill = Skill.objects.create(
        name=name,
        category=str(data.get("category", "")).strip(),
        display_order=data.get("displayOrder", 0),
    )

    ChangeHistory.objects.create(
        entity_type="Skill",
        entity_id=skill.id,
        action="CREATE",
        description=f"Added skill: {skill.name}",
    )

    return JsonResponse({"skill": skill_to_dict(skill)}, status=201)


@require_http_methods(["PUT", "DELETE"])
def admin_skill_detail(request, skill_id):
    if not is_portfolio_admin(request):
        return JsonResponse({"error": "Authentication required."}, status=401)

    try:
        skill = Skill.objects.get(pk=skill_id)
    except Skill.DoesNotExist:
        return JsonResponse({"error": "Skill not found."}, status=404)

    if request.method == "DELETE":
        name = skill.name
        skill.delete()
        ChangeHistory.objects.create(
            entity_type="Skill",
            entity_id=skill_id,
            action="DELETE",
            description=f"Deleted skill: {name}",
        )
        return JsonResponse({"detail": "Skill deleted."})

    try:
        data = json.loads(request.body or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    name = str(data.get("name", skill.name)).strip()
    if not name:
        return JsonResponse({"error": "Skill name is required."}, status=400)

    if Skill.objects.filter(name__iexact=name).exclude(pk=skill.pk).exists():
        return JsonResponse({"error": "This skill already exists."}, status=400)

    skill.name = name
    skill.category = str(data.get("category", skill.category)).strip()
    skill.display_order = data.get("displayOrder", skill.display_order)
    skill.save()

    ChangeHistory.objects.create(
        entity_type="Skill",
        entity_id=skill.id,
        action="UPDATE",
        description=f"Updated skill: {skill.name}",
    )

    return JsonResponse({"skill": skill_to_dict(skill)})


@require_http_methods(["GET", "POST"])
def admin_certifications(request):
    if not is_portfolio_admin(request):
        return JsonResponse({"error": "Authentication required."}, status=401)

    if request.method == "GET":
        return JsonResponse({
            "certifications": [
                certification_to_dict(item)
                for item in Certification.objects.all()
            ]
        })

    try:
        data = json.loads(request.body or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    name = str(data.get("name", "")).strip()
    if not name:
        return JsonResponse({"error": "Certification name is required."}, status=400)

    issue_date = data.get("issueDate") or None
    cert = Certification(
        name=name,
        issuer=str(data.get("issuer", "")).strip(),
        issue_date=issue_date,
        credential_id=str(data.get("credentialId", "")).strip(),
        certificate_url=str(data.get("certificateUrl", "")).strip(),
        description=str(data.get("description", "")).strip(),
    )

    try:
        cert.full_clean()
        cert.save()
    except ValidationError as exc:
        return JsonResponse({"error": exc.messages[0]}, status=400)

    ChangeHistory.objects.create(
        entity_type="Certification",
        entity_id=cert.id,
        action="CREATE",
        description=f"Added certification: {cert.name}",
    )

    return JsonResponse({"certification": certification_to_dict(cert)}, status=201)


@require_http_methods(["PUT", "DELETE"])
def admin_certification_detail(request, certification_id):
    if not is_portfolio_admin(request):
        return JsonResponse({"error": "Authentication required."}, status=401)

    try:
        cert = Certification.objects.get(pk=certification_id)
    except Certification.DoesNotExist:
        return JsonResponse({"error": "Certification not found."}, status=404)

    if request.method == "DELETE":
        name = cert.name
        cert.delete()
        ChangeHistory.objects.create(
            entity_type="Certification",
            entity_id=certification_id,
            action="DELETE",
            description=f"Deleted certification: {name}",
        )
        return JsonResponse({"detail": "Certification deleted."})

    try:
        data = json.loads(request.body or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    cert.name = str(data.get("name", cert.name)).strip()
    cert.issuer = str(data.get("issuer", cert.issuer)).strip()
    cert.issue_date = data.get("issueDate") or None
    cert.credential_id = str(data.get("credentialId", cert.credential_id)).strip()
    cert.certificate_url = str(data.get("certificateUrl", cert.certificate_url)).strip()
    cert.description = str(data.get("description", cert.description)).strip()

    if not cert.name:
        return JsonResponse({"error": "Certification name is required."}, status=400)

    try:
        cert.full_clean()
        cert.save()
    except ValidationError as exc:
        return JsonResponse({"error": exc.messages[0]}, status=400)

    ChangeHistory.objects.create(
        entity_type="Certification",
        entity_id=cert.id,
        action="UPDATE",
        description=f"Updated certification: {cert.name}",
    )

    return JsonResponse({"certification": certification_to_dict(cert)})


@require_http_methods(["GET", "PUT"])
def admin_profile_details(request):
    if not is_portfolio_admin(request):
        return JsonResponse({"error": "Authentication required."}, status=401)

    profile = ProfileDetails.objects.first()

    if request.method == "GET":
        if not profile:
            return JsonResponse({
                "profile": {
                    "fullName": "Vajrabilash Degapogu",
                    "mobileNumber": "",
                    "email": "",
                    "address": "",
                }
            })
        return JsonResponse({"profile": profile_to_dict(profile)})

    try:
        data = json.loads(request.body or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    if profile is None:
        profile = ProfileDetails()

    profile.full_name = str(data.get("fullName", profile.full_name or "")).strip()
    profile.mobile_number = str(data.get("mobileNumber", profile.mobile_number or "")).strip()
    profile.email = str(data.get("email", profile.email or "")).strip()
    profile.address = str(data.get("address", profile.address or "")).strip()

    if not profile.full_name:
        return JsonResponse({"error": "Full name is required."}, status=400)

    try:
        profile.full_clean()
        profile.save()
    except ValidationError as exc:
        return JsonResponse({"error": exc.messages[0]}, status=400)

    ChangeHistory.objects.create(
        entity_type="ProfileDetails",
        entity_id=profile.id,
        action="UPDATE",
        description="Updated profile details",
    )

    return JsonResponse({"profile": profile_to_dict(profile)})


# ---------- Public and admin job listings ----------

from .models import JobListing


def job_to_dict(job):
    return {
        "id": job.id,
        "category": job.category,
        "jobName": job.job_name,
        "role": job.role,
        "companyName": job.company_name,
        "applicationStartDate": job.application_start_date.isoformat(),
        "applicationEndDate": job.application_end_date.isoformat(),
        "applicationUrl": job.application_url,
        "isPublished": job.is_published,
    }


@require_GET
def public_jobs(request):
    from django.utils import timezone
    jobs = JobListing.objects.filter(
        is_published=True,
        application_end_date__gte=timezone.localdate(),
    )
    return JsonResponse({
        "jobs": [job_to_dict(job) for job in jobs]
    })


@require_http_methods(["GET", "POST"])
def admin_jobs(request):
    if not is_portfolio_admin(request):
        return JsonResponse({"error": "Authentication required."}, status=401)

    if request.method == "GET":
        return JsonResponse({
            "jobs": [job_to_dict(job) for job in JobListing.objects.all()]
        })

    try:
        data = json.loads(request.body or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    try:
        job = JobListing(
            category=str(data.get("category", "")).strip(),
            job_name=str(data.get("jobName", "")).strip(),
            role=str(data.get("role", "")).strip(),
            company_name=str(data.get("companyName", "")).strip(),
            application_start_date=data.get("applicationStartDate"),
            application_end_date=data.get("applicationEndDate"),
            application_url=str(data.get("applicationUrl", "")).strip(),
            is_published=bool(data.get("isPublished", True)),
        )
        if job.category not in ("private", "government"):
            return JsonResponse({"error": "Choose Private Jobs or Government Jobs."}, status=400)
        if not all([job.job_name, job.role, job.company_name, job.application_start_date, job.application_end_date, job.application_url]):
            return JsonResponse({"error": "All job fields are required."}, status=400)
        job.full_clean()
        if job.application_end_date < job.application_start_date:
            return JsonResponse({"error": "Application end date must be on or after the start date."}, status=400)
        job.save()
    except (ValidationError, ValueError, TypeError) as exc:
        message = exc.messages[0] if isinstance(exc, ValidationError) else "Enter valid dates and a valid application URL."
        return JsonResponse({"error": message}, status=400)

    ChangeHistory.objects.create(
        entity_type="JobListing",
        entity_id=job.id,
        action="CREATE",
        description=f"Added {job.category} job: {job.job_name}",
    )
    return JsonResponse({"job": job_to_dict(job)}, status=201)


@require_http_methods(["PUT", "DELETE"])
def admin_job_detail(request, job_id):
    if not is_portfolio_admin(request):
        return JsonResponse({"error": "Authentication required."}, status=401)

    try:
        job = JobListing.objects.get(pk=job_id)
    except JobListing.DoesNotExist:
        return JsonResponse({"error": "Job not found."}, status=404)

    if request.method == "DELETE":
        title = job.job_name
        job.delete()
        ChangeHistory.objects.create(
            entity_type="JobListing",
            entity_id=job_id,
            action="DELETE",
            description=f"Deleted job: {title}",
        )
        return JsonResponse({"detail": "Job deleted."})

    try:
        data = json.loads(request.body or "{}")
        job.category = str(data.get("category", job.category)).strip()
        job.job_name = str(data.get("jobName", job.job_name)).strip()
        job.role = str(data.get("role", job.role)).strip()
        job.company_name = str(data.get("companyName", job.company_name)).strip()
        job.application_start_date = data.get("applicationStartDate", job.application_start_date)
        job.application_end_date = data.get("applicationEndDate", job.application_end_date)
        job.application_url = str(data.get("applicationUrl", job.application_url)).strip()
        job.is_published = bool(data.get("isPublished", job.is_published))
        if job.category not in ("private", "government"):
            return JsonResponse({"error": "Choose a valid job category."}, status=400)
        if not all([job.job_name, job.role, job.company_name, job.application_start_date, job.application_end_date, job.application_url]):
            return JsonResponse({"error": "All job fields are required."}, status=400)
        job.full_clean()
        if job.application_end_date < job.application_start_date:
            return JsonResponse({"error": "Application end date must be on or after the start date."}, status=400)
        job.save()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON."}, status=400)
    except (ValidationError, ValueError, TypeError) as exc:
        message = exc.messages[0] if isinstance(exc, ValidationError) else "Enter valid dates and a valid application URL."
        return JsonResponse({"error": message}, status=400)

    ChangeHistory.objects.create(
        entity_type="JobListing",
        entity_id=job.id,
        action="UPDATE",
        description=f"Updated job: {job.job_name}",
    )
    return JsonResponse({"job": job_to_dict(job)})
