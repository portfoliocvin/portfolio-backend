from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("portfolio_builder", "0005_alter_portfolioreview_reviewed_by_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="portfoliosite",
            name="selected_template",
            field=models.CharField(
                choices=[
                    ("minimal", "Minimal"),
                    ("dark_developer", "Dark Developer"),
                    ("creative", "Creative"),
                    ("professional", "Professional"),
                    ("modern_profile", "Modern Profile"),
                    ("career_timeline", "Career Timeline"),
                ],
                default="minimal",
                max_length=50,
            ),
        ),
        migrations.AlterField(
            model_name="portfoliosite",
            name="published_template",
            field=models.CharField(
                choices=[
                    ("minimal", "Minimal"),
                    ("dark_developer", "Dark Developer"),
                    ("creative", "Creative"),
                    ("professional", "Professional"),
                    ("modern_profile", "Modern Profile"),
                    ("career_timeline", "Career Timeline"),
                ],
                default="minimal",
                max_length=50,
            ),
        ),
    ]
