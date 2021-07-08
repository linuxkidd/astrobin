# -*- coding: utf-8 -*-
# Generated by Django 1.11.28 on 2020-03-21 17:04


from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('astrobin_apps_platesolving', '0012_platesolvingadvancedtask'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='platesolvingadvancedsettings',
            name='show_gaia_dr2',
        ),
        migrations.RemoveField(
            model_name='platesolvingadvancedsettings',
            name='show_ppmxl',
        ),
        migrations.AddField(
            model_name='platesolvingadvancedsettings',
            name='show_tycho_2',
            field=models.BooleanField(default=False,
                                      help_text=b'<a href="https://wikipedia.org/wiki/Tycho-2_Catalogue" target="_blank">https://wikipedia.org/wiki/Tycho-2_Catalogue</a>',
                                      verbose_name='Show Tycho-2 catalog'),
        ),
    ]
