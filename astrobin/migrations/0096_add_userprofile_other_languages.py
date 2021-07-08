# -*- coding: utf-8 -*-
# Generated by Django 1.11.29 on 2021-03-06 16:46


from django.db import migrations
from django.db.models import TextField


class Migration(migrations.Migration):
    dependencies = [
        ('astrobin', '0095_add_userprofile_open_notifications_in_new_tab'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='other_languages',
            field=TextField(
                blank=True,
                null=True,
                help_text='Other languages that you can read and write. This can be useful to other AstroBin members '
                          'who would like to communicate with you.',
                verbose_name='Other languages'),
        ),
    ]
