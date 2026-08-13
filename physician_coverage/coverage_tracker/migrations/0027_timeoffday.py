"""Per-day approval for time-off requests.

Creates the TimeOffDay model and backfills one row per business day for
every existing (non-cancelled) request, inheriting the request's current
status so history is preserved: approved requests get all-approved days,
denied get all-denied, pending get all-pending.
"""
from django.db import migrations, models
import django.db.models.deletion


def _backfill_days(apps, schema_editor):
    # Plain helper functions (no model state) — safe to import directly.
    from coverage_tracker.models import get_holidays, get_extra_workdays, is_workday
    import datetime

    TimeOffRequest = apps.get_model('coverage_tracker', 'TimeOffRequest')
    TimeOffDay = apps.get_model('coverage_tracker', 'TimeOffDay')

    rows = []
    for req in TimeOffRequest.objects.exclude(status='cancelled'):
        holidays, extra = set(), set()
        for y in range(req.start_date.year, req.end_date.year + 1):
            holidays |= set(get_holidays(y))
            extra |= get_extra_workdays(y)
        day_status = req.status if req.status in ('approved', 'denied') else 'pending'
        current = req.start_date
        while current <= req.end_date:
            if is_workday(current, holidays, extra):
                rows.append(TimeOffDay(request=req, date=current, status=day_status))
            current += datetime.timedelta(days=1)
    TimeOffDay.objects.bulk_create(rows, batch_size=500)


def _drop_days(apps, schema_editor):
    TimeOffDay = apps.get_model('coverage_tracker', 'TimeOffDay')
    TimeOffDay.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('coverage_tracker', '0026_physician_availability_notes'),
    ]

    operations = [
        migrations.CreateModel(
            name='TimeOffDay',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField()),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('approved', 'Approved'), ('denied', 'Denied')], default='pending', max_length=20)),
                ('decided_by', models.CharField(blank=True, max_length=150)),
                ('decided_at', models.DateTimeField(blank=True, null=True)),
                ('request', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='days', to='coverage_tracker.timeoffrequest')),
            ],
            options={
                'ordering': ['date'],
            },
        ),
        migrations.AddConstraint(
            model_name='timeoffday',
            constraint=models.UniqueConstraint(fields=('request', 'date'), name='one_day_row_per_request_date'),
        ),
        migrations.RunPython(_backfill_days, _drop_days),
    ]
