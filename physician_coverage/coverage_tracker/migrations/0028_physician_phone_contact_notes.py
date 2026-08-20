from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('coverage_tracker', '0027_timeoffday'),
    ]

    operations = [
        migrations.AddField(
            model_name='physician',
            name='phone',
            field=models.CharField(blank=True, help_text='Contact phone number', max_length=30),
        ),
        migrations.AddField(
            model_name='physician',
            name='contact_notes',
            field=models.TextField(blank=True, help_text='Free-text contact notes (shown on the Locum Contacts page)'),
        ),
    ]
