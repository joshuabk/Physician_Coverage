from django import forms
from decimal import Decimal
import datetime
from .models import Physician, Clinic, TimeOffRequest, CoverageAssignment, PhysicianAvailability, OnCallSchedule, ClinicSchedule


class WeeklyScheduleForm(forms.Form):
    """Weekly clinic grid for one NROC/PSA physician.

    One clinic dropdown per (weekday, half-day) slot — 5 days x AM/PM. Leaving
    a slot blank means the physician is not scheduled at any clinic then.
    Saving replaces the physician's entire weekly schedule and keeps the
    legacy Clinic.regular_physicians affiliation in sync.
    """

    def __init__(self, *args, physician=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.physician = physician
        clinics = Clinic.objects.filter(is_active=True).order_by('name')
        for day, _day_name in ClinicSchedule.DAY_CHOICES:
            for session, _session_name in ClinicSchedule.SESSION_CHOICES:
                self.fields[f'd{day}_{session}'] = forms.ModelChoiceField(
                    queryset=clinics, required=False,
                    empty_label='— Not scheduled —',
                    widget=forms.Select(attrs={'class': 'form-control'}),
                )
        if physician is not None and not self.is_bound:
            for row in physician.clinic_schedule.all():
                field = self.fields.get(f'd{row.day_of_week}_{row.session}')
                if field is not None:
                    field.initial = row.clinic_id

    def day_rows(self):
        """[(day_name, am_field, pm_field)] for rendering the grid."""
        return [
            (day_name, self[f'd{day}_am'], self[f'd{day}_pm'])
            for day, day_name in ClinicSchedule.DAY_CHOICES
        ]

    def save(self):
        ClinicSchedule.objects.filter(physician=self.physician).delete()
        rows = []
        for day, _ in ClinicSchedule.DAY_CHOICES:
            for session, _ in ClinicSchedule.SESSION_CHOICES:
                clinic = self.cleaned_data.get(f'd{day}_{session}')
                if clinic:
                    rows.append(ClinicSchedule(
                        physician=self.physician, clinic=clinic,
                        day_of_week=day, session=session,
                    ))
        ClinicSchedule.objects.bulk_create(rows)
        # Keep the legacy "assigned clinics" affiliation in sync so existing
        # views (physician list, time-off assignment, clinic form) stay correct.
        self.physician.assigned_clinics.set({r.clinic for r in rows})
        return rows


class PhysicianForm(forms.ModelForm):
    class Meta:
        model = Physician
        fields = ['first_name', 'last_name', 'email',  'physician_type',
                  'total_vacation_days','total_cme_days', 'hourly_rate', 'agency',
                  'availability_notes', 'is_active']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            
            'physician_type': forms.Select(attrs={'class': 'form-control'}),
            'total_vacation_days': forms.NumberInput(attrs={'class': 'form-control'}),
            'total_cme_days': forms.NumberInput(attrs={'class': 'form-control'}),
            'hourly_rate': forms.NumberInput(attrs={
                'class': 'form-control', 'step': '10.00',
                'placeholder': '340.00',
            }),
            
            'agency': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. CompHealth, Weatherby'}),
            'availability_notes': forms.Textarea(attrs={
                'class': 'form-control', 'rows': 2,
                'placeholder': 'e.g. Out until October — maternity leave',
            }),
        }


class ClinicForm(forms.ModelForm):
    class Meta:
        model = Clinic
        fields = ['name', 'location',  'regular_physicians', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'location': forms.TextInput(attrs={'class': 'form-control'}),
            
            'regular_physicians': forms.CheckboxSelectMultiple(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['regular_physicians'].queryset = Physician.objects.filter(
            is_active=True, physician_type__in=['regular', 'psa']
        ).order_by('physician_type', 'last_name', 'first_name')
        self.fields['regular_physicians'].label = 'Assigned Physicians'
        self.fields['regular_physicians'].help_text = 'Select regular and/or PSA physicians for this clinic.'


class TimeOffRequestForm(forms.ModelForm):
    class Meta:
        model = TimeOffRequest
        fields = ['physician', 'start_date', 'end_date', 'request_type', 'status', 'notes']
        widgets = {
            'physician': forms.Select(attrs={'class': 'form-control'}),
            'start_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'end_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'request_type': forms.Select(attrs={'class': 'form-control'}),
            'status': forms.Select(attrs={'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['physician'].queryset = Physician.objects.filter(
            is_active=True,  physician_type__in=['regular', 'psa']
        )

    def clean(self):
        cleaned_data = super().clean()
        start = cleaned_data.get('start_date')
        end = cleaned_data.get('end_date')
        if start and end and end < start:
            raise forms.ValidationError('End date must be on or after start date.')
        return cleaned_data


class CoverageAssignmentForm(forms.ModelForm):
    class Meta:
        model = CoverageAssignment
        fields = ['clinic', 'covering_physician', 'covered_physician', 'date', 'hours', 'hourly_rate_override', 'notes']
        widgets = {
            'clinic': forms.Select(attrs={'class': 'form-control'}),
            'covering_physician': forms.Select(attrs={'class': 'form-control'}),
            'covered_physician': forms.Select(attrs={'class': 'form-control'}),
            'date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'hours': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.25', 'min': '0', 'placeholder': '8.00'}),
            'hourly_rate_override': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': 'Leave blank to use standard hourly rate'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    # ── Optional weekly repeat ─────────────────────────────────────────────
    # For a locum who routinely works a clinic a couple of days a week (not
    # standing in for anyone), tick the weekdays (and optionally an end date): one
    # CoverageAssignment row is created per matching workday, so the days
    # show on the clinics page/calendar and count toward Locum Costs.
    REPEAT_DAY_CHOICES = [
        (0, 'Mon'), (1, 'Tue'), (2, 'Wed'), (3, 'Thu'), (4, 'Fri'),
    ]
    # A repeat with no end date is treated as open-ended: rows are generated
    # this far ahead of the start date. Submit again later (from any date) to
    # extend — days already assigned are skipped, so nothing is duplicated.
    OPEN_ENDED_YEARS = 2

    repeat_days = forms.TypedMultipleChoiceField(
        choices=REPEAT_DAY_CHOICES, coerce=int, required=False,
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'repeat-days'}),
        label='Repeat weekly on',
        help_text=('Optional. Tick the weekdays this locum routinely works this '
                   'clinic; one assignment is created for every matching workday '
                   'from the date above onward (holidays and days already assigned '
                   'are skipped). Leave unticked for a single day.'),
    )
    repeat_until = forms.DateField(
        required=False, label='Repeat until',
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        help_text=('Optional last date of the repeat (inclusive). Leave blank for an '
                   'open-ended repeat — days are scheduled two years ahead, and you '
                   'can end it any time with "End routine" on the Clinics page.'),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['covering_physician'].queryset = Physician.objects.filter(
            is_active=True, physician_type='locum'
        )
        self.fields['covered_physician'].queryset = Physician.objects.filter(
            is_active=True, physician_type='regular'
        )
        self.fields['covered_physician'].required = False
        self.fields['covered_physician'].help_text = (
            'Leave blank when the locum is routinely covering the clinic rather '
            'than standing in for a specific physician.')
        self.fields['hours'].initial = Decimal('8.00')

    def clean_hours(self):
        """Never save a NULL/negative hours value — fall back to a standard 8-hour day."""
        hours = self.cleaned_data.get('hours')
        if hours is None or hours < 0:
            return Decimal('8.00')
        return hours

    def clean(self):
        cleaned = super().clean()
        days = cleaned.get('repeat_days') or []
        until = cleaned.get('repeat_until')
        start = cleaned.get('date')
        if until and not days:
            self.add_error('repeat_days', 'Tick at least one weekday to repeat, or clear the end date.')
        if days and until and start and until < start:
            self.add_error('repeat_until', 'End date must be on or after the start date.')
        return cleaned

    def _get_validation_exclusions(self):
        # In repeat mode the view skips dates already assigned, so an existing
        # row on the start date is not an error the way it is for a single
        # day. Excluding `date` from model validation makes Django skip the
        # (clinic, covering_physician, date) unique constraint; the form's own
        # DateField has already validated the value.
        exclude = super()._get_validation_exclusions()
        if self.is_repeat:
            exclude.add('date')
        return exclude

    @property
    def is_repeat(self):
        return bool(self.cleaned_data.get('repeat_days'))

    @property
    def is_open_ended(self):
        return self.is_repeat and not self.cleaned_data.get('repeat_until')

    def repeat_end(self):
        """The last date rows are generated for: the given end date, or
        OPEN_ENDED_YEARS after the start when none was given."""
        until = self.cleaned_data.get('repeat_until')
        if until:
            return until
        start = self.cleaned_data['date']
        try:
            return start.replace(year=start.year + self.OPEN_ENDED_YEARS)
        except ValueError:            # Feb 29 -> Feb 28
            return start.replace(year=start.year + self.OPEN_ENDED_YEARS, day=28)

    def repeat_dates(self):
        """Every workday from `date` through `repeat_end()` on a ticked weekday
        (holidays excluded), oldest first. Empty when not repeating."""
        from .models import get_holidays, get_extra_workdays, is_workday
        if not self.is_repeat:
            return []
        start = self.cleaned_data['date']
        until = self.repeat_end()
        weekdays = set(self.cleaned_data['repeat_days'])
        holidays, extra = set(), set()
        for y in range(start.year, until.year + 1):
            holidays |= set(get_holidays(y))
            extra |= get_extra_workdays(y)
        out, d = [], start
        while d <= until:
            if d.weekday() in weekdays and is_workday(d, holidays, extra):
                out.append(d)
            d += datetime.timedelta(days=1)
        return out


class PhysicianAvailabilityForm(forms.ModelForm):
    class Meta:
        model = PhysicianAvailability
        fields = ['physician', 'date', 'is_available', 'notes']
        widgets = {
            'physician': forms.Select(attrs={'class': 'form-control'}),
            'date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['physician'].queryset = Physician.objects.filter(
            is_active=True, physician_type='locum'
        )

class OnCallScheduleForm(forms.ModelForm):
    """Form for adding/editing a weekend on-call assignment.

    The `weekend_start_date` field must be a Monday — enforced both
    client-side (the date input is wired to snap to Mondays in JS) and
    server-side (model `clean()`).
    """

    class Meta:
        model = OnCallSchedule
        fields = ['group', 'weekend_start_date', 'physician', 'notes']
        labels = {
            'weekend_start_date': 'Monday (start of week)',
        }
        widgets = {
            'group': forms.Select(attrs={'class': 'form-control', 'id': 'id_oncall_group'}),
            'weekend_start_date': forms.DateInput(attrs={
                'class': 'form-control', 'type': 'date', 'id': 'id_weekend_start_date',
            }),
            'physician': forms.Select(attrs={'class': 'form-control', 'id': 'id_oncall_physician'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        # Allow caller to pre-restrict by group (e.g. "Add NROC on-call" page)
        group = kwargs.pop('group', None)

        weekend_start_date = kwargs.pop('weekend_start_date', None)
        super().__init__(*args, **kwargs)

        # Both NROC and PSA physicians loaded; template JS narrows by group
        qs = Physician.objects.filter(
            is_active=True, physician_type__in=['regular', 'psa']
        ).order_by('physician_type', 'last_name', 'first_name')
        self.fields['physician'].queryset = qs

        self.fields['physician'].widget.choices = [
            ('', '---------'),
        ] + [
            (p.pk, f"Dr. {p.first_name} {p.last_name} ({'NROC' if p.is_regular else 'PSA'})")
            for p in qs
        ]

        if group:
            self.fields['group'].initial = group

        if weekend_start_date:
            self.fields['weekend_start_date'].initial = weekend_start_date

    # AFTER (clean() with new duplicate-detection block, plus new _post_clean())
    def clean(self):
        cleaned = super().clean()
        group = cleaned.get('group')
        physician = cleaned.get('physician')
        weekend_start = cleaned.get('weekend_start_date')

        # Saturday check (Python: Monday=0 .. Saturday=5, Sunday=6)
        if weekend_start is not None and weekend_start.weekday() != 0:
            self.add_error(
                'weekend_start_date',
                'Please pick a Monday — the shift runs Mon through Sun.'
            )

        if group and physician:
            if group == 'nroc' and not physician.is_regular:
                self.add_error('physician', 'Selected physician is not an NROC physician.')
            elif group == 'psa' and not physician.is_psa:
                self.add_error('physician', 'Selected physician is not a PSA physician.')

        # Friendly duplicate check — runs BEFORE the model-level constraint
        # validation so we can give a specific, actionable message instead of
        # Django's generic "already exists" wording.
        if group and physician and weekend_start:
            qs = OnCallSchedule.objects.filter(
                group=group,
                weekend_start_date=weekend_start,
                physician=physician,
            )
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                group_label = dict(OnCallSchedule.GROUP_CHOICES).get(group, group)
                # Mark so _post_clean knows to suppress Django's duplicate
                # message (we already added a friendlier one).
                self._duplicate_caught = True
                self.add_error(
                    None,
                    f"Dr. {physician.first_name} {physician.last_name} is already "
                    f"scheduled for {group_label} on-call the weekend of "
                    f"{weekend_start:%b %d, %Y}. Pick a different physician or "
                    f"weekend, or edit the existing assignment from the "
                    f"schedule page."
                )

        return cleaned

    def _post_clean(self):
        """Run Django's normal post-clean, but if we already caught a
        duplicate in clean(), strip out Django's generic "already exists"
        message so the user only sees our friendlier one.
        """
        super()._post_clean()
        if getattr(self, '_duplicate_caught', False):
            # Remove Django's default unique-constraint error from __all__,
            # which would otherwise show as a second, redundant red banner.
            generic_msg_prefix = "On call schedule with this"
            non_field = self._errors.get('__all__')
            if non_field:
                self._errors['__all__'] = self.error_class(
                    [m for m in non_field if not str(m).startswith(generic_msg_prefix)]
                )
                if not self._errors['__all__']:
                    del self._errors['__all__']