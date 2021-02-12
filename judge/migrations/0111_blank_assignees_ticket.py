# Generated by Django 2.2.15 on 2020-09-13 16:05

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('judge', '0110_default_output_prefix_override'),
    ]

    operations = [
        migrations.AlterField(
            model_name='ticket',
            name='assignees',
            field=models.ManyToManyField(blank=True, related_name='assigned_tickets', to='judge.Profile', verbose_name='assignees'),
        ),
    ]