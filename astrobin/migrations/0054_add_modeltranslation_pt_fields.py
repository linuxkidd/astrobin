# -*- coding: utf-8 -*-
# Generated by Django 1.11.28 on 2020-03-16 21:42


from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ('astrobin', '0053_migrate_subject_type_and_solar_system_subject_to_charfield'),
    ]

    operations = [
        migrations.RenameField(
            model_name='commercialgear',
            old_name='tagline_pt_BR',
            new_name='tagline_pt'
        ),
        migrations.RenameField(
            model_name='commercialgear',
            old_name='description_pt_BR',
            new_name='description_pt'
        )
    ]
