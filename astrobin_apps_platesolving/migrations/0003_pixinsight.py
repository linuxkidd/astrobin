# -*- coding: utf-8 -*-
# Generated by Django 1.11.27 on 2020-02-10 07:17


from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('astrobin_apps_platesolving', '0002_auto_20171109_2307'),
    ]

    operations = [
        migrations.AddField(
            model_name='solution',
            name='advanced_dec',
            field=models.DecimalField(blank=True, decimal_places=9, max_digits=11, null=True),
        ),
        migrations.AddField(
            model_name='solution',
            name='advanced_dec_bottom_left',
            field=models.DecimalField(blank=True, decimal_places=9, max_digits=11, null=True),
        ),
        migrations.AddField(
            model_name='solution',
            name='advanced_dec_bottom_right',
            field=models.DecimalField(blank=True, decimal_places=8, max_digits=11, null=True),
        ),
        migrations.AddField(
            model_name='solution',
            name='advanced_dec_top_left',
            field=models.DecimalField(blank=True, decimal_places=8, max_digits=11, null=True),
        ),
        migrations.AddField(
            model_name='solution',
            name='advanced_dec_top_right',
            field=models.DecimalField(blank=True, decimal_places=8, max_digits=11, null=True),
        ),
        migrations.AddField(
            model_name='solution',
            name='advanced_flipped',
            field=models.NullBooleanField(),
        ),
        migrations.AddField(
            model_name='solution',
            name='advanced_orientation',
            field=models.DecimalField(blank=True, decimal_places=3, max_digits=6, null=True),
        ),
        migrations.AddField(
            model_name='solution',
            name='advanced_pixscale',
            field=models.DecimalField(blank=True, decimal_places=3, max_digits=6, null=True),
        ),
        migrations.AddField(
            model_name='solution',
            name='advanced_ra',
            field=models.DecimalField(blank=True, decimal_places=8, max_digits=11, null=True),
        ),
        migrations.AddField(
            model_name='solution',
            name='advanced_ra_bottom_left',
            field=models.DecimalField(blank=True, decimal_places=8, max_digits=11, null=True),
        ),
        migrations.AddField(
            model_name='solution',
            name='advanced_ra_bottom_right',
            field=models.DecimalField(blank=True, decimal_places=8, max_digits=11, null=True),
        ),
        migrations.AddField(
            model_name='solution',
            name='advanced_ra_top_left',
            field=models.DecimalField(blank=True, decimal_places=8, max_digits=11, null=True),
        ),
        migrations.AddField(
            model_name='solution',
            name='advanced_ra_top_right',
            field=models.DecimalField(blank=True, decimal_places=8, max_digits=11, null=True),
        ),
        migrations.AddField(
            model_name='solution',
            name='advanced_wcs_transformation',
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
        migrations.AddField(
            model_name='solution',
            name='pixinsight_serial_number',
            field=models.CharField(blank=True, max_length=32, null=True),
        ),
        migrations.AddField(
            model_name='solution',
            name='pixinsight_svg_annotation',
            field=models.ImageField(blank=True, null=True, upload_to=b'pixinsight-solutions'),
        ),
        migrations.AlterField(
            model_name='solution',
            name='status',
            field=models.PositiveIntegerField(choices=[(0, 'Missing'), (1, 'Pending'), (2, 'Failed'), (3, 'Success'), (4, 'Advanced pending'), (5, 'Advanced failed'), (6, 'Advanced success')], default=0),
        ),
    ]
