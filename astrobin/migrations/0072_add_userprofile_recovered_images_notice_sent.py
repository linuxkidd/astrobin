# -*- coding: utf-8 -*-
# Generated by Django 1.11.29 on 2020-10-16 12:47


from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('astrobin', '0071_add_eye_in_the_sky'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='recovered_images_notice_sent',
            field=models.DateTimeField(null=True),
        ),
    ]
