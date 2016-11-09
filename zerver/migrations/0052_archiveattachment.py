# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models
import django.utils.timezone
from django.conf import settings
import zerver.lib.str_utils


class Migration(migrations.Migration):

    dependencies = [
        ('zerver', '0051_archive_user_message'),
    ]

    operations = [
        migrations.CreateModel(
            name='ArchiveAttachment',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('file_name', models.TextField(db_index=True)),
                ('path_id', models.TextField(db_index=True)),
                ('is_realm_public', models.BooleanField(default=False)),
                ('create_time', models.DateTimeField(default=django.utils.timezone.now, db_index=True)),
                ('archived_date', models.DateTimeField(default=django.utils.timezone.now, verbose_name='data archived', db_index=True)),
                ('messages', models.ManyToManyField(to='zerver.ArchiveMessage')),
                ('owner', models.ForeignKey(to=settings.AUTH_USER_MODEL)),
                ('realm', models.ForeignKey(blank=True, to='zerver.Realm', null=True)),
            ],
            options={
                'abstract': False,
            },
            bases=(zerver.lib.str_utils.ModelReprMixin, models.Model),
        ),
    ]
