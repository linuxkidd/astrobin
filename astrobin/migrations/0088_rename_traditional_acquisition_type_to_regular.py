# -*- coding: utf-8 -*-
# Generated by Django 1.11.29 on 2020-12-01 11:59


from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('astrobin', '0087_migrate_traditional_acquisition_type_to_regular'),
    ]

    operations = [
        migrations.AlterField(
            model_name='image',
            name='acquisition_type',
            field=models.CharField(
                choices=[
                    ('REGULAR', 'Regular (e.g. medium/long exposure with a CCD or DSLR)'),
                    ('EAA', 'Electronically-Assisted Astronomy (EAA, e.g. based on a live video feed)'),
                    ('LUCKY', 'Lucky imaging'),
                    ('DRAWING', 'Drawing/Sketch'),
                    ('OTHER', 'Other/Unknown')],
                default=b'REGULAR',
                max_length=32,
                verbose_name='Acquisition type'),
        ),
    ]
