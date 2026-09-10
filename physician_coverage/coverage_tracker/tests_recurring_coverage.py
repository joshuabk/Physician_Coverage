"""Routine weekly locum coverage from the Assign Locum Coverage form.

A locum who works a clinic a couple of days a week (not standing in for a
specific physician) is recorded as one CoverageAssignment per matching
workday, so the days appear on the clinics page / calendar and count toward
Locum Costs. Locums are never assigned via the Edit Clinic page and never
have time-off requests.
"""
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings

from .forms import ClinicForm, CoverageAssignmentForm, TimeOffRequestForm
from .models import Clinic, CoverageAssignment, Physician, UserProfile


@override_settings(SEND_NOTIFICATION_EMAILS=False,
                   EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
                   TIME_OFF_NOTIFICATION_RECIPIENTS=['group@t.org'])
class RecurringCoverageTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.locum = Physician.objects.create(
            first_name='Lou', last_name='Cummings', email='lou@t.org',
            physician_type='locum', hourly_rate=Decimal('300'))
        cls.nroc = Physician.objects.create(
            first_name='Nora', last_name='Regular', email='nora@t.org',
            physician_type='regular')
        cls.clinic = Clinic.objects.create(name='East Clinic')
        cls.admin = User.objects.create_user('admin', password='pw', is_superuser=True)
        UserProfile.objects.create(user=cls.admin, role='admin', scope='all')

    def setUp(self):
        self.client.login(username='admin', password='pw')

    def _post(self, **extra):
        data = {
            'clinic': self.clinic.pk, 'covering_physician': self.locum.pk,
            'covered_physician': '', 'date': '2026-10-05',  # a Monday
            'hours': '8', 'hourly_rate_override': '', 'notes': 'routine',
        }
        follow = extra.pop('follow', False)
        data.update(extra)
        return self.client.post('/coverage/add/', data, follow=follow)

    # -- single day still works exactly as before ----------------------------
    def test_single_day_unchanged(self):
        r = self._post()
        self.assertRedirects(r, '/clinics/', fetch_redirect_response=False)
        self.assertEqual(CoverageAssignment.objects.count(), 1)
        a = CoverageAssignment.objects.get()
        self.assertEqual(a.date, date(2026, 10, 5))
        self.assertIsNone(a.covered_physician)
        self.assertEqual(len(mail.outbox), 1)

    # -- repeat ----------------------------------------------------------------
    def test_repeat_mon_wed_for_four_weeks(self):
        r = self._post(repeat_days=[0, 2], repeat_until='2026-10-30')
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r['Location'], '/clinics/?date=2026-10-05')
        dates = list(CoverageAssignment.objects.order_by('date').values_list('date', flat=True))
        self.assertEqual(dates, [
            date(2026, 10, 5), date(2026, 10, 7), date(2026, 10, 12), date(2026, 10, 14),
            date(2026, 10, 19), date(2026, 10, 21), date(2026, 10, 26), date(2026, 10, 28),
        ])
        for a in CoverageAssignment.objects.all():
            self.assertEqual(a.clinic, self.clinic)
            self.assertEqual(a.covering_physician, self.locum)
            self.assertIsNone(a.covered_physician)
            self.assertEqual(a.hours, Decimal('8'))
            self.assertEqual(a.notes, 'routine')
        # ONE summary email for the whole run
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Oct 05', mail.outbox[0].body)
        self.assertIn('Oct 28', mail.outbox[0].body)

    def test_repeat_skips_holidays(self):
        # Thanksgiving 2026 is Thu Nov 26; Christmas is Fri Dec 25.
        self._post(date='2026-11-23', repeat_days=[3, 4], repeat_until='2026-12-25')
        dates = set(CoverageAssignment.objects.values_list('date', flat=True))
        self.assertNotIn(date(2026, 11, 26), dates)
        self.assertNotIn(date(2026, 12, 25), dates)
        self.assertIn(date(2026, 11, 27), dates)   # day after Thanksgiving is a workday
        self.assertIn(date(2026, 12, 24), dates)

    def test_repeat_skips_days_already_assigned(self):
        CoverageAssignment.objects.create(
            clinic=self.clinic, covering_physician=self.locum,
            date=date(2026, 10, 12), hours=Decimal('4'), notes='pre-existing')
        r = self._post(repeat_days=[0], repeat_until='2026-10-26', follow=True)
        self.assertEqual(CoverageAssignment.objects.count(), 4)  # 5, 12(existing), 19, 26
        kept = CoverageAssignment.objects.get(date=date(2026, 10, 12))
        self.assertEqual(kept.hours, Decimal('4'))
        self.assertEqual(kept.notes, 'pre-existing')
        self.assertContains(r, '3 coverage day(s) added')
        self.assertContains(r, '1 day(s) already assigned were skipped')

    def test_repeat_with_nothing_new_saves_nothing_and_emails_nothing(self):
        CoverageAssignment.objects.create(
            clinic=self.clinic, covering_physician=self.locum, date=date(2026, 10, 5))
        r = self._post(repeat_days=[0], repeat_until='2026-10-05', follow=True)
        self.assertEqual(CoverageAssignment.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 0)
        self.assertContains(r, 'No new coverage days')

    def test_repeat_can_also_cover_a_named_physician(self):
        self._post(covered_physician=self.nroc.pk, repeat_days=[1], repeat_until='2026-10-13')
        self.assertEqual(CoverageAssignment.objects.count(), 2)
        self.assertTrue(all(a.covered_physician == self.nroc
                            for a in CoverageAssignment.objects.all()))

    def test_repeat_days_show_on_clinics_page_as_additional_coverage(self):
        self._post(repeat_days=[0], repeat_until='2026-10-12')
        r = self.client.get('/clinics/?date=2026-10-12')
        self.assertContains(r, 'Additional Coverage')
        self.assertContains(r, 'Dr. Lou Cummings')
        self.assertNotContains(r, 'Coverage needed')

    def test_repeat_days_count_toward_locum_costs(self):
        self._post(repeat_days=[0, 2], repeat_until='2026-10-30')  # 8 days x 8h x $300
        self.assertEqual(self.locum.total_coverage_hours(2026), Decimal('64'))
        self.assertEqual(self.locum.total_coverage_cost(2026), Decimal('19200'))

    # -- validation -----------------------------------------------------------
    def test_days_without_end_date_is_open_ended_two_years(self):
        r = self._post(repeat_days=[0], follow=True)   # Mondays from 2026-10-05, no end
        dates = list(CoverageAssignment.objects.order_by('date').values_list('date', flat=True))
        self.assertEqual(dates[0], date(2026, 10, 5))
        self.assertEqual(dates[-1], date(2028, 10, 2))       # last Monday <= 2028-10-05
        self.assertTrue(all(d.weekday() == 0 for d in dates))
        self.assertGreater(len(dates), 100)                  # ~104 Mondays minus holidays
        self.assertContains(r, 'Open-ended')
        self.assertEqual(len(mail.outbox), 1)

    def test_open_ended_resubmit_extends_without_duplicates(self):
        self._post(repeat_days=[0])
        n = CoverageAssignment.objects.count()
        self._post(date='2028-09-04', repeat_days=[0])       # overlaps the tail, then extends
        dates = list(CoverageAssignment.objects.order_by('date').values_list('date', flat=True))
        self.assertEqual(len(dates), len(set(dates)))        # no duplicate days
        self.assertGreater(len(dates), n)
        # 2030-09-02 is Labor Day (skipped), so the last Monday is Aug 26
        self.assertEqual(dates[-1], date(2030, 8, 26))

    def test_end_date_without_days_is_an_error(self):
        r = self._post(repeat_until='2026-10-30')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Tick at least one weekday')
        self.assertEqual(CoverageAssignment.objects.count(), 0)

    def test_end_before_start_is_an_error(self):
        r = self._post(repeat_days=[0], repeat_until='2026-10-01')
        self.assertContains(r, 'on or after the start date')
        self.assertEqual(CoverageAssignment.objects.count(), 0)

    def test_repeat_can_span_several_years(self):
        r = self._post(repeat_days=[0], repeat_until='2029-10-01')
        self.assertEqual(r.status_code, 302)
        dates = list(CoverageAssignment.objects.order_by('date').values_list('date', flat=True))
        self.assertEqual(dates[-1], date(2029, 10, 1))
        self.assertGreater(len(dates), 140)                  # ~157 Mondays minus holidays

    def test_form_renders_repeat_fields(self):
        r = self.client.get('/coverage/add/')
        self.assertContains(r, 'Repeat weekly on')
        self.assertContains(r, 'id_repeat_days_0')
        self.assertContains(r, 'id_repeat_until')

    def test_repeat_dates_helper(self):
        f = CoverageAssignmentForm({
            'clinic': self.clinic.pk, 'covering_physician': self.locum.pk,
            'date': '2026-10-05', 'hours': '8', 'repeat_days': [0, 4],
            'repeat_until': '2026-10-16'})
        self.assertTrue(f.is_valid(), f.errors)
        self.assertEqual(f.repeat_dates(), [
            date(2026, 10, 5), date(2026, 10, 9), date(2026, 10, 12), date(2026, 10, 16)])


class LocumsStayOutOfClinicAndTimeOffFormsTests(TestCase):
    """Locums are placed at clinics only through coverage assignments."""

    def setUp(self):
        self.locum = Physician.objects.create(
            first_name='Lou', last_name='Cummings', email='lou@t.org', physician_type='locum')

    def test_clinic_form_excludes_locums(self):
        self.assertNotIn(self.locum, ClinicForm().fields['regular_physicians'].queryset)

    def test_time_off_form_excludes_locums(self):
        self.assertNotIn(self.locum, TimeOffRequestForm().fields['physician'].queryset)


class EndRoutineCoverageTests(TestCase):
    """The "End routine" button on the clinics page."""

    def setUp(self):
        self.locum = Physician.objects.create(
            first_name='Lou', last_name='Cummings', email='lou@t.org',
            physician_type='locum', hourly_rate=Decimal('300'))
        self.other_locum = Physician.objects.create(
            first_name='Ann', last_name='Other', email='ann@t.org', physician_type='locum')
        self.nroc = Physician.objects.create(
            first_name='Nora', last_name='Regular', email='nora@t.org', physician_type='regular')
        self.clinic = Clinic.objects.create(name='East Clinic')
        self.clinic_b = Clinic.objects.create(name='West Clinic')
        admin = User.objects.create_user('admin', password='pw', is_superuser=True)
        UserProfile.objects.create(user=admin, role='admin', scope='all')
        self.client.login(username='admin', password='pw')

        def mk(d, **kw):
            base = dict(clinic=self.clinic, covering_physician=self.locum, hours=Decimal('8'))
            base.update(kw)
            return CoverageAssignment.objects.create(date=d, **base)

        # Lou's routine Mondays at East: Sep 28, Oct 5, 12, 19, 26
        for d in (date(2026, 9, 28), date(2026, 10, 5), date(2026, 10, 12),
                  date(2026, 10, 19), date(2026, 10, 26)):
            mk(d)
        self.kept_timeoff = mk(date(2026, 10, 14), covered_physician=self.nroc)   # covering Nora
        self.kept_other_clinic = mk(date(2026, 10, 19), clinic=self.clinic_b)     # West, routine
        self.kept_other_locum = mk(date(2026, 10, 19), covering_physician=self.other_locum)

    def _end(self, when='2026-10-12', **extra):
        data = {'clinic': self.clinic.pk, 'locum': self.locum.pk, 'date': when}
        data.update(extra)
        return self.client.post('/coverage/end-routine/', data, follow=True)

    def test_removes_that_day_and_later_routine_days_only(self):
        r = self._end('2026-10-12')
        remaining = set(CoverageAssignment.objects.filter(
            clinic=self.clinic, covering_physician=self.locum,
            covered_physician__isnull=True).values_list('date', flat=True))
        self.assertEqual(remaining, {date(2026, 9, 28), date(2026, 10, 5)})   # past days kept
        # untouched: time-off coverage, other clinic, other locum
        for a in (self.kept_timeoff, self.kept_other_clinic, self.kept_other_locum):
            self.assertTrue(CoverageAssignment.objects.filter(pk=a.pk).exists())
        self.assertContains(r, 'removed 3 day(s)')
        self.assertContains(r, 'Oct 12 through Oct 26, 2026')
        self.assertEqual(r.request['PATH_INFO'], '/clinics/')
        self.assertEqual(r.request['QUERY_STRING'], 'date=2026-10-12')

    def test_nothing_to_remove_is_a_friendly_message(self):
        r = self._end('2026-11-02')
        self.assertContains(r, 'No routine coverage days')
        self.assertEqual(CoverageAssignment.objects.count(), 8)

    def test_invalid_input_is_rejected(self):
        self._end('not-a-date')
        self._end(locum=self.nroc.pk)   # not a locum
        self._end(clinic=9999)
        self.assertEqual(CoverageAssignment.objects.count(), 8)

    def test_get_and_non_admin_are_refused(self):
        self.assertEqual(self.client.get('/coverage/end-routine/').status_code, 302)
        nurse = User.objects.create_user('nurse', password='pw')
        UserProfile.objects.create(user=nurse, role='nursing', scope='all')
        self.client.login(username='nurse', password='pw')
        self._end('2026-10-12')
        self.assertEqual(CoverageAssignment.objects.count(), 8)

    def test_button_shows_only_for_routine_rows(self):
        r = self.client.get('/clinics/?date=2026-10-12')
        self.assertContains(r, 'End routine')
        self.assertContains(r, 'routine clinic day')
        r = self.client.get('/clinics/?date=2026-10-14')   # only the time-off coverage row
        self.assertNotContains(r, 'End routine')
        self.assertContains(r, 'covering Dr. Nora Regular')
