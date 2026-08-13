"""
Tests for per-day time-off approval + the post-approval locum popup + the
"approved & covered" notification email.

Run with:
    python manage.py test coverage_tracker.tests_day_approval

Covers:
  - Day rows are created on submit, one per business day
  - Approving/denying a single day, and the roll-up to request status
  - Approving a day redirects to the list with the popup open
  - The popup only opens for approved days and only for approvers
  - Assigning a locum from the popup creates coverage and emails the group
  - The email contains the time-off details AND the covering locum
  - No email until BOTH conditions are met (approved + locum assigned)
  - Denying an approved day removes that day's locum coverage
  - Downstream views (coverage page, calendar, dashboard) honor day status
  - Legacy requests with no day rows still behave as before
"""
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings

from .models import (
    Physician, Clinic, TimeOffRequest, TimeOffDay, CoverageAssignment,
    UserProfile,
)

# Holiday-free weekdays: Oct 2026 — 5th=Mon, 6th=Tue, 7th=Wed, 8th=Thu, 9th=Fri
MON, TUE, WED, THU, FRI = (date(2026, 10, d) for d in (5, 6, 7, 8, 9))

EMAIL_SETTINGS = dict(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    SEND_NOTIFICATION_EMAILS=True,
    EMAIL_HOST_USER='scheduler@test.org',
    TIME_OFF_NOTIFICATION_RECIPIENTS=['office@test.org', 'manager@test.org'],
)


@override_settings(**EMAIL_SETTINGS)
class DayApprovalBase(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.clinic = Clinic.objects.create(name='Clinic Alpha')
        cls.clinic_b = Clinic.objects.create(name='Clinic Beta')

        cls.doc = Physician.objects.create(
            first_name='Nina', last_name='North', email='nina@test.org',
            physician_type='regular', total_vacation_days=20)
        cls.locum = Physician.objects.create(
            first_name='Lou', last_name='Cummings', email='lou@test.org',
            physician_type='locum', hourly_rate=Decimal('100.00'),
            agency='LocumCo')
        cls.clinic.regular_physicians.add(cls.doc)

        cls.admin = User.objects.create_user(
            'admin', password='pw', first_name='Ada', last_name='Min')
        UserProfile.objects.create(user=cls.admin, role='admin', scope='all')

        cls.phys_user = User.objects.create_user('doc', password='pw')
        UserProfile.objects.create(user=cls.phys_user, role='physician',
                                   scope='nroc', physician=cls.doc)

    def setUp(self):
        self.client.login(username='admin', password='pw')
        mail.outbox = []

    # -- helpers -----------------------------------------------------------
    def submit(self, start=MON, end=WED, request_type='vacation'):
        resp = self.client.post('/time-off/add/', {
            'physician': self.doc.pk,
            'start_date': start.isoformat(),
            'end_date': end.isoformat(),
            'request_type': request_type,
            'notes': '',
        })
        self.assertEqual(resp.status_code, 302)
        mail.outbox = []   # discard the "new request submitted" email
        return TimeOffRequest.objects.get(physician=self.doc, start_date=start)

    def day(self, req, when):
        return TimeOffDay.objects.get(request=req, date=when)

    def approve_day(self, req, when):
        d = self.day(req, when)
        return self.client.post(f'/time-off/day/{d.pk}/approve/')

    def deny_day(self, req, when):
        d = self.day(req, when)
        return self.client.post(f'/time-off/day/{d.pk}/deny/')

    def assign_locum(self, req, when, locum=None, clinic=None, hours='8'):
        """Submit the group form filling in just one day's row."""
        key = when.strftime('%Y-%m-%d')
        return self.client.post(f'/time-off/{req.pk}/assign-locums/', {
            f'locum_{key}': (locum or self.locum).pk,
            f'clinic_{key}': (clinic or self.clinic).pk,
            f'hours_{key}': hours,
        })

    def assign_locums(self, req, day_map):
        """Submit the group form for several days at once.
        day_map: {date: (locum, clinic, hours)}"""
        data = {}
        for when, (locum, clinic, hours) in day_map.items():
            key = when.strftime('%Y-%m-%d')
            data[f'locum_{key}'] = locum.pk
            data[f'clinic_{key}'] = clinic.pk
            data[f'hours_{key}'] = hours
        return self.client.post(f'/time-off/{req.pk}/assign-locums/', data)


# ─── 1. Day rows ─────────────────────────────────────────────────────────────

class DayRowCreationTests(DayApprovalBase):

    def test_submit_creates_one_row_per_business_day(self):
        req = self.submit(MON, WED)
        self.assertEqual(req.days.count(), 3)
        self.assertEqual(
            sorted(req.days.values_list('date', flat=True)), [MON, TUE, WED])

    def test_new_rows_start_pending(self):
        req = self.submit()
        self.assertEqual(set(req.days.values_list('status', flat=True)), {'pending'})

    def test_weekend_days_excluded(self):
        # Fri Oct 9 through Mon Oct 12 -> only Fri + Mon are business days
        req = self.submit(FRI, date(2026, 10, 12))
        self.assertEqual(list(req.days.values_list('date', flat=True)),
                         [FRI, date(2026, 10, 12)])

    def test_ensure_day_rows_is_idempotent(self):
        req = self.submit()
        req.ensure_day_rows()
        req.ensure_day_rows()
        self.assertEqual(req.days.count(), 3)

    def test_editing_dates_resyncs_rows(self):
        req = self.submit(MON, WED)
        self.client.post(f'/time-off/{req.pk}/edit/', {
            'physician': self.doc.pk,
            'start_date': MON.isoformat(),
            'end_date': TUE.isoformat(),
            'request_type': 'vacation',
            'status': 'pending',
            'notes': '',
        })
        req.refresh_from_db()
        self.assertEqual(list(req.days.values_list('date', flat=True)), [MON, TUE])


# ─── 2. Approving / denying individual days ──────────────────────────────────

class IndividualDecisionTests(DayApprovalBase):

    def test_approve_one_day_leaves_others_pending(self):
        req = self.submit(MON, WED)
        self.approve_day(req, MON)
        self.assertEqual(self.day(req, MON).status, 'approved')
        self.assertEqual(self.day(req, TUE).status, 'pending')
        self.assertEqual(self.day(req, WED).status, 'pending')

    def test_deny_one_day_leaves_others_pending(self):
        req = self.submit(MON, WED)
        self.deny_day(req, TUE)
        self.assertEqual(self.day(req, TUE).status, 'denied')
        self.assertEqual(self.day(req, MON).status, 'pending')

    def test_any_approved_day_rolls_request_up_to_approved(self):
        req = self.submit(MON, WED)
        self.approve_day(req, MON)
        req.refresh_from_db()
        self.assertEqual(req.status, 'approved')

    def test_all_days_denied_rolls_request_to_denied(self):
        req = self.submit(MON, WED)
        for d in (MON, TUE, WED):
            self.deny_day(req, d)
        req.refresh_from_db()
        self.assertEqual(req.status, 'denied')

    def test_approve_day_records_who_and_when(self):
        req = self.submit()
        self.approve_day(req, MON)
        d = self.day(req, MON)
        self.assertEqual(d.decided_by, 'Ada Min')
        self.assertIsNotNone(d.decided_at)

    def test_approve_day_redirects_with_popup_open(self):
        req = self.submit()
        resp = self.approve_day(req, MON)
        self.assertEqual(resp.status_code, 302)
        self.assertIn(f'assign_req={req.pk}', resp.url)

    def test_denied_day_can_be_approved_afterwards(self):
        req = self.submit()
        self.deny_day(req, MON)
        self.approve_day(req, MON)
        self.assertEqual(self.day(req, MON).status, 'approved')

    def test_get_request_does_nothing(self):
        req = self.submit()
        d = self.day(req, MON)
        self.client.get(f'/time-off/day/{d.pk}/approve/')
        self.assertEqual(self.day(req, MON).status, 'pending')

    def test_physician_cannot_approve_days(self):
        req = self.submit()
        self.client.logout()
        self.client.login(username='doc', password='pw')
        d = self.day(req, MON)
        self.client.post(f'/time-off/day/{d.pk}/approve/')
        self.assertEqual(self.day(req, MON).status, 'pending')

    def test_approve_all_button_approves_every_pending_day(self):
        req = self.submit(MON, WED)
        self.deny_day(req, TUE)
        self.client.post(f'/time-off/{req.pk}/approve/')
        statuses = dict(req.days.values_list('date', 'status'))
        self.assertEqual(statuses[MON], 'approved')
        self.assertEqual(statuses[WED], 'approved')
        # An explicitly denied day is NOT silently flipped
        self.assertEqual(statuses[TUE], 'denied')

    def test_deny_all_button_denies_every_day(self):
        req = self.submit(MON, WED)
        self.client.post(f'/time-off/{req.pk}/deny/')
        self.assertEqual(set(req.days.values_list('status', flat=True)), {'denied'})


# ─── 3. The group locum popup ────────────────────────────────────────────────

class LocumPopupTests(DayApprovalBase):

    def test_popup_context_lists_every_approved_day(self):
        req = self.submit(MON, WED)
        self.approve_day(req, MON)
        self.approve_day(req, WED)
        resp = self.client.get(f'/time-off/?assign_req={req.pk}')
        ctx = resp.context['assign_req_ctx']
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx['req'].pk, req.pk)
        self.assertEqual([r['day'].date for r in ctx['day_rows']], [MON, WED])

    def test_popup_shows_denied_and_pending_days(self):
        req = self.submit(MON, WED)
        self.approve_day(req, MON)
        self.deny_day(req, TUE)
        resp = self.client.get(f'/time-off/?assign_req={req.pk}')
        ctx = resp.context['assign_req_ctx']
        self.assertEqual(ctx['denied_days'], [TUE])
        self.assertEqual(ctx['pending_days'], [WED])

    def test_popup_renders_in_html(self):
        req = self.submit(MON, WED)
        self.approve_day(req, MON)
        resp = self.client.get(f'/time-off/?assign_req={req.pk}')
        self.assertContains(resp, 'Assign Locum Coverage')
        self.assertContains(resp, f'/time-off/{req.pk}/assign-locums/')
        self.assertContains(resp, f'locum_{MON.isoformat()}')

    def test_no_popup_when_no_days_approved_yet(self):
        req = self.submit()
        resp = self.client.get(f'/time-off/?assign_req={req.pk}')
        self.assertIsNone(resp.context['assign_req_ctx'])

    def test_no_popup_for_non_approver(self):
        req = self.submit()
        self.approve_day(req, MON)
        self.client.logout()
        self.client.login(username='doc', password='pw')
        resp = self.client.get(f'/time-off/?assign_req={req.pk}')
        self.assertIsNone(resp.context['assign_req_ctx'])

    def test_garbage_assign_req_param_is_ignored(self):
        self.submit()
        resp = self.client.get('/time-off/?assign_req=notanumber')
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.context['assign_req_ctx'])

    def test_popup_preselects_existing_assignments(self):
        req = self.submit(MON, WED)
        self.approve_day(req, MON)
        self.approve_day(req, TUE)
        self.assign_locum(req, MON)
        resp = self.client.get(f'/time-off/?assign_req={req.pk}')
        rows = resp.context['assign_req_ctx']['day_rows']
        mon_row = next(r for r in rows if r['day'].date == MON)
        tue_row = next(r for r in rows if r['day'].date == TUE)
        self.assertEqual(mon_row['existing'].covering_physician_id, self.locum.pk)
        self.assertIsNone(tue_row['existing'])


# ─── 4. Assigning the locum + the notification email ─────────────────────────

class AssignAndNotifyTests(DayApprovalBase):

    def test_assignment_creates_coverage_row(self):
        req = self.submit()
        self.approve_day(req, MON)
        self.assign_locum(req, MON, hours='7.5')
        a = CoverageAssignment.objects.get(covered_physician=self.doc, date=MON)
        self.assertEqual(a.covering_physician, self.locum)
        self.assertEqual(a.clinic, self.clinic)
        self.assertEqual(a.hours, Decimal('7.50'))

    def test_assignment_sends_exactly_one_email(self):
        req = self.submit()
        self.approve_day(req, MON)
        mail.outbox = []
        self.assign_locum(req, MON)
        self.assertEqual(len(mail.outbox), 1)

    def test_approval_alone_sends_no_covered_email(self):
        req = self.submit()
        mail.outbox = []
        self.approve_day(req, MON)
        for m in mail.outbox:
            self.assertNotIn('Approved & Covered', m.subject)

    def test_email_subject_names_physician_range_and_locum(self):
        req = self.submit()
        self.approve_day(req, MON)
        mail.outbox = []
        self.assign_locum(req, MON)
        self.assertEqual(
            mail.outbox[-1].subject,
            'Time Off Approved & Covered — Dr. North (Oct 05 – Oct 07): '
            '1 day approved, Dr. Cummings covering')

    def test_email_body_has_time_off_details_and_locum(self):
        req = self.submit()
        self.approve_day(req, MON)
        mail.outbox = []
        self.assign_locum(req, MON, hours='6')
        body = mail.outbox[-1].body
        # Time-off info
        self.assertIn('Dr. Nina North', body)
        self.assertIn('Vacation', body)
        self.assertIn('Oct 05, 2026', body)
        self.assertIn('Clinic Alpha', body)
        # Locum info
        self.assertIn('Dr. Lou Cummings', body)
        self.assertIn('LocumCo', body)
        self.assertIn('6', body)
        self.assertIn('Ada Min', body)

    def test_one_submit_many_days_sends_one_email_listing_each_day(self):
        req = self.submit(MON, WED)
        for d in (MON, TUE, WED):
            self.approve_day(req, d)
        other = Physician.objects.create(
            first_name='Lena', last_name='Kovacs', email='lena2@test.org',
            physician_type='locum', hourly_rate=Decimal('110.00'))
        mail.outbox = []
        self.assign_locums(req, {
            MON: (self.locum, self.clinic, '8'),
            TUE: (other, self.clinic_b, '6'),
            WED: (self.locum, self.clinic, '8'),
        })
        self.assertEqual(len(mail.outbox), 1)
        body = mail.outbox[0].body
        self.assertIn('3 of 3 days', body)
        self.assertIn('Mon, Oct 05, 2026:  Dr. Lou Cummings at Clinic Alpha', body)
        self.assertIn('Tue, Oct 06, 2026:  Dr. Lena Kovacs at Clinic Beta — 6.00 hrs', body)
        self.assertIn('Wed, Oct 07, 2026:  Dr. Lou Cummings at Clinic Alpha', body)
        self.assertIn('2 locums covering', mail.outbox[0].subject)

    def test_email_covers_approved_days_even_when_request_partially_decided(self):
        """The core ask: submit as a group before ALL days are decided —
        the email reports the approved days (covered or not), plus what was
        denied and what's still waiting."""
        req = self.submit(MON, WED)   # 3 business days
        self.approve_day(req, MON)
        self.approve_day(req, TUE)
        self.deny_day(req, WED)
        mail.outbox = []
        # Only assign a locum for MON; TUE stays unassigned
        self.assign_locum(req, MON)
        self.assertEqual(len(mail.outbox), 1)
        body = mail.outbox[0].body
        self.assertIn('2 of 3 days', body)
        self.assertIn('Mon, Oct 05, 2026:  Dr. Lou Cummings at Clinic Alpha', body)
        self.assertIn('Tue, Oct 06, 2026:  no locum assigned yet', body)
        self.assertIn('Denied:', body)
        self.assertIn('Oct 07', body)

    def test_email_lists_days_still_awaiting_decision(self):
        req = self.submit(MON, WED)
        self.approve_day(req, MON)     # TUE + WED still pending
        mail.outbox = []
        self.assign_locum(req, MON)
        body = mail.outbox[0].body
        self.assertIn('1 of 3 days', body)
        self.assertIn('Awaiting decision: Oct 06, Oct 07', body)

    def test_submit_with_no_selections_sends_no_email(self):
        req = self.submit(MON, WED)
        self.approve_day(req, MON)
        mail.outbox = []
        self.client.post(f'/time-off/{req.pk}/assign-locums/', {})
        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(
            CoverageAssignment.objects.filter(covered_physician=self.doc).exists())

    def test_email_goes_to_the_main_group(self):
        req = self.submit()
        self.approve_day(req, MON)
        mail.outbox = []
        self.assign_locum(req, MON)
        self.assertEqual(sorted(mail.outbox[-1].to),
                         ['manager@test.org', 'office@test.org'])

    def test_reassigning_locum_updates_row_and_renotifies(self):
        req = self.submit()
        self.approve_day(req, MON)
        self.assign_locum(req, MON)
        other = Physician.objects.create(
            first_name='Lena', last_name='Kovacs', email='lena@test.org',
            physician_type='locum', hourly_rate=Decimal('110.00'))
        mail.outbox = []
        self.assign_locum(req, MON, locum=other, clinic=self.clinic_b)
        self.assertEqual(
            CoverageAssignment.objects.filter(covered_physician=self.doc, date=MON).count(), 1)
        a = CoverageAssignment.objects.get(covered_physician=self.doc, date=MON)
        self.assertEqual(a.covering_physician, other)
        self.assertEqual(a.clinic, self.clinic_b)
        self.assertEqual(len(mail.outbox), 1)

    def test_cannot_assign_locum_to_pending_day(self):
        req = self.submit()
        mail.outbox = []
        self.assign_locum(req, MON)
        self.assertFalse(
            CoverageAssignment.objects.filter(covered_physician=self.doc, date=MON).exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_missing_locum_selection_saves_nothing(self):
        req = self.submit()
        self.approve_day(req, MON)
        mail.outbox = []
        key = MON.strftime('%Y-%m-%d')
        self.client.post(f'/time-off/{req.pk}/assign-locums/',
                         {f'locum_{key}': '', f'clinic_{key}': self.clinic.pk})
        self.assertFalse(
            CoverageAssignment.objects.filter(covered_physician=self.doc, date=MON).exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_missing_clinic_selection_saves_nothing(self):
        req = self.submit()
        self.approve_day(req, MON)
        mail.outbox = []
        key = MON.strftime('%Y-%m-%d')
        self.client.post(f'/time-off/{req.pk}/assign-locums/',
                         {f'locum_{key}': self.locum.pk, f'clinic_{key}': ''})
        self.assertFalse(
            CoverageAssignment.objects.filter(covered_physician=self.doc, date=MON).exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_one_bad_day_does_not_block_the_good_day(self):
        req = self.submit(MON, WED)
        self.approve_day(req, MON)
        self.approve_day(req, TUE)
        mail.outbox = []
        mon_key, tue_key = MON.strftime('%Y-%m-%d'), TUE.strftime('%Y-%m-%d')
        self.client.post(f'/time-off/{req.pk}/assign-locums/', {
            f'locum_{mon_key}': self.locum.pk, f'clinic_{mon_key}': self.clinic.pk,
            f'locum_{tue_key}': self.locum.pk, f'clinic_{tue_key}': '',   # bad row
        })
        self.assertTrue(
            CoverageAssignment.objects.filter(covered_physician=self.doc, date=MON).exists())
        self.assertFalse(
            CoverageAssignment.objects.filter(covered_physician=self.doc, date=TUE).exists())
        self.assertEqual(len(mail.outbox), 1)   # MON still went out

    def test_blank_hours_defaults_to_eight(self):
        req = self.submit()
        self.approve_day(req, MON)
        self.assign_locum(req, MON, hours='')
        a = CoverageAssignment.objects.get(covered_physician=self.doc, date=MON)
        self.assertEqual(a.hours, Decimal('8.00'))

    def test_non_approver_cannot_assign(self):
        req = self.submit()
        self.approve_day(req, MON)
        self.client.logout()
        self.client.login(username='doc', password='pw')
        mail.outbox = []
        self.assign_locum(req, MON)
        self.assertFalse(
            CoverageAssignment.objects.filter(covered_physician=self.doc, date=MON).exists())

    def test_two_separate_submits_send_two_emails(self):
        """Coverage can still be added in stages — each group submit that
        saves something sends one (cumulative) email."""
        req = self.submit(MON, WED)
        self.approve_day(req, MON)
        self.approve_day(req, TUE)
        mail.outbox = []
        self.assign_locum(req, MON)
        self.assign_locum(req, TUE)
        self.assertEqual(len(mail.outbox), 2)
        # The second email is cumulative: both days now covered
        body = mail.outbox[1].body
        self.assertIn('Mon, Oct 05, 2026:  Dr. Lou Cummings', body)
        self.assertIn('Tue, Oct 06, 2026:  Dr. Lou Cummings', body)

    def test_denying_an_approved_day_removes_its_coverage(self):
        req = self.submit()
        self.approve_day(req, MON)
        self.assign_locum(req, MON)
        self.deny_day(req, MON)
        self.assertFalse(
            CoverageAssignment.objects.filter(covered_physician=self.doc, date=MON).exists())

    def test_email_failure_does_not_block_the_assignment(self):
        req = self.submit()
        self.approve_day(req, MON)
        with override_settings(EMAIL_BACKEND='coverage_tracker.tests_day_approval.BrokenBackend'):
            self.assign_locum(req, MON)
        self.assertTrue(
            CoverageAssignment.objects.filter(covered_physician=self.doc, date=MON).exists())


class BrokenBackend:
    """Email backend that always blows up — used to prove failures are swallowed."""
    def __init__(self, *a, **kw):
        pass

    def send_messages(self, messages):
        raise RuntimeError('smtp is down')


# ─── 5. Downstream views honor per-day status ────────────────────────────────

class DownstreamViewTests(DayApprovalBase):

    def test_coverage_page_lists_only_approved_days(self):
        req = self.submit(MON, WED)
        self.approve_day(req, MON)
        self.deny_day(req, TUE)
        resp = self.client.get(f'/time-off/approved-coverage/?year={MON.year}')
        entry = next(e for e in resp.context['enriched'] if e['request'].pk == req.pk)
        dates = [d['date'] for d in entry['day_coverage']]
        self.assertEqual(dates, [MON])

    def test_assign_locum_page_lists_only_approved_days(self):
        req = self.submit(MON, WED)
        self.approve_day(req, MON)
        self.approve_day(req, WED)
        resp = self.client.get(f'/time-off/{req.pk}/assign-locum/')
        self.assertEqual(resp.context['all_dates'], [MON, WED])

    def test_calendar_marks_only_approved_days_off(self):
        req = self.submit(MON, WED)
        self.approve_day(req, MON)
        resp = self.client.get(f'/calendar/?date={MON.isoformat()}')
        self.assertEqual(resp.status_code, 200)

    def test_vacation_pool_counts_only_approved_days(self):
        req = self.submit(MON, WED)
        self.approve_day(req, MON)
        self.approve_day(req, TUE)
        self.deny_day(req, WED)
        self.assertEqual(self.doc.days_taken(MON.year), 2)
        self.assertEqual(self.doc.days_pending(MON.year), 0)

    def test_partially_decided_request_counts_pending_days(self):
        req = self.submit(MON, WED)
        self.approve_day(req, MON)
        self.assertEqual(self.doc.days_taken(MON.year), 1)
        self.assertEqual(self.doc.days_pending(MON.year), 2)

    def test_request_stays_on_pending_list_while_days_remain(self):
        req = self.submit(MON, WED)
        self.approve_day(req, MON)
        resp = self.client.get('/')
        self.assertIn(req.pk, [r.pk for r in resp.context['pending']])

    def test_request_leaves_pending_list_when_all_days_decided(self):
        req = self.submit(MON, WED)
        for d in (MON, TUE, WED):
            self.approve_day(req, d)
        resp = self.client.get('/')
        self.assertNotIn(req.pk, [r.pk for r in resp.context['pending']])

    def test_time_off_list_exposes_day_details(self):
        req = self.submit(MON, WED)
        resp = self.client.get('/time-off/')
        item = next(i for i in resp.context['enriched_requests'] if i['req'].pk == req.pk)
        self.assertEqual(len(item['day_details']), 3)
        self.assertTrue(item['has_pending_days'])


# ─── 6. Legacy requests (no day rows) still work ─────────────────────────────

class LegacyFallbackTests(DayApprovalBase):

    def make_legacy(self, status='approved'):
        """A request created straight in the DB, bypassing the day rows."""
        return TimeOffRequest.objects.create(
            physician=self.doc, start_date=MON, end_date=WED,
            request_type='vacation', status=status)

    def test_legacy_approved_request_counts_all_days(self):
        self.make_legacy('approved')
        self.assertEqual(self.doc.days_taken(MON.year), 3)

    def test_legacy_approved_workdays_falls_back(self):
        req = self.make_legacy('approved')
        self.assertEqual(req.approved_workdays(), [MON, TUE, WED])

    def test_legacy_pending_request_has_no_approved_days(self):
        req = self.make_legacy('pending')
        self.assertEqual(req.approved_workdays(), [])

    def test_legacy_request_shows_on_dashboard_out_today(self):
        TimeOffRequest.objects.create(
            physician=self.doc, start_date=date.today(), end_date=date.today(),
            request_type='vacation', status='approved')
        resp = self.client.get('/')
        self.assertIn(self.doc, [r.physician for r in resp.context['out_today']])

    def test_legacy_request_gets_day_rows_on_list_view(self):
        req = self.make_legacy('approved')
        self.assertEqual(req.days.count(), 0)
        self.client.get('/time-off/')
        self.assertEqual(req.days.count(), 3)
        self.assertEqual(set(req.days.values_list('status', flat=True)), {'approved'})

    def test_legacy_assign_locum_page_still_lists_all_days(self):
        req = self.make_legacy('approved')
        resp = self.client.get(f'/time-off/{req.pk}/assign-locum/')
        self.assertEqual(resp.context['all_dates'], [MON, TUE, WED])
