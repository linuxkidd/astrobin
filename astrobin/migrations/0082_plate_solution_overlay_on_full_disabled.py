# -*- coding: utf-8 -*-
# Generated by Django 1.11.29 on 2020-11-22 10:40


from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('astrobin', '0081_add_uploader_fields_to_image_revision'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='plate_solution_overlay_on_full_disabled',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
