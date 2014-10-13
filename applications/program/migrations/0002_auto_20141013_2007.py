# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('program', '0001_initial'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='participant',
            name='convention',
        ),
        migrations.RemoveField(
            model_name='participant',
            name='user',
        ),
        migrations.DeleteModel(
            name='Participant',
        ),
    ]
