# -*- coding: utf-8 -*-
# Generated by Django 1.11.29 on 2020-10-30 19:10


from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('astrobin', '0075_add_userprofile_delete_reason_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='banned_from_competitions',
            field=models.DateTimeField(blank=True, editable=False, null=True),
        ),
    ]
