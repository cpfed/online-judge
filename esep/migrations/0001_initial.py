import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    # Depends on the judge app having Contest/Profile. Points at the current judge head;
    # this only references (doesn't add to) the judge migration graph, so it never creates
    # a judge migration-number conflict when syncing the DMOJ fork.
    dependencies = [
        ('judge', '0149_add_organization_private_problems_permission'),
    ]

    operations = [
        migrations.CreateModel(
            name='ContestAnnouncement',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('body', models.TextField(verbose_name='announcement body')),
                ('time', models.DateTimeField(auto_now_add=True, verbose_name='announcement time')),
                ('author', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='contest_announcements', to='judge.Profile', verbose_name='author')),
                ('contest', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='announcements', to='judge.Contest', verbose_name='contest')),
            ],
            options={
                'verbose_name': 'contest announcement',
                'verbose_name_plural': 'contest announcements',
                'ordering': ['-time'],
            },
        ),
    ]
