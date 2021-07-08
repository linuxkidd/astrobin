# -*- coding: utf-8 -*-
# Generated by Django 1.9.13 on 2018-02-24 15:40


from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('astrobin', '0004_userprofile_updated'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='accept_tos',
            field=models.BooleanField(default=False, editable=False),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='receive_important_communications',
            field=models.BooleanField(default=False, help_text='This is highly recommended. These are very rare and contain information that you probably want to have.', verbose_name='I accept to receive rare important communications via email'),
        ),

        migrations.AddField(
            model_name='userprofile',
            name='receive_marketing_and_commercial_material',
            field=models.BooleanField(default=False, help_text='These emails may contain offers, commercial news, and promotions from AstroBin or its partners.', verbose_name='I accept to receive occasional marketing and commercial material via email'),
        ),

        migrations.AddField(
            model_name='userprofile',
            name='receive_newsletter',
            field=models.BooleanField(default=False, help_text='Newsletters do not have a fixed schedule, but in any case they are not sent out more often than once per month.', verbose_name='I accept to receive occasional newsletters via email'),
        ),
    ]
