# -*- coding: utf-8 -*-
# Generated by Django 1.11.29 on 2020-12-08 22:30


from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='ExchangeRate',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('rate', models.DecimalField(decimal_places=5, max_digits=8)),
                ('source', models.CharField(max_length=3)),
                ('target', models.CharField(max_length=3)),
                ('time', models.DateTimeField()),
            ],
        ),
    ]
