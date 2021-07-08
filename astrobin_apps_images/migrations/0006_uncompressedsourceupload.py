# -*- coding: utf-8 -*-
# Generated by Django 1.11.29 on 2020-09-06 17:36


import common.upload_paths
import common.validators.file_validator
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('astrobin_apps_images', '0005_add_sharpened_inverted'),
    ]

    operations = [
        migrations.CreateModel(
            name='UncompressedSourceUpload',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('uncompressed_source_file', models.FileField(help_text='You can store the final processed image that came out of your favorite image editor (e.g. PixInsight, Adobe Photoshop, etc) here on AstroBin, for archival purposes. This file is stored privately and only you will have access to it.', max_length=256, null=True, upload_to=common.upload_paths.uncompressed_source_upload_path, validators=[common.validators.file_validator.FileValidator(allowed_extensions=('xisf', 'fits', 'fit', 'fts', 'psd', 'tiff'))], verbose_name='Uncompressed source (max 100 MB)')),
                ('image', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='uncompressed_source_upload', to='astrobin.Image')),
            ],
        ),
    ]
