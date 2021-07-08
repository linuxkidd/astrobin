# -*- coding: utf-8 -*-
# Generated by Django 1.11.28 on 2020-03-16 21:40


import image_cropping.fields
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ('astrobin', '0046_update_filter_field'),
    ]

    operations = [
        migrations.AlterField(
            model_name='image',
            name='square_cropping',
            field=image_cropping.fields.ImageRatioField('image_file', '130x130', adapt_rotation=False,
                                                        allow_fullsize=False, free_crop=False,
                                                        help_text='Select an area of the image to be used as thumbnail in your gallery.',
                                                        hide_image_field=False, size_warning=True,
                                                        verbose_name='Gallery thumbnail'),
        ),
        migrations.AlterField(
            model_name='imagerevision',
            name='square_cropping',
            field=image_cropping.fields.ImageRatioField('image_file', '130x130', adapt_rotation=False,
                                                        allow_fullsize=False, free_crop=False,
                                                        help_text='Select an area of the image to be used as thumbnail in your gallery.',
                                                        hide_image_field=False, size_warning=True,
                                                        verbose_name='Gallery thumbnail'),
        ),
    ]
