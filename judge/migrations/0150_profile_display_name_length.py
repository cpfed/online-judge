from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('judge', '0149_add_organization_private_problems_permission'),
    ]

    operations = [
        migrations.AlterField(
            model_name='profile',
            name='username_display_override',
            field=models.CharField(
                blank=True,
                help_text='Name displayed in place of username.',
                max_length=256,
                verbose_name='display name override',
            ),
        ),
    ]
