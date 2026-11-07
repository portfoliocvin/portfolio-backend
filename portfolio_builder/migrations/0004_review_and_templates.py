from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
from django.utils import timezone


def seed_templates(apps, schema_editor):
    Template = apps.get_model('portfolio_builder', 'PortfolioTemplate')
    defaults = [
        ('minimal', 'Minimal', 'Professional', 'Clean, simple portfolio layout.'),
        ('dark_developer', 'Dark Developer', 'Developer / Techie', 'Dark interface for developers and technical professionals.'),
        ('creative', 'Creative', 'Creative', 'Expressive layout for creative portfolios.'),
        ('professional', 'Professional', 'Professional', 'Traditional professional portfolio layout.'),
        ('modern_profile', 'Modern Profile', 'Professional', 'Modern personal profile layout.'),
        ('career_timeline', 'Career Timeline', 'Student / Career', 'Timeline-focused career presentation.'),
    ]
    for index, (key, name, category, description) in enumerate(defaults):
        Template.objects.get_or_create(
            key=key,
            defaults={
                'name': name,
                'category': category,
                'description': description,
                'is_active': True,
                'is_system': True,
                'display_order': index,
            },
        )


class Migration(migrations.Migration):
    dependencies = [
        ('portfolio_builder', '0003_portfoliocertification_certificate_file'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name='portfoliosite', name='selected_template',
            field=models.CharField(default='minimal', max_length=50),
        ),
        migrations.AlterField(
            model_name='portfoliosite', name='published_template',
            field=models.CharField(default='minimal', max_length=50),
        ),
        migrations.CreateModel(
            name='PortfolioTemplate',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('key', models.SlugField(max_length=50, unique=True)),
                ('name', models.CharField(max_length=100)),
                ('category', models.CharField(max_length=80, default='General')),
                ('description', models.CharField(max_length=300, blank=True)),
                ('preview_image_url', models.URLField(blank=True)),
                ('is_active', models.BooleanField(default=True)),
                ('is_system', models.BooleanField(default=False)),
                ('display_order', models.PositiveIntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={'ordering': ['display_order', 'name']},
        ),
        migrations.CreateModel(
            name='PortfolioReview',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('approved', 'Approved'), ('changes_requested', 'Changes requested')], default='pending', max_length=30)),
                ('template_key', models.CharField(max_length=50)),
                ('content_snapshot', models.JSONField(default=dict)),
                ('submitted_at', models.DateTimeField(default=timezone.now)),
                ('reviewed_at', models.DateTimeField(blank=True, null=True)),
                ('review_notes', models.TextField(blank=True)),
                ('reviewed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='portfolio_reviews_handled', to=settings.AUTH_USER_MODEL)),
                ('site', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='reviews', to='portfolio_builder.portfoliosite')),
                ('submitted_by', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='portfolio_reviews_submitted', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-submitted_at']},
        ),
        migrations.RunPython(seed_templates, migrations.RunPython.noop),
    ]
