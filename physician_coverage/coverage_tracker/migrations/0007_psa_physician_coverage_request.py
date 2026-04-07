from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('coverage_tracker', '0006_alter_timeoffrequest_status'),
    ]

    operations = [
        migrations.AlterField(
            model_name='physician',
            name='physician_type',
            field=models.CharField(
                choices=[
                    ('regular', 'Regular Physician'),
                    ('locum', 'Locum / Covering Physician'),
                    ('psa', 'PSA Physician'),
                ],
                default='regular',
                max_length=10,
            ),
        ),
        migrations.CreateModel(
            name='CoverageRequest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('requested_date', models.DateField()),
                ('status', models.CharField(
                    choices=[('pending', 'Pending'), ('approved', 'Approved'), ('denied', 'Denied')],
                    default='pending',
                    max_length=20,
                )),
                ('notes', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('physician', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='coverage_requests',
                    to='coverage_tracker.physician',
                )),
            ],
            options={
                'ordering': ['-requested_date'],
                'unique_together': {('physician', 'requested_date')},
            },
        ),
    ]
