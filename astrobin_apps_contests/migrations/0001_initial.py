# -*- coding: utf-8 -*-
# Generated by Django 1.11.28 on 2020-04-28 20:34
from __future__ import unicode_literals

import astrobin_apps_contests.models.entry
from django.conf import settings
import django.core.validators
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('astrobin', '0054_auto_20200428_2034'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Contest',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('deleted', models.DateTimeField(editable=False, null=True)),
                ('title', models.CharField(max_length=200, unique=True)),
                ('description', models.TextField()),
                ('rules', models.TextField()),
                ('prizes', models.TextField(null=True)),
                ('start_date', models.DateField()),
                ('end_date', models.DateField()),
                ('min_participants', models.PositiveSmallIntegerField(default=2, validators=[django.core.validators.MinValueValidator(2)])),
                ('max_participants', models.PositiveSmallIntegerField(null=True)),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('updated', models.DateTimeField(auto_now=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ('-created',),
            },
        ),
        migrations.CreateModel(
            name='Entry',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('deleted', models.DateTimeField(editable=False, null=True)),
                ('image_file', models.ImageField(height_field='image_height', upload_to=astrobin_apps_contests.models.entry.image_upload_path, width_field='image_width')),
                ('image_width', models.PositiveSmallIntegerField()),
                ('image_height', models.PositiveSmallIntegerField()),
                ('submitted', models.DateTimeField(auto_now_add=True)),
                ('contest', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='astrobin_apps_contests.Contest')),
                ('image', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='astrobin.Image')),
            ],
            options={
                'ordering': ('-submitted',),
            },
        ),
        migrations.CreateModel(
            name='Vote',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('deleted', models.DateTimeField(editable=False, null=True)),
                ('score', models.PositiveSmallIntegerField()),
                ('submitted', models.DateTimeField(auto_now_add=True)),
                ('entry', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='astrobin_apps_contests.Entry')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ('-submitted',),
            },
        ),
        migrations.AlterUniqueTogether(
            name='vote',
            unique_together=set([('user', 'entry')]),
        ),
    ]
