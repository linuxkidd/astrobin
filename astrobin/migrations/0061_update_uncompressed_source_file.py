# -*- coding: utf-8 -*-
# Generated by Django 1.11.29 on 2020-09-08 20:14


import common.upload_paths
import common.validators.file_validator
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('astrobin', '0060_is_wip_default_false'),
    ]

    operations = [
        migrations.AlterField(
            model_name='image',
            name='uncompressed_source_file',
            field=models.FileField(help_text='You can store the final processed image that came out of your favorite image editor (e.g. PixInsight, Adobe Photoshop, etc) here on AstroBin, for archival purposes. This file is stored privately and only you will have access to it.', max_length=256, null=True, upload_to=common.upload_paths.uncompressed_source_upload_path, validators=[common.validators.file_validator.FileValidator(allowed_extensions=('xisf', 'fits', 'fit', 'fts', 'psd', 'tiff'))], verbose_name='Uncompressed source (max 100 MB)'),
        ),
    ]
