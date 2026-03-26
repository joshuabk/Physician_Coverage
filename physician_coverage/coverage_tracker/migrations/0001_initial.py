from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.CreateModel(
            name='Clinic',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200)),
                ('location', models.CharField(blank=True, max_length=200)),
                ('specialty', models.CharField(blank=True, max_length=100)),
                ('is_active', models.BooleanField(default=True)),
            ],
            options={'ordering': ['name']},
        ),
        migrations.CreateModel(
            name='Physician',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('first_name', models.CharField(max_length=100)),
                ('last_name', models.CharField(max_length=100)),
                ('email', models.EmailField(unique=True)),
                ('specialty', models.CharField(blank=True, max_length=100)),
                ('total_vacation_days', models.PositiveIntegerField(default=20)),
                ('is_active', models.BooleanField(default=True)),
                ('user', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='auth.user')),
            ],
            options={'ordering': ['last_name', 'first_name']},
        ),
        migrations.CreateModel(
            name='TimeOffRequest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('start_date', models.DateField()),
                ('end_date', models.DateField()),
                ('request_type', models.CharField(choices=[('vacation', 'Vacation'), ('sick', 'Sick Leave'), ('conference', 'Conference / CME'), ('personal', 'Personal'), ('other', 'Other')], default='vacation', max_length=20)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('approved', 'Approved'), ('denied', 'Denied'), ('cancelled', 'Cancelled')], default='pending', max_length=20)),
                ('notes', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('physician', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='time_off_requests', to='coverage_tracker.physician')),
            ],
            options={'ordering': ['-start_date']},
        ),
        migrations.CreateModel(
            name='PhysicianAvailability',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField()),
                ('is_available', models.BooleanField(default=True)),
                ('notes', models.TextField(blank=True)),
                ('physician', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='availability_slots', to='coverage_tracker.physician')),
            ],
            options={'ordering': ['date', 'physician'], 'unique_together': {('physician', 'date')}},
        ),
        migrations.CreateModel(
            name='CoverageAssignment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField()),
                ('notes', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('clinic', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='coverage_assignments', to='coverage_tracker.clinic')),
                ('covered_physician', models.ForeignKey(blank=True, help_text='Physician being covered (leave blank for regular staffing)', null=True, on_delete=django.db.models.deletion.CASCADE, related_name='covered_assignments', to='coverage_tracker.physician')),
                ('covering_physician', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='coverage_assignments', to='coverage_tracker.physician')),
            ],
            options={'ordering': ['date', 'clinic'], 'unique_together': {('clinic', 'covering_physician', 'date')}},
        ),
    ]
