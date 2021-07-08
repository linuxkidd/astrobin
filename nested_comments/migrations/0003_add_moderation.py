# -*- coding: utf-8 -*-
# Generated by Django 1.11.29 on 2021-01-17 13:44


import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import common.utils
import nested_comments.models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('nested_comments', '0002_auto_20171112_1510'),
    ]

    operations = [
        migrations.AddField(
            model_name='nestedcomment',
            name='moderator',
            field=models.ForeignKey(default=None, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name='moderated_comments', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='nestedcomment',
            name='pending_moderation',
            field=models.NullBooleanField(),
        ),
        migrations.AlterField(
            model_name='nestedcomment',
            name='author',
            field=models.ForeignKey(editable=False, on_delete=models.SET(common.utils.get_sentinel_user),
                                    related_name='comments', to=settings.AUTH_USER_MODEL),
        ),
    ]
