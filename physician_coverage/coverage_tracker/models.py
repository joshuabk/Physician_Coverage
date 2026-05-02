from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import date
import datetime
import calendar
from decimal import Decimal


def get_holidays(year):
    holidays = []
    
    # Fixed holidays
    holidays.append(date(year, 1, 1))   # New Year's Day
    holidays.append(date(year, 7, 4))   # Independence Day
    holidays.append(date(year, 12, 25)) # Christmas Day
    may_cal = calendar.monthcalendar(year, 5)
    last_monday_may = [week[0] for week in may_cal if week[0] != 0][-1]
    holidays.append(date(year, 5, last_monday_may))
    
    # Labor Day: First Monday in September
    sep_cal = calendar.monthcalendar(year, 9)
    first_monday_sep = next(week[0] for week in sep_cal if week[0] != 0)
    holidays.append(date(year, 9, first_monday_sep))
    
    # Thanksgiving: 4th Thursday in November
    nov_cal = calendar.monthcalendar(year, 11)
    thursdays = [week[3] for week in nov_cal if week[3] != 0]  # Thursday index = 3
    fourth_thursday = thursdays[3]
    holidays.append(date(year, 11, fourth_thursday))
    
    return sorted(holidays)


HOLIDAYS = {
    (1, 1),   # New Year's Day
    (5, 25),  # Memorial Day
    (7, 4),   # Independence Day
    (9, 7),   # Labor Day
    (11, 26), # Thanksgiving
    (12, 25), # Christmas
}

def check_holiday(day):
    is_holiday = (day.month, day.day) in HOLIDAYS
    return is_holiday

class Physician(models.Model):
    PHYSICIAN_TYPE_CHOICES = [
        ('regular', 'NROC Physician'),
        ('locum', 'Locum / Covering Physician'),
        ('psa', 'PSA Physician'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, null=True, blank=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField(unique=True)
    
    physician_type = models.CharField(max_length=10, choices=PHYSICIAN_TYPE_CHOICES, default='regular')
    total_vacation_days = models.PositiveIntegerField(
        default=20,
        help_text="Annual vacation day allocation (for NROC physicians)"
    )
    daily_rate = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Legacy / standard daily rate (kept for reference — hourly rate is used for pay)"
    )
    hourly_rate = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Hourly rate for locum physicians. Daily pay = hourly rate × hours worked."
    )
    agency = models.CharField(
        max_length=200, blank=True,
        help_text="Staffing agency name (for locum physicians)"
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['physician_type', 'last_name', 'first_name']

    def __str__(self):
        return f"Dr. {self.first_name} {self.last_name}"

    @property
    def is_locum(self):
        return self.physician_type == 'locum'

    @property
    def is_regular(self):
        return self.physician_type == 'regular'

    @property
    def is_psa(self):
        return self.physician_type == 'psa'

    def days_taken(self, year=None):
        if year is None:
            year = timezone.now().year
        total = 0
        for req in TimeOffRequest.objects.filter(physician=self, status='approved', start_date__year=year):
            total += (req.end_date - req.start_date).days + 1
        return total

    def days_remaining(self, year=None):
        return self.total_vacation_days - self.days_taken(year)

    def days_pending(self, year=None):
        if year is None:
            year = timezone.now().year
        total = 0
        for req in TimeOffRequest.objects.filter(physician=self, status='pending', start_date__year=year):
            total += (req.end_date - req.start_date).days + 1
        return total

    def total_coverage_days(self, year=None):
        if year is None:
            year = timezone.now().year
        return CoverageAssignment.objects.filter(covering_physician=self, date__year=year).count()
    
    def total_coverage_hours(self, year=None):
        if year is None:
            year = timezone.now().year
        from django.db.models import Sum
        result = CoverageAssignment.objects.filter(
            covering_physician=self, date__year=year
        ).aggregate(total=Sum('hours'))
        return result['total'] or Decimal('0.00')

    def total_coverage_cost(self, year=None):
        if year is None:
            year = timezone.now().year
        assignments = CoverageAssignment.objects.filter(
            covering_physician=self, date__year=year
        )
        total = Decimal('0.00')
        for a in assignments:
            rate = a.hourly_rate_override if a.hourly_rate_override is not None else self.hourly_rate
            if rate is None:
                continue
            total += (rate * a.hours)
        return total.quantize(Decimal('0.01'))

    def requested_coverage_days(self, year=None):
        if year is None:
            year = timezone.now().year
        return CoverageRequest.objects.filter(physician=self, requested_date__year=year).count()


class Clinic(models.Model):
    name = models.CharField(max_length=200)
    location = models.CharField(max_length=200, blank=True)
    
    regular_physicians = models.ManyToManyField(
        'Physician',
        blank=True,
        related_name='assigned_clinics',
        limit_choices_to={'physician_type__in': ['regualr', 'psa']},
        help_text= "NROC and PSA physicians permanently assigned to this clinic"
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class TimeOffRequest(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('denied', 'Denied'),
        ('cancelled', 'Cancelled'),
        
    ]
    TYPE_CHOICES = [
        ('vacation', 'Vacation'),
        ('sick', 'Sick Leave'),
        ('conference', 'Conference / CME'),
        ('personal', 'Personal'),
        ('other', 'Other'),
    ]

    physician = models.ForeignKey(Physician, on_delete=models.CASCADE, related_name='time_off_requests')
    start_date = models.DateField()
    end_date = models.DateField()
    request_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='vacation')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-start_date']

    def __str__(self):
        return f"{self.physician} — {self.start_date} to {self.end_date}"

    @property
    def duration_days(self):
        total = 0
        current = self.start_date
        year = self.start_date.year
        holidays = get_holidays(year)
        while current <= self.end_date:
            if current.weekday() < 5 and not current in holidays:  # 0=Mon, 4=Fri, 5=Sat, 6=Sun
                total += 1
            current += datetime.timedelta(days=1)
        return total

class CoverageAssignment(models.Model):
    clinic = models.ForeignKey(Clinic, on_delete=models.CASCADE, related_name='coverage_assignments')
    hours = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    covering_physician = models.ForeignKey(
        Physician, on_delete=models.CASCADE, related_name='coverage_assignments',
        null=True, blank=True,  
        limit_choices_to={'physician_type': 'locum'},
        help_text="Locum physician providing coverage"
    )
    covered_physician = models.ForeignKey(
        Physician, on_delete=models.CASCADE, related_name='covered_assignments',
        null=True, blank=True,
        limit_choices_to={'physician_type': 'regular'},
        help_text="NROC physician being covered (optional)"
    )
    date = models.DateField()

    no_coverage_needed = models.BooleanField(
        default=False,
        help_text="Mark this day as resolved without assigning a locum (e.g., half day, shift swapped)."
    )
    no_coverage_reason = models.CharField(
        max_length=255, blank=True,
        help_text="Required reason when 'no coverage needed' is set (e.g., 'half day', 'physician swapped shift')."
    )

    hourly_rate_override = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Override the locum's standard hourly rate for this specific assignment"
    )

    daily_rate_override = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Override the locum's standard daily rate for this specific assignment"
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['date', 'clinic']
        # OLD: unique_together = ['clinic', 'covering_physician', 'date']
        # That breaks once covering_physician can be null (multiple "no coverage"
        # rows would collide). Replaced with conditional constraints:
        constraints = [
            models.UniqueConstraint(
                fields=['clinic', 'covering_physician', 'date'],
                condition=models.Q(covering_physician__isnull=False),
                name='unique_clinic_locum_date_when_assigned',
            ),
            # One "no coverage needed" marker per covered physician per day
            models.UniqueConstraint(
                fields=['covered_physician', 'date'],
                condition=models.Q(no_coverage_needed=True),
                name='unique_no_coverage_per_covered_physician_per_day',
            ),
        ]


    def __str__(self):
        return f"{self.clinic} — {self.covering_physician} on {self.date}"
    
    @property
    def is_no_coverage(self):
        return self.no_coverage_needed


    @property
    def effective_hourly_rate(self):
        """Hourly rate used for pay — per-assignment override beats physician default."""
        if self.no_coverage_needed or self.covering_physician is None:   # ← NEW guard
            return Decimal('0.00')
        if self.hourly_rate_override is not None:
            return self.hourly_rate_override
        return self.covering_physician.hourly_rate or Decimal('0.00')
    
    @property
    def effective_daily_rate(self):
        if self.no_coverage_needed or self.covering_physician is None:   # ← NEW guard
            return Decimal('0.00')
        if self.hourly_rate_override is not None or self.covering_physician.hourly_rate:
            hours = self.hours if self.hours is not None else Decimal('0.00')   # ← null-safe
            return (self.effective_hourly_rate * hours).quantize(Decimal('0.01'))
        if self.daily_rate_override is not None:
            return self.daily_rate_override
        return self.covering_physician.daily_rate or Decimal('0.00')
       

    @property
    def cost(self):
        return self.effective_daily_rate


class PhysicianAvailability(models.Model):
    physician = models.ForeignKey(
        Physician, on_delete=models.CASCADE, related_name='availability_slots',
        limit_choices_to={'physician_type': 'locum'}
    )
    date = models.DateField()
    is_available = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['date', 'physician']
        unique_together = ['physician', 'date']

    def __str__(self):
        status = "Available" if self.is_available else "Unavailable"
        return f"{self.physician} — {self.date} ({status})"


class CoverageRequest(models.Model):
    """Tracks requested coverage days for PSA physicians."""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('denied', 'Denied'),
    ]
    physician = models.ForeignKey(
        Physician, on_delete=models.CASCADE, related_name='coverage_requests'
    )
    requested_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-requested_date']
        unique_together = ['physician', 'requested_date']

    def __str__(self):
        return f"{self.physician} — {self.requested_date} ({self.status})"


class UserProfile(models.Model):
    """Extends Django User with role and scope.

    Scope determines which physicians' time off a non-admin user can see:
    - 'nroc' → NROC physicians only
    - 'psa'  → PSA physicians only
    - 'all'  → both (admins always behave as 'all' regardless of scope)
    """
    ROLE_CHOICES = [
        ('admin', 'Administrator'),
        ('physician_admin', 'Physician Administrator'),
        ('physician', 'Physician'),
    ]
    SCOPE_CHOICES = [
        ('nroc', 'NROC Physicians'),
        ('psa', 'PSA Physicians'),
        ('all', 'Both NROC and PSA'),
    ]
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='physician')
    scope = models.CharField(
        max_length=10, choices=SCOPE_CHOICES, default='nroc',
        help_text="Which physician group this login represents."
    )
    physician = models.OneToOneField(
        Physician, on_delete=models.SET_NULL, null=True, blank=True,
        help_text="Optional: link to a specific physician record (not required for shared logins)."
    )

    @property
    def is_admin(self):
        return self.role == 'admin' or self.user.is_superuser
    
    @property
    def is_physician_admin(self):
        return self.role == 'physician_admin'


    @property
    def is_physician(self):
        return self.role == 'physician'
    
    @property
    def can_approve_time_off(self):
        """True for full admins and physician administrators."""
        return self.is_admin or self.is_physician_admin

    def __str__(self):
        return f"{self.user.username} ({self.get_role_display()})"
