"""Comprehensive functional tests for the physician coverage app."""
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase, Client

from .models import (
    Physician, Clinic, TimeOffRequest, CoverageAssignment,
    PhysicianAvailability, CoverageRequest, OnCallSchedule, UserProfile,
    get_holidays, get_extra_workdays, is_workday,
)

YEAR = 2026


def make_user(username, role='admin', scope='all', physician=None, superuser=False):
    if superuser:
        u = User.objects.create_superuser(username, f'{username}@x.com', 'pw12345!')
    else:
        u = User.objects.create_user(username, f'{username}@x.com', 'pw12345!')
    UserProfile.objects.create(user=u, role=role, scope=scope, physician=physician)
    return u


class HolidayWorkdayTests(TestCase):
    def test_holidays_2026(self):
        h = get_holidays(2026)
        self.assertIn(date(2026, 1, 1), h)      # New Year's
        self.assertIn(date(2026, 7, 4), h)      # July 4
        self.assertIn(date(2026, 12, 25), h)    # Christmas
        self.assertIn(date(2026, 5, 25), h)     # Memorial Day (last Mon of May)
        self.assertIn(date(2026, 9, 7), h)      # Labor Day (1st Mon of Sep)
        self.assertIn(date(2026, 11, 26), h)    # Thanksgiving (4th Thu of Nov)
        self.assertEqual(len(h), 6)

    def test_sunday_before_thanksgiving_is_extra_workday(self):
        extra = get_extra_workdays(2026)
        self.assertIn(date(2026, 11, 22), extra)  # Sunday before Thanksgiving
        self.assertTrue(is_workday(date(2026, 11, 22),
                                   set(get_holidays(2026)), extra))

    def test_weekend_not_workday_holiday_not_workday(self):
        h, e = set(get_holidays(2026)), get_extra_workdays(2026)
        self.assertFalse(is_workday(date(2026, 7, 11), h, e))  # Saturday
        self.assertFalse(is_workday(date(2026, 12, 25), h, e))  # Christmas (Friday)
        self.assertTrue(is_workday(date(2026, 7, 8), h, e))    # Wednesday


class VacationAndCmePoolTests(TestCase):
    def setUp(self):
        self.p = Physician.objects.create(
            first_name='Alice', last_name='Reed', email='ar@x.com',
            physician_type='regular', total_vacation_days=20)

    def _req(self, rtype, start, end, status='approved'):
        return TimeOffRequest.objects.create(
            physician=self.p, request_type=rtype, status=status,
            start_date=start, end_date=end)

    def test_defaults(self):
        self.assertEqual(self.p.total_vacation_days, 20)
        self.assertEqual(self.p.total_cme_days, 5)  # new default

    def test_vacation_draws_pool(self):
        # Mon Aug 3 - Fri Aug 7 2026 = 5 business days
        self._req('vacation', date(2026, 8, 3), date(2026, 8, 7))
        self.assertEqual(self.p.days_taken(YEAR), 5)
        self.assertEqual(self.p.days_remaining(YEAR), 15)

    def test_sick_draws_vacation_pool(self):
        self._req('sick', date(2026, 8, 12), date(2026, 8, 13))  # Wed-Thu = 2
        self.assertEqual(self.p.days_taken(YEAR), 2)
        self.assertEqual(self.p.days_remaining(YEAR), 18)

    def test_vacation_plus_sick_combined(self):
        self._req('vacation', date(2026, 8, 3), date(2026, 8, 7))   # 5
        self._req('sick', date(2026, 8, 12), date(2026, 8, 12))     # 1
        self.assertEqual(self.p.days_taken(YEAR), 6)
        self.assertEqual(self.p.days_remaining(YEAR), 14)

    def test_cme_has_own_pool_and_does_not_touch_vacation(self):
        self._req('conference', date(2026, 9, 14), date(2026, 9, 16))  # Mon-Wed = 3
        self.assertEqual(self.p.cme_days_taken(YEAR), 3)
        self.assertEqual(self.p.cme_days_remaining(YEAR), 2)
        self.assertEqual(self.p.days_taken(YEAR), 0)          # vacation untouched
        self.assertEqual(self.p.days_remaining(YEAR), 20)

    def test_sick_does_not_touch_cme(self):
        self._req('sick', date(2026, 8, 12), date(2026, 8, 12))
        self.assertEqual(self.p.cme_days_taken(YEAR), 0)
        self.assertEqual(self.p.cme_days_remaining(YEAR), 5)

    def test_personal_and_other_draw_nothing(self):
        self._req('personal', date(2026, 8, 3), date(2026, 8, 4))
        self._req('other', date(2026, 8, 5), date(2026, 8, 6))
        self.assertEqual(self.p.days_taken(YEAR), 0)
        self.assertEqual(self.p.cme_days_taken(YEAR), 0)

    def test_pending_counts_separately(self):
        self._req('vacation', date(2026, 8, 3), date(2026, 8, 4), status='pending')
        self._req('sick', date(2026, 8, 5), date(2026, 8, 5), status='pending')
        self._req('conference', date(2026, 8, 6), date(2026, 8, 7), status='pending')
        self.assertEqual(self.p.days_pending(YEAR), 3)       # vac 2 + sick 1
        self.assertEqual(self.p.cme_days_pending(YEAR), 2)
        self.assertEqual(self.p.days_taken(YEAR), 0)          # nothing approved

    def test_denied_and_cancelled_draw_nothing(self):
        self._req('vacation', date(2026, 8, 3), date(2026, 8, 7), status='denied')
        self._req('sick', date(2026, 8, 10), date(2026, 8, 11), status='cancelled')
        self.assertEqual(self.p.days_taken(YEAR), 0)
        self.assertEqual(self.p.days_pending(YEAR), 0)

    def test_year_scoping(self):
        self._req('vacation', date(2025, 8, 4), date(2025, 8, 8))
        self.assertEqual(self.p.days_taken(2026), 0)
        self.assertEqual(self.p.days_taken(2025), 5)

    def test_duration_skips_weekend_and_holiday(self):
        # Wed Jul 1 - Tue Jul 7 2026: Jul 4 is Saturday; Fri Jul 3 IS counted
        # (only actual holiday dates excluded). Business days: 1,2,3,6,7 = 5
        r = self._req('vacation', date(2026, 7, 1), date(2026, 7, 7))
        self.assertEqual(r.duration_days, 5)

    def test_duration_spans_year_boundary(self):
        # Mon Dec 28 2026 - Fri Jan 1 2027; Jan 1 is a holiday -> 4 days
        r = self._req('vacation', date(2026, 12, 28), date(2027, 1, 1))
        self.assertEqual(r.duration_days, 4)

    def test_thanksgiving_week(self):
        # Sun Nov 22 (extra workday) - Fri Nov 27 2026, Thanksgiving Nov 26 off
        # Workdays: Sun 22, Mon 23, Tue 24, Wed 25, Fri 27 = 5
        r = self._req('vacation', date(2026, 11, 22), date(2026, 11, 27))
        self.assertEqual(r.duration_days, 5)


class CoverageCostTests(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(name='Main Clinic')
        self.locum = Physician.objects.create(
            first_name='Lou', last_name='Cummings', email='lc@x.com',
            physician_type='locum', hourly_rate=Decimal('340.00'))
        self.reg = Physician.objects.create(
            first_name='Rita', last_name='Ng', email='rn@x.com',
            physician_type='regular')

    def test_hourly_cost(self):
        a = CoverageAssignment.objects.create(
            clinic=self.clinic, covering_physician=self.locum,
            covered_physician=self.reg, date=date(2026, 8, 3),
            hours=Decimal('8.00'))
        self.assertEqual(a.cost, Decimal('2720.00'))
        self.assertEqual(self.locum.total_coverage_cost(YEAR), Decimal('2720.00'))
        self.assertEqual(self.locum.total_coverage_hours(YEAR), Decimal('8.00'))

    def test_hourly_override_beats_default(self):
        a = CoverageAssignment.objects.create(
            clinic=self.clinic, covering_physician=self.locum,
            date=date(2026, 8, 4), hours=Decimal('4.00'),
            hourly_rate_override=Decimal('400.00'))
        self.assertEqual(a.cost, Decimal('1600.00'))

    def test_no_coverage_needed_costs_zero(self):
        a = CoverageAssignment.objects.create(
            clinic=self.clinic, covered_physician=self.reg,
            date=date(2026, 8, 5), no_coverage_needed=True,
            no_coverage_reason='half day')
        self.assertEqual(a.cost, Decimal('0.00'))
        self.assertEqual(a.effective_hourly_rate, Decimal('0.00'))

    def test_null_hours_is_safe(self):
        a = CoverageAssignment.objects.create(
            clinic=self.clinic, covering_physician=self.locum,
            date=date(2026, 8, 6), hours=None)
        self.assertEqual(a.cost, Decimal('0.00'))

    def test_unique_assignment_constraint(self):
        CoverageAssignment.objects.create(
            clinic=self.clinic, covering_physician=self.locum,
            date=date(2026, 8, 7), hours=Decimal('8'))
        from django.db import IntegrityError, transaction
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CoverageAssignment.objects.create(
                    clinic=self.clinic, covering_physician=self.locum,
                    date=date(2026, 8, 7), hours=Decimal('8'))

    def test_two_no_coverage_rows_different_physicians_ok(self):
        reg2 = Physician.objects.create(
            first_name='Bo', last_name='Ta', email='bt@x.com',
            physician_type='regular')
        CoverageAssignment.objects.create(
            clinic=self.clinic, covered_physician=self.reg,
            date=date(2026, 8, 10), no_coverage_needed=True, no_coverage_reason='x')
        CoverageAssignment.objects.create(
            clinic=self.clinic, covered_physician=reg2,
            date=date(2026, 8, 10), no_coverage_needed=True, no_coverage_reason='y')
        self.assertEqual(CoverageAssignment.objects.filter(
            date=date(2026, 8, 10)).count(), 2)


class OnCallScheduleTests(TestCase):
    def setUp(self):
        self.nroc = Physician.objects.create(
            first_name='N', last_name='Roc', email='nr@x.com',
            physician_type='regular')
        self.psa = Physician.objects.create(
            first_name='P', last_name='Sa', email='ps@x.com',
            physician_type='psa')

    def test_must_start_on_monday(self):
        entry = OnCallSchedule(group='nroc', physician=self.nroc,
                               weekend_start_date=date(2026, 7, 14))  # Tuesday
        with self.assertRaises(ValidationError):
            entry.full_clean()

    def test_group_physician_mismatch_rejected(self):
        entry = OnCallSchedule(group='nroc', physician=self.psa,
                               weekend_start_date=date(2026, 7, 13))  # Monday
        with self.assertRaises(ValidationError):
            entry.full_clean()
        entry2 = OnCallSchedule(group='psa', physician=self.nroc,
                                weekend_start_date=date(2026, 7, 13))
        with self.assertRaises(ValidationError):
            entry2.full_clean()

    def test_valid_entry_and_label(self):
        e = OnCallSchedule.objects.create(
            group='nroc', physician=self.nroc,
            weekend_start_date=date(2026, 7, 13))
        e.full_clean()
        self.assertEqual(e.sunday, date(2026, 7, 19))
        self.assertIn('Jul 13', e.weekend_label)
        self.assertIn('19', e.weekend_label)

    def test_both_groups_can_cover_same_week(self):
        OnCallSchedule.objects.create(group='nroc', physician=self.nroc,
                                      weekend_start_date=date(2026, 7, 13))
        OnCallSchedule.objects.create(group='psa', physician=self.psa,
                                      weekend_start_date=date(2026, 7, 13))
        self.assertEqual(OnCallSchedule.objects.filter(
            weekend_start_date=date(2026, 7, 13)).count(), 2)


class AvailabilityAndCoverageRequestTests(TestCase):
    def setUp(self):
        self.locum = Physician.objects.create(
            first_name='L', last_name='O', email='lo@x.com',
            physician_type='locum')
        self.psa = Physician.objects.create(
            first_name='P', last_name='S', email='psx@x.com',
            physician_type='psa')

    def test_availability_unique_per_day(self):
        PhysicianAvailability.objects.create(
            physician=self.locum, date=date(2026, 8, 3), is_available=True)
        from django.db import IntegrityError, transaction
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PhysicianAvailability.objects.create(
                    physician=self.locum, date=date(2026, 8, 3), is_available=False)

    def test_coverage_request_unique_and_count(self):
        CoverageRequest.objects.create(physician=self.psa,
                                       requested_date=date(2026, 8, 3))
        self.assertEqual(self.psa.requested_coverage_days(YEAR), 1)
        from django.db import IntegrityError, transaction
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CoverageRequest.objects.create(physician=self.psa,
                                               requested_date=date(2026, 8, 3))


class AuthAndPermissionTests(TestCase):
    def setUp(self):
        self.c = Client()
        self.admin = make_user('boss', role='admin', superuser=True)
        self.phys_p = Physician.objects.create(
            first_name='Doc', last_name='Tor', email='dt@x.com',
            physician_type='regular')
        self.phys = make_user('doc', role='physician', scope='nroc',
                              physician=self.phys_p)
        self.nurse = make_user('nurse', role='nursing')
        self.pa = make_user('pa', role='physician_admin', scope='nroc')

    def test_login_page_renders_and_bad_login_rejected(self):
        r = self.c.get('/login/')
        self.assertEqual(r.status_code, 200)
        r = self.c.post('/login/', {'username': 'boss', 'password': 'wrong'})
        self.assertEqual(r.status_code, 200)  # re-renders with error
        r = self.c.post('/login/', {'username': 'boss', 'password': 'pw12345!'})
        self.assertEqual(r.status_code, 302)

    def test_anonymous_redirected_to_login(self):
        for url in ['/', '/physicians/', '/time-off/', '/clinics/', '/users/']:
            r = self.c.get(url)
            self.assertEqual(r.status_code, 302, url)
            self.assertIn('/login/', r.url)

    def test_admin_can_reach_admin_pages(self):
        self.c.force_login(self.admin)
        for url in ['/', '/physicians/?type=regular', '/physicians/?type=locum',
                    '/physicians/?type=psa', '/physicians/add/', '/time-off/',
                    '/time-off/add/', '/time-off/approved-coverage/', '/clinics/',
                    '/clinics/add/', '/locum-costs/', '/availability/', '/users/',
                    '/users/add/', '/on-call/', '/account/password/',
                    '/physicians/psa/coverage-requests/']:
            r = self.c.get(url)
            self.assertEqual(r.status_code, 200, f'{url} -> {r.status_code}')

    def test_physician_blocked_from_admin_pages(self):
        self.c.force_login(self.phys)
        for url in ['/physicians/', '/users/', '/locum-costs/']:
            r = self.c.get(url)
            self.assertEqual(r.status_code, 302, url)

    def test_physician_can_reach_own_pages(self):
        self.c.force_login(self.phys)
        for url in ['/time-off/', '/time-off/add/', '/on-call/']:
            r = self.c.get(url)
            self.assertEqual(r.status_code, 200, url)

    def test_nursing_locked_to_clinics(self):
        self.c.force_login(self.nurse)
        r = self.c.get('/clinics/')
        self.assertEqual(r.status_code, 200)
        for url in ['/', '/time-off/', '/physicians/']:
            r = self.c.get(url, follow=True)
            self.assertEqual(r.request['PATH_INFO'], '/clinics/', url)

    def test_logout(self):
        self.c.force_login(self.admin)
        r = self.c.get('/logout/')
        self.assertEqual(r.status_code, 302)
        r = self.c.get('/')
        self.assertEqual(r.status_code, 302)


class PhysicianCrudViewTests(TestCase):
    def setUp(self):
        self.c = Client()
        self.admin = make_user('boss', role='admin', superuser=True)
        self.c.force_login(self.admin)

    def test_add_regular_physician(self):
        r = self.c.post('/physicians/add/', {
            'first_name': 'New', 'last_name': 'Doc', 'email': 'nd@x.com',
            'physician_type': 'regular', 'total_vacation_days': 22,
            'total_cme_days': 5, 'agency': '', 'is_active': 'on'})
        self.assertEqual(r.status_code, 302)
        p = Physician.objects.get(email='nd@x.com')
        self.assertEqual(p.total_vacation_days, 22)
        self.assertEqual(p.total_cme_days, 5)

    def test_add_locum_with_rate(self):
        r = self.c.post('/physicians/add/', {
            'first_name': 'Loc', 'last_name': 'Um', 'email': 'lu@x.com',
            'physician_type': 'locum', 'total_vacation_days': 0,
            'total_cme_days': 0, 'hourly_rate': '340.00',
            'agency': 'CompHealth', 'is_active': 'on'})
        self.assertEqual(r.status_code, 302)
        p = Physician.objects.get(email='lu@x.com')
        self.assertEqual(p.hourly_rate, Decimal('340.00'))

    def test_edit_physician_cme_allocation(self):
        p = Physician.objects.create(first_name='E', last_name='D',
                                     email='ed@x.com', physician_type='regular')
        r = self.c.post(f'/physicians/{p.pk}/edit/', {
            'first_name': 'E', 'last_name': 'D', 'email': 'ed@x.com',
            'physician_type': 'regular', 'total_vacation_days': 20,
            'total_cme_days': 8, 'agency': '', 'is_active': 'on'})
        self.assertEqual(r.status_code, 302)
        p.refresh_from_db()
        self.assertEqual(p.total_cme_days, 8)

    def test_duplicate_email_rejected(self):
        Physician.objects.create(first_name='A', last_name='B',
                                 email='dup@x.com', physician_type='regular')
        r = self.c.post('/physicians/add/', {
            'first_name': 'C', 'last_name': 'D', 'email': 'dup@x.com',
            'physician_type': 'regular', 'total_vacation_days': 20,
            'total_cme_days': 5, 'is_active': 'on'})
        self.assertEqual(r.status_code, 200)  # form redisplayed with error
        self.assertEqual(Physician.objects.filter(email='dup@x.com').count(), 1)

    def test_detail_page_shows_cme(self):
        p = Physician.objects.create(first_name='Show', last_name='Me',
                                     email='sm@x.com', physician_type='regular')
        TimeOffRequest.objects.create(
            physician=p, request_type='conference', status='approved',
            start_date=date(YEAR, 9, 14), end_date=date(YEAR, 9, 15))
        r = self.c.get(f'/physicians/{p.pk}/?year={YEAR}')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'CME Remaining')
        self.assertEqual(r.context['cme_taken'], 2)
        self.assertEqual(r.context['cme_remaining'], 3)


class TimeOffWorkflowTests(TestCase):
    def setUp(self):
        self.c = Client()
        self.admin = make_user('boss', role='admin', superuser=True)
        self.p = Physician.objects.create(
            first_name='Flow', last_name='Test', email='ft@x.com',
            physician_type='regular')
        self.c.force_login(self.admin)

    def _submit(self, rtype='vacation', start='2026-08-03', end='2026-08-05'):
        return self.c.post('/time-off/add/', {
            'physician': self.p.pk, 'start_date': start, 'end_date': end,
            'request_type': rtype, 'notes': ''})

    def test_submit_creates_pending(self):
        r = self._submit()
        self.assertEqual(r.status_code, 302)
        req = TimeOffRequest.objects.get(physician=self.p)
        self.assertEqual(req.status, 'pending')

    def test_approve_then_pool_updates(self):
        self._submit('sick', '2026-08-12', '2026-08-13')
        req = TimeOffRequest.objects.get(physician=self.p)
        r = self.c.post(f'/time-off/{req.pk}/approve/')
        self.assertEqual(r.status_code, 302)
        req.refresh_from_db()
        self.assertEqual(req.status, 'approved')
        self.assertEqual(self.p.days_taken(YEAR), 2)   # sick hit vacation pool

    def test_deny(self):
        self._submit()
        req = TimeOffRequest.objects.get(physician=self.p)
        self.c.post(f'/time-off/{req.pk}/deny/')
        req.refresh_from_db()
        self.assertEqual(req.status, 'denied')
        self.assertEqual(self.p.days_taken(YEAR), 0)

    def test_cancel(self):
        self._submit()
        req = TimeOffRequest.objects.get(physician=self.p)
        r = self.c.post(f'/time-off/{req.pk}/cancel/')
        self.assertEqual(r.status_code, 302)
        req.refresh_from_db()
        self.assertEqual(req.status, 'cancelled')

    def test_approve_requires_post(self):
        self._submit()
        req = TimeOffRequest.objects.get(physician=self.p)
        self.c.get(f'/time-off/{req.pk}/approve/')
        req.refresh_from_db()
        self.assertEqual(req.status, 'pending')  # GET must not approve

    def test_physician_cannot_approve(self):
        self._submit()
        req = TimeOffRequest.objects.get(physician=self.p)
        phys_user = make_user('docx', role='physician', scope='nroc',
                              physician=self.p)
        c2 = Client()
        c2.force_login(phys_user)
        c2.post(f'/time-off/{req.pk}/approve/')
        req.refresh_from_db()
        self.assertEqual(req.status, 'pending')

    def test_physician_admin_can_approve(self):
        self._submit()
        req = TimeOffRequest.objects.get(physician=self.p)
        pa = make_user('pax', role='physician_admin', scope='nroc')
        c2 = Client()
        c2.force_login(pa)
        c2.post(f'/time-off/{req.pk}/approve/')
        req.refresh_from_db()
        self.assertEqual(req.status, 'approved')

    def test_oncall_conflict_warns_then_acknowledge(self):
        OnCallSchedule.objects.create(group='nroc', physician=self.p,
                                      weekend_start_date=date(2026, 8, 3))
        r = self._submit('vacation', '2026-08-03', '2026-08-05')
        self.assertEqual(r.status_code, 200)  # warning page, not saved
        self.assertEqual(TimeOffRequest.objects.count(), 0)
        r = self.c.post('/time-off/add/', {
            'physician': self.p.pk, 'start_date': '2026-08-03',
            'end_date': '2026-08-05', 'request_type': 'vacation',
            'notes': '', 'acknowledge_oncall': '1'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(TimeOffRequest.objects.count(), 1)

    def test_time_off_list_renders(self):
        self._submit()
        r = self.c.get('/time-off/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Flow')


class DashboardTests(TestCase):
    def setUp(self):
        self.c = Client()
        self.admin = make_user('boss', role='admin', superuser=True)
        self.c.force_login(self.admin)
        self.p = Physician.objects.create(
            first_name='Dash', last_name='Board', email='db@x.com',
            physician_type='regular')

    def test_dashboard_shows_combined_pool_and_cme(self):
        TimeOffRequest.objects.create(
            physician=self.p, request_type='sick', status='approved',
            start_date=date(YEAR, 8, 12), end_date=date(YEAR, 8, 12))
        TimeOffRequest.objects.create(
            physician=self.p, request_type='conference', status='approved',
            start_date=date(YEAR, 9, 14), end_date=date(YEAR, 9, 14))
        r = self.c.get(f'/?year={YEAR}')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'CME Left')
        s = [x for x in r.context['physician_summaries']
             if x['physician'].pk == self.p.pk][0]
        self.assertEqual(s['days_taken'], 1)       # sick counted
        self.assertEqual(s['days_remaining'], 19)
        self.assertEqual(s['cme_remaining'], 4)

    def test_physician_list_shows_cme_column(self):
        r = self.c.get(f'/physicians/?type=regular&year={YEAR}')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'CME')
        s = [x for x in r.context['summaries']
             if x['physician'].pk == self.p.pk][0]
        self.assertEqual(s['cme_total'], 5)


class ClinicAndCoverageViewTests(TestCase):
    def setUp(self):
        self.c = Client()
        self.admin = make_user('boss', role='admin', superuser=True)
        self.c.force_login(self.admin)
        self.clinic = Clinic.objects.create(name='East Clinic')
        self.locum = Physician.objects.create(
            first_name='Cov', last_name='Er', email='ce@x.com',
            physician_type='locum', hourly_rate=Decimal('300'))

    def test_add_clinic(self):
        r = self.c.post('/clinics/add/', {'name': 'West Clinic',
                                          'location': 'West side',
                                          'is_active': 'on'})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(Clinic.objects.filter(name='West Clinic').exists())

    def test_clinic_list_renders(self):
        r = self.c.get('/clinics/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'East Clinic')

    def test_locum_costs_page(self):
        CoverageAssignment.objects.create(
            clinic=self.clinic, covering_physician=self.locum,
            date=date(YEAR, 8, 3), hours=Decimal('8'))
        r = self.c.get(f'/locum-costs/?year={YEAR}')
        self.assertEqual(r.status_code, 200)

    def test_availability_update_json(self):
        import json as _json
        r = self.c.post('/availability/update/',
                        _json.dumps({'physician_id': self.locum.pk,
                                     'date': '2026-08-03',
                                     'status': 'available'}),
                        content_type='application/json')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(PhysicianAvailability.objects.filter(
            physician=self.locum, date=date(2026, 8, 3),
            is_available=True).exists())
        # flip to unavailable
        r = self.c.post('/availability/update/',
                        _json.dumps({'physician_id': self.locum.pk,
                                     'date': '2026-08-03',
                                     'status': 'unavailable'}),
                        content_type='application/json')
        self.assertEqual(r.status_code, 200)
        pa = PhysicianAvailability.objects.get(physician=self.locum,
                                               date=date(2026, 8, 3))
        self.assertFalse(pa.is_available)

    def test_availability_update_rejects_bad_input(self):
        import json as _json
        r = self.c.post('/availability/update/', 'not json',
                        content_type='application/json')
        self.assertEqual(r.status_code, 400)
        r = self.c.post('/availability/update/',
                        _json.dumps({'physician_id': self.locum.pk,
                                     'date': '2026-08-03',
                                     'status': 'assigned'}),
                        content_type='application/json')
        self.assertEqual(r.status_code, 400)


class UserManagementTests(TestCase):
    def setUp(self):
        self.c = Client()
        self.admin = make_user('boss', role='admin', superuser=True)
        self.c.force_login(self.admin)

    def test_add_user(self):
        r = self.c.post('/users/add/', {
            'username': 'newnurse', 'password': 'S3cret!pass',
            'role': 'nursing', 'scope': 'all'})
        self.assertEqual(r.status_code, 302)
        u = User.objects.get(username='newnurse')
        self.assertEqual(u.profile.role, 'nursing')

    def test_user_list_renders(self):
        r = self.c.get('/users/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'boss')

    def test_change_password_flow(self):
        r = self.c.post('/account/password/', {
            'current_password': 'pw12345!', 'new_password': 'N3w!passw0rd',
            'confirm_password': 'N3w!passw0rd'})
        self.assertEqual(r.status_code, 302)
        c2 = Client()
        self.assertTrue(c2.login(username='boss', password='N3w!passw0rd'))

    def test_change_password_wrong_current_rejected(self):
        r = self.c.post('/account/password/', {
            'current_password': 'WRONG', 'new_password': 'N3w!passw0rd',
            'confirm_password': 'N3w!passw0rd'})
        self.assertEqual(r.status_code, 200)  # redisplayed with error
        c2 = Client()
        self.assertTrue(c2.login(username='boss', password='pw12345!'))

    def test_BUG_nonadmin_cannot_change_own_password(self):
        """Documents a bug: change_password is @admin_required, but the
        code comment says 'all logged-in users'. A physician login gets
        redirected away instead of seeing the form."""
        phys = make_user('plainphys', role='physician', scope='nroc')
        c2 = Client()
        c2.force_login(phys)
        r = c2.get('/account/password/')
        self.assertEqual(r.status_code, 302)  # bounced -- cannot change pw


class FiscalYearTests(TestCase):
    """Pools reset every November 1: FY N = Nov 1 (N-1) through Oct 31 (N)."""

    def setUp(self):
        from .models import fiscal_year_for, fiscal_year_range
        self.fy_for = fiscal_year_for
        self.fy_range = fiscal_year_range
        self.p = Physician.objects.create(
            first_name='Fis', last_name='Cal', email='fc@x.com',
            physician_type='regular', total_vacation_days=20)

    def _req(self, rtype, start, end, status='approved'):
        return TimeOffRequest.objects.create(
            physician=self.p, request_type=rtype, status=status,
            start_date=start, end_date=end)

    def test_fiscal_year_label_boundaries(self):
        self.assertEqual(self.fy_for(date(2026, 10, 31)), 2026)  # last day of FY2026
        self.assertEqual(self.fy_for(date(2026, 11, 1)), 2027)   # reset day
        self.assertEqual(self.fy_for(date(2026, 7, 10)), 2026)
        self.assertEqual(self.fy_for(date(2027, 1, 15)), 2027)

    def test_fiscal_year_range(self):
        self.assertEqual(self.fy_range(2027),
                         (date(2026, 11, 1), date(2027, 10, 31)))

    def test_vacation_resets_on_nov_1(self):
        # 3 vacation days in August 2026 -> FY2026
        self._req('vacation', date(2026, 8, 3), date(2026, 8, 5))
        # 2 vacation days in November 2026 -> FY2027 (after the reset)
        self._req('vacation', date(2026, 11, 2), date(2026, 11, 3))
        self.assertEqual(self.p.days_taken(2026), 3)
        self.assertEqual(self.p.days_remaining(2026), 17)
        self.assertEqual(self.p.days_taken(2027), 2)   # only post-reset days
        self.assertEqual(self.p.days_remaining(2027), 18)

    def test_sick_resets_too(self):
        self._req('sick', date(2026, 10, 29), date(2026, 10, 30))  # FY2026
        self._req('sick', date(2026, 11, 2), date(2026, 11, 2))    # FY2027 (Nov 1 is a Sunday; Mon Nov 2 is the first workday)
        self.assertEqual(self.p.days_taken(2026), 2)
        self.assertEqual(self.p.days_taken(2027), 1)

    def test_cme_resets_on_nov_1(self):
        self._req('conference', date(2026, 9, 14), date(2026, 9, 16))  # FY2026: 3
        self._req('conference', date(2026, 11, 2), date(2026, 11, 3))  # FY2027: 2
        self.assertEqual(self.p.cme_days_taken(2026), 3)
        self.assertEqual(self.p.cme_days_remaining(2026), 2)
        self.assertEqual(self.p.cme_days_taken(2027), 2)
        self.assertEqual(self.p.cme_days_remaining(2027), 3)  # fresh 5-day pool

    def test_oct_30_vs_nov_2_split(self):
        self._req('vacation', date(2026, 10, 30), date(2026, 10, 30))  # Fri, FY2026
        self._req('vacation', date(2026, 11, 2), date(2026, 11, 2))    # Mon, FY2027
        self.assertEqual(self.p.days_taken(2026), 1)
        self.assertEqual(self.p.days_taken(2027), 1)

    def test_request_spanning_reset_charges_to_start_fy(self):
        # Wed Oct 28 - Tue Nov 3 2026 spans the reset; whole request charges
        # to FY2026 because it STARTS before Nov 1 (start-date rule).
        r = self._req('vacation', date(2026, 10, 28), date(2026, 11, 3))
        self.assertEqual(r.duration_days, 5)
        self.assertEqual(self.p.days_taken(2026), 5)
        self.assertEqual(self.p.days_taken(2027), 0)

    def test_default_year_is_current_fiscal_year(self):
        from .models import current_fiscal_year
        fy = current_fiscal_year()
        self._req('vacation', date(2026, 8, 3), date(2026, 8, 3))
        # Today is July 2026 -> current FY is 2026, so defaults see the request
        self.assertEqual(fy, 2026)
        self.assertEqual(self.p.days_taken(), 1)
        self.assertEqual(self.p.days_remaining(), 19)

    def test_pending_uses_fiscal_year(self):
        self._req('vacation', date(2026, 11, 2), date(2026, 11, 3),
                  status='pending')
        self.assertEqual(self.p.days_pending(2026), 0)
        self.assertEqual(self.p.days_pending(2027), 2)

    def test_dashboard_defaults_to_fiscal_year(self):
        admin = make_user('fyboss', role='admin', superuser=True)
        c = Client()
        c.force_login(admin)
        r = c.get('/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['year'], 2026)  # FY2026 in July 2026
        self.assertEqual(r.context['fy_start'], date(2025, 11, 1))
        self.assertEqual(r.context['fy_end'], date(2026, 10, 31))
        self.assertContains(r, 'resets Nov 1')

    def test_dashboard_next_fiscal_year_shows_reset_balances(self):
        self._req('vacation', date(2026, 8, 3), date(2026, 8, 7))  # 5d in FY2026
        admin = make_user('fyboss2', role='admin', superuser=True)
        c = Client()
        c.force_login(admin)
        s26 = [x for x in c.get('/?year=2026').context['physician_summaries']
               if x['physician'].pk == self.p.pk][0]
        s27 = [x for x in c.get('/?year=2027').context['physician_summaries']
               if x['physician'].pk == self.p.pk][0]
        self.assertEqual(s26['days_taken'], 5)
        self.assertEqual(s27['days_taken'], 0)          # reset!
        self.assertEqual(s27['days_remaining'], 20)
        self.assertEqual(s27['cme_remaining'], 5)


class ClinicScheduleTests(TestCase):
    """Per-weekday, half-day clinic assignments for NROC/PSA physicians."""

    MONDAY = date(2026, 7, 13)
    TUESDAY = date(2026, 7, 14)

    def setUp(self):
        from .models import ClinicSchedule
        self.ClinicSchedule = ClinicSchedule
        self.clinic_a = Clinic.objects.create(name='Alpharetta')
        self.clinic_b = Clinic.objects.create(name='Buckhead')
        self.nroc = Physician.objects.create(
            first_name='Nina', last_name='Roc', email='nr@x.com',
            physician_type='regular')
        self.psa = Physician.objects.create(
            first_name='Pat', last_name='Sa', email='ps@x.com',
            physician_type='psa')
        self.admin = make_user('schedboss', role='admin', superuser=True)
        self.client_ = Client()
        self.client_.force_login(self.admin)

    def _slot(self, physician, clinic, day, session):
        return self.ClinicSchedule.objects.create(
            physician=physician, clinic=clinic, day_of_week=day, session=session)

    def test_half_day_split_shows_both_clinics(self):
        # Monday: AM at Alpharetta, PM at Buckhead
        self._slot(self.nroc, self.clinic_a, 0, 'am')
        self._slot(self.nroc, self.clinic_b, 0, 'pm')
        r = self.client_.get(f'/clinics/?date={self.MONDAY}')
        data = {item['clinic'].name: item for item in r.context['clinic_data']}
        a_staff = {(s['physician'].pk, s['label']) for s in data['Alpharetta']['staff_today']}
        b_staff = {(s['physician'].pk, s['label']) for s in data['Buckhead']['staff_today']}
        self.assertIn((self.nroc.pk, 'AM'), a_staff)
        self.assertIn((self.nroc.pk, 'PM'), b_staff)

    def test_full_day_label_when_both_sessions_same_clinic(self):
        self._slot(self.psa, self.clinic_a, 0, 'am')
        self._slot(self.psa, self.clinic_a, 0, 'pm')
        r = self.client_.get(f'/clinics/?date={self.MONDAY}')
        data = {item['clinic'].name: item for item in r.context['clinic_data']}
        labels = {s['physician'].pk: s['label'] for s in data['Alpharetta']['staff_today']}
        self.assertEqual(labels[self.psa.pk], 'Full day')

    def test_not_shown_on_unscheduled_day(self):
        self._slot(self.nroc, self.clinic_a, 0, 'am')  # Monday only
        r = self.client_.get(f'/clinics/?date={self.TUESDAY}')
        data = {item['clinic'].name: item for item in r.context['clinic_data']}
        pks = {s['physician'].pk for s in data['Alpharetta']['staff_today']}
        self.assertNotIn(self.nroc.pk, pks)

    def test_out_flag_follows_schedule(self):
        self._slot(self.nroc, self.clinic_a, 0, 'am')
        self._slot(self.nroc, self.clinic_b, 0, 'pm')
        TimeOffRequest.objects.create(
            physician=self.nroc, status='approved', request_type='vacation',
            start_date=self.MONDAY, end_date=self.MONDAY)
        r = self.client_.get(f'/clinics/?date={self.MONDAY}')
        data = {item['clinic'].name: item for item in r.context['clinic_data']}
        # Marked out at both clinics they were scheduled at that day
        self.assertIn(self.nroc, data['Alpharetta']['regular_out'])
        self.assertIn(self.nroc, data['Buckhead']['regular_out'])

    def test_legacy_m2m_fallback_full_day(self):
        # No weekly schedule rows -> legacy clinic affiliation still shows
        self.clinic_a.regular_physicians.add(self.nroc)
        r = self.client_.get(f'/clinics/?date={self.TUESDAY}')
        data = {item['clinic'].name: item for item in r.context['clinic_data']}
        labels = {s['physician'].pk: s['label'] for s in data['Alpharetta']['staff_today']}
        self.assertEqual(labels[self.nroc.pk], 'Full day')

    def test_schedule_supersedes_legacy_m2m(self):
        # Once a physician has any schedule rows, the M2M no longer places
        # them everywhere all week.
        self.clinic_a.regular_physicians.add(self.nroc)
        self._slot(self.nroc, self.clinic_b, 1, 'am')  # Tuesday AM at B only
        r = self.client_.get(f'/clinics/?date={self.TUESDAY}')
        data = {item['clinic'].name: item for item in r.context['clinic_data']}
        a_pks = {s['physician'].pk for s in data['Alpharetta']['staff_today']}
        b_pks = {s['physician'].pk for s in data['Buckhead']['staff_today']}
        self.assertNotIn(self.nroc.pk, a_pks)
        self.assertIn(self.nroc.pk, b_pks)

    def test_unique_constraint_one_clinic_per_half_day(self):
        self._slot(self.nroc, self.clinic_a, 0, 'am')
        with self.assertRaises(IntegrityError):
            self._slot(self.nroc, self.clinic_b, 0, 'am')

    def test_editor_saves_grid_and_syncs_m2m(self):
        r = self.client_.post(f'/physicians/{self.nroc.pk}/schedule/', {
            'd0_am': self.clinic_a.pk,   # Mon AM  -> A
            'd0_pm': self.clinic_b.pk,   # Mon PM  -> B (split day)
            'd1_am': self.clinic_a.pk,   # Tue AM  -> A
            'd1_pm': self.clinic_a.pk,   # Tue PM  -> A (full day)
        })
        self.assertEqual(r.status_code, 302)
        rows = self.ClinicSchedule.objects.filter(physician=self.nroc)
        self.assertEqual(rows.count(), 4)
        self.assertEqual(
            set(self.nroc.assigned_clinics.all()), {self.clinic_a, self.clinic_b})
        # Re-saving replaces the schedule (and re-syncs the M2M)
        r = self.client_.post(f'/physicians/{self.nroc.pk}/schedule/', {
            'd2_am': self.clinic_b.pk,
        })
        self.assertEqual(r.status_code, 302)
        rows = self.ClinicSchedule.objects.filter(physician=self.nroc)
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows.first().day_of_week, 2)
        self.assertEqual(set(self.nroc.assigned_clinics.all()), {self.clinic_b})

    def test_editor_rejects_locums(self):
        locum = Physician.objects.create(
            first_name='Lo', last_name='Cum', email='lc@x.com',
            physician_type='locum')
        r = self.client_.get(f'/physicians/{locum.pk}/schedule/')
        self.assertEqual(r.status_code, 404)

    def test_editor_requires_admin(self):
        phys_user = make_user('plainsched', role='physician', scope='nroc')
        c2 = Client()
        c2.force_login(phys_user)
        r = c2.get(f'/physicians/{self.nroc.pk}/schedule/')
        self.assertEqual(r.status_code, 302)  # bounced

    def test_detail_page_shows_schedule(self):
        self._slot(self.nroc, self.clinic_a, 0, 'am')
        self._slot(self.nroc, self.clinic_b, 0, 'pm')
        r = self.client_.get(f'/physicians/{self.nroc.pk}/')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.context['has_weekly_schedule'])
        monday = r.context['weekly_schedule'][0]
        self.assertEqual(monday['day'], 'Monday')
        self.assertEqual(monday['am'].clinic, self.clinic_a)
        self.assertEqual(monday['pm'].clinic, self.clinic_b)


class DayReassignmentTests(TestCase):
    """One-day manual location overrides for NROC and PSA physicians."""

    MONDAY = date(2026, 7, 13)

    def setUp(self):
        from .models import ClinicSchedule, DayReassignment
        self.ClinicSchedule = ClinicSchedule
        self.DayReassignment = DayReassignment
        self.clinic_a = Clinic.objects.create(name='Alpharetta')
        self.clinic_b = Clinic.objects.create(name='Buckhead')
        self.nroc = Physician.objects.create(
            first_name='Nina', last_name='Roc', email='nr2@x.com',
            physician_type='regular')
        self.psa = Physician.objects.create(
            first_name='Pat', last_name='Sa', email='ps2@x.com',
            physician_type='psa')
        # NROC works Mondays full day at A (weekly schedule)
        for session in ('am', 'pm'):
            self.ClinicSchedule.objects.create(
                physician=self.nroc, clinic=self.clinic_a,
                day_of_week=0, session=session)
        # PSA has only a legacy affiliation with A
        self.clinic_a.regular_physicians.add(self.psa)
        self.admin = make_user('reassignboss', role='admin', superuser=True)
        self.client_ = Client()
        self.client_.force_login(self.admin)

    def _staff(self, resp):
        return {
            item['clinic'].name: {
                s['physician'].pk: s for s in item['staff_today']
            }
            for item in resp.context['clinic_data']
        }

    def test_full_day_reassignment_moves_scheduled_physician(self):
        self.DayReassignment.objects.create(
            physician=self.nroc, clinic=self.clinic_b,
            date=self.MONDAY, session='full')
        staff = self._staff(self.client_.get(f'/clinics/?date={self.MONDAY}'))
        self.assertNotIn(self.nroc.pk, staff['Alpharetta'])
        self.assertEqual(staff['Buckhead'][self.nroc.pk]['label'], 'Full day')
        self.assertTrue(staff['Buckhead'][self.nroc.pk]['reassigned'])

    def test_half_day_reassignment_splits_the_day(self):
        # PM moved to B; AM stays at A per the weekly schedule
        self.DayReassignment.objects.create(
            physician=self.nroc, clinic=self.clinic_b,
            date=self.MONDAY, session='pm')
        staff = self._staff(self.client_.get(f'/clinics/?date={self.MONDAY}'))
        self.assertEqual(staff['Alpharetta'][self.nroc.pk]['label'], 'AM')
        self.assertEqual(staff['Buckhead'][self.nroc.pk]['label'], 'PM')
        self.assertTrue(staff['Buckhead'][self.nroc.pk]['reassigned'])
        self.assertFalse(staff['Alpharetta'][self.nroc.pk]['reassigned'])

    def test_reassignment_works_for_legacy_psa_physician(self):
        self.DayReassignment.objects.create(
            physician=self.psa, clinic=self.clinic_b,
            date=self.MONDAY, session='full')
        staff = self._staff(self.client_.get(f'/clinics/?date={self.MONDAY}'))
        self.assertNotIn(self.psa.pk, staff['Alpharetta'])
        self.assertEqual(staff['Buckhead'][self.psa.pk]['label'], 'Full day')

    def test_only_applies_on_that_date(self):
        self.DayReassignment.objects.create(
            physician=self.nroc, clinic=self.clinic_b,
            date=self.MONDAY, session='full')
        next_monday = self.MONDAY + timedelta(days=7)
        staff = self._staff(self.client_.get(f'/clinics/?date={next_monday}'))
        self.assertIn(self.nroc.pk, staff['Alpharetta'])
        self.assertNotIn(self.nroc.pk, staff.get('Buckhead', {}))

    def test_post_endpoint_creates_reassignment(self):
        r = self.client_.post('/clinics/reassign/', {
            'date': str(self.MONDAY), 'physician': self.psa.pk,
            'clinic': self.clinic_b.pk, 'session': 'am', 'note': 'staff gap',
        })
        self.assertEqual(r.status_code, 302)
        row = self.DayReassignment.objects.get(physician=self.psa)
        self.assertEqual((row.clinic, row.date, row.session, row.note),
                         (self.clinic_b, self.MONDAY, 'am', 'staff gap'))

    def test_full_day_conflicts_with_existing_half_day(self):
        self.DayReassignment.objects.create(
            physician=self.nroc, clinic=self.clinic_b,
            date=self.MONDAY, session='am')
        r = self.client_.post('/clinics/reassign/', {
            'date': str(self.MONDAY), 'physician': self.nroc.pk,
            'clinic': self.clinic_b.pk, 'session': 'full',
        }, follow=True)
        self.assertEqual(
            self.DayReassignment.objects.filter(physician=self.nroc).count(), 1)
        self.assertContains(r, 'already has a reassignment')

    def test_delete_endpoint(self):
        row = self.DayReassignment.objects.create(
            physician=self.nroc, clinic=self.clinic_b,
            date=self.MONDAY, session='full')
        r = self.client_.post(f'/clinics/reassign/{row.pk}/delete/')
        self.assertEqual(r.status_code, 302)
        self.assertFalse(self.DayReassignment.objects.exists())

    def test_reassign_requires_admin(self):
        phys_user = make_user('plainreassign', role='physician', scope='nroc')
        c2 = Client()
        c2.force_login(phys_user)
        r = c2.post('/clinics/reassign/', {
            'date': str(self.MONDAY), 'physician': self.nroc.pk,
            'clinic': self.clinic_b.pk,
        })
        self.assertEqual(self.DayReassignment.objects.count(), 0)

    def test_locum_cannot_be_reassigned(self):
        locum = Physician.objects.create(
            first_name='Lo', last_name='Cum', email='lc2@x.com',
            physician_type='locum')
        r = self.client_.post('/clinics/reassign/', {
            'date': str(self.MONDAY), 'physician': locum.pk,
            'clinic': self.clinic_b.pk,
        }, follow=True)
        self.assertEqual(self.DayReassignment.objects.count(), 0)


class CalendarViewTests(TestCase):
    """Monthly calendar showing per-day clinic staffing and who is off."""

    MONDAY = date(2026, 7, 13)

    def setUp(self):
        from .models import ClinicSchedule, DayReassignment
        self.ClinicSchedule = ClinicSchedule
        self.DayReassignment = DayReassignment
        self.clinic_a = Clinic.objects.create(name='Alpharetta')
        self.clinic_b = Clinic.objects.create(name='Buckhead')
        self.nroc = Physician.objects.create(
            first_name='Nina', last_name='Roc', email='nr3@x.com',
            physician_type='regular')
        self.psa = Physician.objects.create(
            first_name='Pat', last_name='Sa', email='ps3@x.com',
            physician_type='psa')
        # NROC: Mondays full day at A via the weekly grid
        for session in ('am', 'pm'):
            self.ClinicSchedule.objects.create(
                physician=self.nroc, clinic=self.clinic_a,
                day_of_week=0, session=session)
        # PSA: legacy affiliation with B
        self.clinic_b.regular_physicians.add(self.psa)
        self.admin = make_user('calboss', role='admin', superuser=True)
        self.client_ = Client()
        self.client_.force_login(self.admin)

    def _get(self, year=2026, month=7):
        return self.client_.get(f'/calendar/?year={year}&month={month}')

    def _summary(self, resp, d):
        return resp.context['day_summaries'][d.isoformat()]

    def test_scheduled_physicians_appear_on_their_days(self):
        r = self._get()
        self.assertEqual(r.status_code, 200)
        monday = self._summary(r, self.MONDAY)
        clinics = {c['name']: c['staff'] for c in monday['clinics']}
        a_names = {(s['name'], s['label']) for s in clinics['Alpharetta']}
        self.assertIn(('Dr. Nina Roc', 'Full day'), a_names)
        # Legacy PSA shows at B every workday
        b_names = {s['name'] for s in clinics['Buckhead']}
        self.assertIn('Dr. Pat Sa', b_names)
        # Weekly-grid physician absent on a day they aren't scheduled
        tuesday = self._summary(r, self.MONDAY + timedelta(days=1))
        tue_clinics = {c['name']: c['staff'] for c in tuesday['clinics']}
        tue_a = {s['name'] for s in tue_clinics.get('Alpharetta', [])}
        self.assertNotIn('Dr. Nina Roc', tue_a)

    def test_off_physicians_listed_and_flagged(self):
        TimeOffRequest.objects.create(
            physician=self.nroc, status='approved', request_type='vacation',
            start_date=self.MONDAY, end_date=self.MONDAY)
        monday = self._summary(self._get(), self.MONDAY)
        self.assertIn('Dr. Nina Roc', monday['off'])
        clinics = {c['name']: c['staff'] for c in monday['clinics']}
        entry = next(s for s in clinics['Alpharetta']
                     if s['name'] == 'Dr. Nina Roc')
        self.assertTrue(entry['out'])

    def test_reassignment_reflected_on_calendar(self):
        self.DayReassignment.objects.create(
            physician=self.nroc, clinic=self.clinic_b,
            date=self.MONDAY, session='pm')
        monday = self._summary(self._get(), self.MONDAY)
        clinics = {c['name']: c['staff'] for c in monday['clinics']}
        a = next(s for s in clinics['Alpharetta'] if s['name'] == 'Dr. Nina Roc')
        b = next(s for s in clinics['Buckhead'] if s['name'] == 'Dr. Nina Roc')
        self.assertEqual(a['label'], 'AM')
        self.assertEqual(b['label'], 'PM')
        self.assertTrue(b['reassigned'])

    def test_weekend_and_holiday_not_workdays(self):
        r = self._get()
        saturday = self._summary(r, date(2026, 7, 11))
        self.assertFalse(saturday['workday'])
        self.assertEqual(saturday['clinics'], [])
        july4_observed = self._summary(self._get(month=7), date(2026, 7, 4))
        self.assertFalse(july4_observed['workday'])

    def test_month_navigation_bounds(self):
        r = self.client_.get('/calendar/?year=2026&month=13')
        self.assertEqual(r.status_code, 200)  # falls back to current month
        r = self._get(year=2026, month=1)
        self.assertIn(date(2026, 1, 1).isoformat(), r.context['day_summaries'])

    def test_nursing_can_view_physician_cannot(self):
        nurse = make_user('calnurse', role='nursing')
        c2 = Client()
        c2.force_login(nurse)
        self.assertEqual(c2.get('/calendar/').status_code, 200)
        doc = make_user('caldoc', role='physician', scope='nroc')
        c3 = Client()
        c3.force_login(doc)
        self.assertEqual(c3.get('/calendar/').status_code, 302)  # bounced
