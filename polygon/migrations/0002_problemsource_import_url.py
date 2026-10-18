from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('polygon', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='problemsource',
            name='import_url',
            field=models.URLField(blank=True, default='', max_length=1024),
        ),
    ]
