from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('coverage_tracker', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='physician',
            name='physician_type',
            field=models.CharField(choices=[('regular', 'Regular Physician'), ('locum', 'Locum / Covering Physician')], default='regular', max_length=10),
        ),
        migrations.AddField(
            model_name='physician',
            name='daily_rate',
            field=models.DecimalField(blank=True, decimal_places=2, help_text='Daily rate in USD (for locum physicians)', max_digits=10, null=True),
        ),
        migrations.AddField(
            model_name='physician',
            name='agency',
            field=models.CharField(blank=True, help_text='Staffing agency name (for locum physicians)', max_length=200),
        ),
        migrations.AddField(
            model_name='coverageassignment',
            name='daily_rate_override',
            field=models.DecimalField(blank=True, decimal_places=2, help_text='Override the locum standard daily rate for this assignment', max_digits=10, null=True),
        ),
        migrations.AddField(
            model_name='clinic',
            name='regular_physicians',
            field=models.ManyToManyField(blank=True, help_text='Regular physicians permanently assigned to this clinic', limit_choices_to={'physician_type': 'regular'}, related_name='assigned_clinics', to='coverage_tracker.physician'),
        ),
    ]
