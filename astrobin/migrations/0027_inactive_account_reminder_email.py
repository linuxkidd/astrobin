# -*- coding: utf-8 -*-
# Generated by Django 1.9.13 on 2019-08-30 10:38


from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('astrobin', '0026_broadcast_email_message_split'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='inactive_account_reminder_sent',
            field=models.DateTimeField(null=True),
        ),
    ]
