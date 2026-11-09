# Generated for Portfolio.cv job listings.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("portfolio_api", "0002_certification_profiledetails_skill"),
    ]

    operations = [
        migrations.CreateModel(
            name="JobListing",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("category", models.CharField(choices=[("private", "Private Jobs"), ("government", "Government Jobs")], max_length=20)),
                ("job_name", models.CharField(max_length=200)),
                ("role", models.CharField(max_length=200)),
                ("company_name", models.CharField(max_length=200)),
                ("application_start_date", models.DateField()),
                ("application_end_date", models.DateField()),
                ("application_url", models.URLField(max_length=1000)),
                ("is_published", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["application_end_date", "-created_at"]},
        ),
    ]
