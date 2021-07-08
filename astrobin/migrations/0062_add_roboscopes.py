# -*- coding: utf-8 -*-
# Generated by Django 1.11.29 on 2020-09-10 06:43


from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('astrobin', '0061_update_uncompressed_source_file'),
    ]

    operations = [
        migrations.AlterField(
            model_name='image',
            name='remote_source',
            field=models.CharField(blank=True,
                                   choices=[(None, '---------'), ('OWN', 'Non-commercial independent facility'),
                                            (None, '---------'), ('AC', 'AstroCamp'),
                                            ('AHK', 'Astro Hostel Krasnodar'),
                                            ('AOWA', 'Astro Observatories Western Australia'), ('CS', 'ChileScope'),
                                            ('DSNM', 'Dark Sky New Mexico'), ('DSP', 'Dark Sky Portal'),
                                            ('DSC', 'DeepSkyChile'), ('DSW', 'DeepSkyWest'),
                                            ('eEyE', 'e-EyE Extremadura'), ('GMO', 'Grand Mesa Observatory'),
                                            ('HMO', "Heaven's Mirror Observatory"),
                                            ('IC', 'IC Astronomy Observatories'), ('ITU', 'Image The Universe'),
                                            ('INS', 'Insight Observatory'), ('iT', 'iTelescope'),
                                            ('LGO', 'Lijiang Gemini Observatory'),
                                            ('MARIO', 'Marathon Remote Imaging Observatory (MaRIO)'),
                                            ('NMS', 'New Mexico Skies'), ('OES', 'Observatorio El Sauce'),
                                            ('PSA', 'PixelSkies'), ('REM', 'RemoteSkies.net'),
                                            ('RLD', 'Riverland Dingo Observatory'), ('ROBO', 'RoboScopes'),
                                            ('SS', 'Sahara Sky'), ('SPVO', 'San Pedro Valley Observatory'),
                                            ('SRO', 'Sierra Remote Observatories'),
                                            ('SRO2', 'Sky Ranch Observatory'), ('SPOO', 'SkyPi Online Observatory'),
                                            ('SLO', 'Slooh'), ('SSLLC', 'Stellar Skies LLC'),
                                            ('OTHER', 'None of the above')],
                                   help_text='Which remote hosting facility did you use to acquire data for this image?',
                                   max_length=8, null=True, verbose_name='Remote data source'),
        ),
    ]
