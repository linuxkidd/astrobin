# -*- coding: utf-8 -*-
# Generated by Django 1.11.28 on 2020-04-06 09:19


from django.db import migrations, models

from astrobin.enums import SubjectType, SolarSystemSubject
from astrobin.models import Image

SUBJECT_TYPE_MIGRATION_MAP = {
    100: SubjectType.DEEP_SKY,
    200: SubjectType.SOLAR_SYSTEM,
    300: SubjectType.WIDE_FIELD,
    400: SubjectType.STAR_TRAILS,
    450: SubjectType.NORTHERN_LIGHTS,
    500: SubjectType.GEAR,
    600: SubjectType.OTHER,
}  # type: Dict[int, str]

SOLAR_SYSTEM_SUBJECT_MIGRATION_MAP = {
    None: None,
    0: SolarSystemSubject.SUN,
    1: SolarSystemSubject.MOON,
    2: SolarSystemSubject.MERCURY,
    3: SolarSystemSubject.VENUS,
    4: SolarSystemSubject.MARS,
    5: SolarSystemSubject.JUPITER,
    6: SolarSystemSubject.SATURN,
    7: SolarSystemSubject.URANUS,
    8: SolarSystemSubject.NEPTUNE,
    9: SolarSystemSubject.MINOR_PLANET,
    10: SolarSystemSubject.COMET,
    11: SolarSystemSubject.OTHER,
}  # type: Dict[int, str]


def get_images(apps):
    # type: (object) -> QuerySet
    return apps.get_model('astrobin', 'Image').objects.all()


def migrate_subject_type_values(apps, schema_editor):
    for old_value, new_value in SUBJECT_TYPE_MIGRATION_MAP.items():
        get_images(apps).filter(subject_type=old_value).update(subject_type=new_value)
    get_images(apps).filter(subject_type=0).update(subject_type=SubjectType.OTHER)

def reverse_migrate_subject_type_values(apps, schema_editor):
    for old_value, new_value in SUBJECT_TYPE_MIGRATION_MAP.items():
        get_images(apps).filter(subject_type=new_value).update(subject_type=old_value)


def migrate_solar_system_subject_values(apps, schema_editor):
    for old_value, new_value in SOLAR_SYSTEM_SUBJECT_MIGRATION_MAP.items():
        get_images(apps).filter(solar_system_main_subject=old_value).update(solar_system_main_subject=new_value)


def reverse_migrate_solar_system_subjects_values(apps, schema_editor):
    for old_value, new_value in SOLAR_SYSTEM_SUBJECT_MIGRATION_MAP.items():
        get_images(apps).filter(solar_system_main_subject=new_value).update(solar_system_main_subject=old_value)


class Migration(migrations.Migration):
    dependencies = [
        ('astrobin', '0052_data_migrate_subject_type_and_solar_system_subject_to_charfield'),
    ]

    operations = [
        migrations.RunPython(migrate_subject_type_values, reverse_migrate_subject_type_values),
        migrations.RunPython(migrate_solar_system_subject_values, reverse_migrate_solar_system_subjects_values),
    ]
