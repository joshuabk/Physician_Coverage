"""
Tests for every email-notification feature.

Run with:
    python manage.py test coverage_tracker.tests_email

Covers:
  - New-request email (recipients, group-admin routing, dedup, body content,
    clinics line for both schedule styles, notes, submitted-by)
  - Approved / denied decision emails (button, edit-form flip, no duplicates,
    clear APPROVED/DENIED wording)
  - Locum-assigned email (all three assignment flows, multi-day summary,
    clinics line, hours, no-coverage days excluded, blank saves silent)
  - Safety: master switch off -> console only; no recipients -> no email;
    a failing mail server never blocks the request itself.

Uses Django's in-memory (locmem) email backend, so nothing is ever
actually sent, and a fresh test database, so real data is never touched.
"""
from datetime import date
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings

from .models import (
    Physician, Clinic, ClinicSchedule, DayReassignment,
    TimeOffRequest, CoverageAssignment, UserProfile,
)

# Fixed, holiday-free weekdays (Oct 2026: 5th=Mon, 6th=Tue, 7th=Wed)
MON, TUE, WED = date(2026, 10, 5), date(2026, 10, 6), date(2026, 10, 7)

EMAIL_SETTINGS = dict(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    SEND_NOTIFICATION_EMAILS=False,
    EMAIL_HOST_USER='scheduler@test.org',
    TIME_OFF_NOTIFICATION_RECIPIENTS=['office@test.org', 'manager@test.org'],
)


@override_settings(**EMAIL_SETTINGS)
class EmailTestBase(TestCase):
    """Shared fixtures: users of every role, physicians, clinics."""

    @classmethod
    def setUpTestData(cls):
        # Clinics
        cls.clinic_a = Clinic.objects.create(name='Clinic Alpha')
        cls.clinic_b = Clinic.objects.create(name='Clinic Beta')
        cls.clinic_c = Clinic.objects.create(name='Clinic Gamma')

        # Physicians
        cls.nroc_doc = Physician.objects.create(
            first_name='Nina', last_name='North', email='nina@test.org',
            physician_type='regular')
        cls.psa_doc = Physician.objects.create(
            first_name='Paul', last_name='South', email='paul@test.org',
            physician_type='psa')
        cls.locum = Physician.objects.create(
            first_name='Lou', last_name='Cummings', email='lou@test.org',
            physician_type='locum', hourly_rate=Decimal('100.00'))
        cls.locum2 = Physician.objects.create(
            first_name='Lena', last_name='Kovacs', email='lena@test.org',
            physician_type='locum', hourly_rate=Decimal('110.00'))

        # Legacy clinic affiliation for the NROC doc
        cls.clinic_a.regular_physicians.add(cls.nroc_doc)

        # Users / roles
        def make_user(username, role, scope='nroc', email='', physician=None,
                      first='', last=''):
            u = User.objects.create_user(
                username=username, password='pw', email=email,
                first_name=first, last_name=last)
            profile = u.profile  # auto-created? no — create explicitly
            return u

        cls.admin = User.objects.create_user(
            'admin', password='pw', first_name='Ada', last_name='Min')
        UserProfile.objects.create(user=cls.admin, role='admin', scope='all')

        cls.nroc_admin = User.objects.create_user(
            'nroc_admin', password='pw', email='nroc_admin@test.org',
            first_name='Nora', last_name='Chief')
        UserProfile.objects.create(user=cls.nroc_admin,
                                   role='physician_admin', scope='nroc')

        cls.psa_admin = User.objects.create_user(
            'psa_admin', password='pw', email='psa_admin@test.org',
            first_name='Pete', last_name='Chief')
        UserProfile.objects.create(user=cls.psa_admin,
                                   role='physician_admin', scope='psa')

        # A physician admin with NO email but a linked physician record
        cls.linked_phys = Physician.objects.create(
            first_name='Larry', last_name='Linked',
            email='larry_linked@test.org', physician_type='regular')
        cls.noemail_admin = User.objects.create_user('noemail_admin', password='pw')
        UserProfile.objects.create(user=cls.noemail_admin,
                                   role='physician_admin', scope='nroc',
                                   physician=cls.linked_phys)

    def setUp(self):
        self.client.login(username='admin', password='pw')

    # -- helpers ------------------------------------------------------------
    def submit_request(self, physician=None, start=MON, end=TUE, notes='',
                       request_type='vacation'):
        physician = physician or self.nroc_doc
        resp = self.client.post('/time-off/add/', {
            'physician': physician.pk,
            'start_date': start.isoformat(),
            'end_date': end.isoformat(),
            'request_type': request_type,
            'notes': notes,
        })
        self.assertEqual(resp.status_code, 302)
        return TimeOffRequest.objects.get(physician=physician, start_date=start)

    def last_email(self):
        self.assertTrue(mail.outbox, 'expected an email but none was sent')
        return mail.outbox[-1]


# ─── 1. New-request email ────────────────────────────────────────────────────

class SubmitEmailTests(EmailTestBase):

    def test_submission_sends_one_email(self):
        self.submit_request()
        self.assertEqual(len(mail.outbox), 1)

    def test_subject_and_sender(self):
        self.submit_request()
        m = self.last_email()
        self.assertEqual(
            m.subject, 'New Time Off Request — Dr. North (Oct 05 – Oct 06)')
        self.assertEqual(m.from_email, 'scheduler@test.org')

    def test_nroc_request_adds_nroc_admins_to_main_list(self):
        self.submit_request(self.nroc_doc)
        to = self.last_email().to
        # main list first, then the NROC group admins (incl. the one whose
        # address comes from a linked physician record); never the PSA admin
        self.assertIn('office@test.org', to)
        self.assertIn('manager@test.org', to)
        self.assertIn('nroc_admin@test.org', to)
        self.assertIn('larry_linked@test.org', to)
        self.assertNotIn('psa_admin@test.org', to)

    def test_psa_request_goes_to_psa_admin_not_nroc(self):
        self.submit_request(self.psa_doc)
        to = self.last_email().to
        self.assertIn('psa_admin@test.org', to)
        self.assertNotIn('nroc_admin@test.org', to)
        self.assertNotIn('larry_linked@test.org', to)

    @override_settings(TIME_OFF_NOTIFICATION_RECIPIENTS=['nroc_admin@test.org'])
    def test_admin_already_on_main_list_not_duplicated(self):
        self.submit_request(self.nroc_doc)
        to = self.last_email().to
        self.assertEqual(to.count('nroc_admin@test.org'), 1)

    def test_scope_all_admin_gets_both_groups(self):
        both = User.objects.create_user('both_admin', password='pw',
                                        email='both@test.org')
        UserProfile.objects.create(user=both, role='physician_admin', scope='all')
        self.submit_request(self.nroc_doc)
        self.assertIn('both@test.org', self.last_email().to)
        self.submit_request(self.psa_doc, start=WED, end=WED)
        self.assertIn('both@test.org', self.last_email().to)

    def test_body_contents(self):
        self.submit_request(notes='family trip')
        body = self.last_email().body
        self.assertIn('A new time off request has been submitted.', body)
        self.assertIn('Physician:  Dr. Nina North (NROC)', body)
        self.assertIn('Type:       Vacation', body)
        self.assertIn('Dates:      Oct 05, 2026 – Oct 06, 2026', body)
        self.assertIn('Work days:  2', body)
        self.assertIn('Status:     Pending approval', body)
        self.assertIn('Notes:      family trip', body)
        self.assertIn('Submitted by: Ada Min', body)

    def test_psa_body_shows_psa_group(self):
        self.submit_request(self.psa_doc)
        self.assertIn('Physician:  Dr. Paul South (PSA)', self.last_email().body)

    def test_notes_line_omitted_when_blank(self):
        self.submit_request()
        self.assertNotIn('Notes:', self.last_email().body)

    def test_invalid_form_sends_nothing(self):
        self.client.post('/time-off/add/', {
            'physician': self.nroc_doc.pk,
            'start_date': 'not-a-date', 'end_date': 'not-a-date',
            'request_type': 'vacation',
        })
        self.assertEqual(len(mail.outbox), 0)

    # clinics line -----------------------------------------------------------
    def test_clinics_line_legacy_affiliation(self):
        self.submit_request(self.nroc_doc)
        self.assertIn('Clinics:    Clinic Alpha', self.last_email().body)

    def test_clinics_line_weekly_grid_with_reassignment(self):
        # Mon: Alpha (AM) + Beta (PM); Tue: Alpha all day but AM reassigned to Gamma
        ClinicSchedule.objects.create(physician=self.nroc_doc,
                                      clinic=self.clinic_a, day_of_week=0, session='am')
        ClinicSchedule.objects.create(physician=self.nroc_doc,
                                      clinic=self.clinic_b, day_of_week=0, session='pm')
        ClinicSchedule.objects.create(physician=self.nroc_doc,
                                      clinic=self.clinic_a, day_of_week=1, session='am')
        ClinicSchedule.objects.create(physician=self.nroc_doc,
                                      clinic=self.clinic_a, day_of_week=1, session='pm')
        DayReassignment.objects.create(physician=self.nroc_doc,
                                       clinic=self.clinic_c, date=TUE, session='am')
        self.submit_request(self.nroc_doc)
        self.assertIn('Clinics:    Clinic Alpha, Clinic Beta, Clinic Gamma',
                      self.last_email().body)

    def test_clinics_line_only_covers_requested_days(self):
        # Grid: Monday at Alpha, WEDNESDAY at Beta. Request Mon–Tue only.
        ClinicSchedule.objects.create(physician=self.nroc_doc,
                                      clinic=self.clinic_a, day_of_week=0, session='am')
        ClinicSchedule.objects.create(physician=self.nroc_doc,
                                      clinic=self.clinic_b, day_of_week=2, session='am')
        self.submit_request(self.nroc_doc, start=MON, end=TUE)
        body = self.last_email().body
        self.assertIn('Clinic Alpha', body)
        self.assertNotIn('Clinic Beta', body)

    def test_clinics_line_omitted_when_no_schedule(self):
        # PSA doc has no affiliation and no grid
        self.submit_request(self.psa_doc)
        self.assertNotIn('Clinics:', self.last_email().body)

    def test_physician_admin_submission_also_notifies(self):
        self.client.logout()
        self.client.login(username='nroc_admin', password='pw')
        self.submit_request(self.nroc_doc)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Submitted by: Nora Chief', self.last_email().body)


# ─── 2 & 3. Approved / denied decision emails ────────────────────────────────

class DecisionEmailTests(EmailTestBase):

    def approve(self, req):
        return self.client.post(f'/time-off/{req.pk}/approve/')

    def deny(self, req):
        return self.client.post(f'/time-off/{req.pk}/deny/')

    def test_approve_sends_email_indicating_approved(self):
        req = self.submit_request()
        self.approve(req)
        m = self.last_email()
        self.assertEqual(m.subject, 'Time Off Approved — Dr. North (Oct 05 – Oct 06)')
        self.assertIn('has been APPROVED', m.body)
        self.assertIn('Status:     Approved', m.body)
        self.assertIn('Approved by: Ada Min', m.body)

    def test_deny_sends_email_indicating_denied(self):
        req = self.submit_request()
        self.deny(req)
        m = self.last_email()
        self.assertEqual(m.subject, 'Time Off Denied — Dr. North (Oct 05 – Oct 06)')
        self.assertIn('has been DENIED', m.body)
        self.assertIn('Status:     Denied', m.body)
        self.assertIn('Denied by: Ada Min', m.body)

    def test_decision_email_goes_to_main_list_only(self):
        req = self.submit_request()
        self.approve(req)
        self.assertEqual(sorted(self.last_email().to),
                         ['manager@test.org', 'office@test.org'])

    def test_decision_email_includes_clinics(self):
        req = self.submit_request(self.nroc_doc)
        self.approve(req)
        self.assertIn('Clinics:    Clinic Alpha', self.last_email().body)

    def test_no_duplicate_on_repeat_approve(self):
        req = self.submit_request()
        self.approve(req)
        n = len(mail.outbox)
        self.approve(req)          # already approved
        self.assertEqual(len(mail.outbox), n)

    def test_no_duplicate_on_repeat_deny(self):
        req = self.submit_request()
        self.deny(req)
        n = len(mail.outbox)
        self.deny(req)
        self.assertEqual(len(mail.outbox), n)

    def _edit(self, req, status):
        return self.client.post(f'/time-off/{req.pk}/edit/', {
            'physician': req.physician.pk,
            'start_date': req.start_date.isoformat(),
            'end_date': req.end_date.isoformat(),
            'request_type': req.request_type,
            'status': status, 'notes': '',
        })

    def test_edit_form_flip_to_approved_sends(self):
        req = self.submit_request()
        n = len(mail.outbox)
        self._edit(req, 'approved')
        self.assertEqual(len(mail.outbox), n + 1)
        self.assertIn('APPROVED', self.last_email().body)

    def test_edit_form_flip_to_denied_sends(self):
        req = self.submit_request()
        n = len(mail.outbox)
        self._edit(req, 'denied')
        self.assertEqual(len(mail.outbox), n + 1)
        self.assertIn('DENIED', self.last_email().body)

    def test_edit_without_status_change_sends_nothing(self):
        req = self.submit_request()
        self.approve(req)
        n = len(mail.outbox)
        self._edit(req, 'approved')   # still approved — just an edit
        self.assertEqual(len(mail.outbox), n)

    def test_cancel_sends_nothing(self):
        req = self.submit_request()
        n = len(mail.outbox)
        self.client.post(f'/time-off/{req.pk}/cancel/')
        self.assertEqual(len(mail.outbox), n)


# ─── 4. Locum-assigned email ─────────────────────────────────────────────────

class LocumAssignedEmailTests(EmailTestBase):

    def approved_request(self, start=MON, end=WED):
        req = self.submit_request(self.nroc_doc, start=start, end=end)
        self.client.post(f'/time-off/{req.pk}/approve/')
        return req

    def test_assign_locum_page_sends_one_summary_email(self):
        req = self.approved_request()
        n = len(mail.outbox)
        self.client.post(f'/time-off/{req.pk}/assign-locum/', {
            'mode_2026-10-05': 'locum', 'locum_2026-10-05': self.locum.pk,
            'clinic_2026-10-05': self.clinic_a.pk, 'hours_2026-10-05': '8',
            'mode_2026-10-06': 'locum', 'locum_2026-10-06': self.locum.pk,
            'clinic_2026-10-06': self.clinic_b.pk, 'hours_2026-10-06': '4.5',
        })
        self.assertEqual(len(mail.outbox), n + 1)   # ONE email for both days
        m = self.last_email()
        self.assertEqual(m.subject, 'Locum Assigned — Dr. Lou Cummings (2 days)')
        self.assertIn('Covering for: Dr. Nina North', m.body)
        self.assertIn('Clinics:      Clinic Alpha, Clinic Beta', m.body)
        self.assertIn('Mon, Oct 05, 2026:  Dr. Lou Cummings at Clinic Alpha '
                      '(covering Dr. North) — 8 hrs', m.body)
        self.assertIn('Tue, Oct 06, 2026:  Dr. Lou Cummings at Clinic Beta '
                      '(covering Dr. North) — 4.5 hrs', m.body)
        self.assertIn('Assigned by: Ada Min', m.body)

    def test_two_locums_subject(self):
        req = self.approved_request()
        self.client.post(f'/time-off/{req.pk}/assign-locum/', {
            'mode_2026-10-05': 'locum', 'locum_2026-10-05': self.locum.pk,
            'clinic_2026-10-05': self.clinic_a.pk, 'hours_2026-10-05': '8',
            'mode_2026-10-06': 'locum', 'locum_2026-10-06': self.locum2.pk,
            'clinic_2026-10-06': self.clinic_a.pk, 'hours_2026-10-06': '8',
        })
        self.assertEqual(self.last_email().subject,
                         'Locum Assigned — 2 locums (2 days)')

    def test_no_coverage_days_do_not_email(self):
        req = self.approved_request()
        n = len(mail.outbox)
        self.client.post(f'/time-off/{req.pk}/assign-locum/', {
            'mode_2026-10-05': 'none',
            'no_coverage_reason_2026-10-05': 'half day',
            'clinic_2026-10-05': self.clinic_a.pk,
        })
        self.assertEqual(len(mail.outbox), n)

    def test_blank_save_does_not_email(self):
        req = self.approved_request()
        n = len(mail.outbox)
        self.client.post(f'/time-off/{req.pk}/assign-locum/', {})
        self.assertEqual(len(mail.outbox), n)

    def test_mixed_save_emails_only_locum_days(self):
        req = self.approved_request()
        self.client.post(f'/time-off/{req.pk}/assign-locum/', {
            'mode_2026-10-05': 'locum', 'locum_2026-10-05': self.locum.pk,
            'clinic_2026-10-05': self.clinic_a.pk, 'hours_2026-10-05': '8',
            'mode_2026-10-06': 'none',
            'no_coverage_reason_2026-10-06': 'shift swapped',
            'clinic_2026-10-06': self.clinic_a.pk,
        })
        m = self.last_email()
        self.assertIn('(1 day)', m.subject)
        self.assertIn('Oct 05', m.body)
        self.assertNotIn('Oct 06', m.body.split('Assigned by')[0].split('Clinics:')[1])

    def test_clinics_page_single_day_assignment_emails(self):
        n = len(mail.outbox)
        self.client.post('/clinics/assign-day/', {
            'date': MON.isoformat(), 'clinic': self.clinic_b.pk,
            'physician': self.psa_doc.pk, 'locum': self.locum.pk, 'hours': '6',
        })
        self.assertEqual(len(mail.outbox), n + 1)
        m = self.last_email()
        self.assertEqual(m.subject, 'Locum Assigned — Dr. Lou Cummings (1 day)')
        self.assertIn('Covering for: Dr. Paul South', m.body)
        self.assertIn('Clinics:      Clinic Beta', m.body)
        self.assertIn('— 6 hrs', m.body)

    def test_add_coverage_form_emails(self):
        n = len(mail.outbox)
        resp = self.client.post('/coverage/add/', {
            'clinic': self.clinic_c.pk,
            'covering_physician': self.locum.pk,
            'covered_physician': self.nroc_doc.pk,
            'date': WED.isoformat(), 'hours': '8', 'notes': '',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(len(mail.outbox), n + 1)
        self.assertIn('Clinics:      Clinic Gamma', self.last_email().body)

    def test_locum_email_goes_to_main_list_only(self):
        self.client.post('/clinics/assign-day/', {
            'date': MON.isoformat(), 'clinic': self.clinic_a.pk,
            'physician': self.nroc_doc.pk, 'locum': self.locum.pk, 'hours': '8',
        })
        self.assertEqual(sorted(self.last_email().to),
                         ['manager@test.org', 'office@test.org'])

    def test_updating_existing_assignment_renotifies(self):
        req = self.approved_request()
        day = {'mode_2026-10-05': 'locum', 'locum_2026-10-05': self.locum.pk,
               'clinic_2026-10-05': self.clinic_a.pk, 'hours_2026-10-05': '8'}
        self.client.post(f'/time-off/{req.pk}/assign-locum/', day)
        n = len(mail.outbox)
        day['locum_2026-10-05'] = self.locum2.pk    # swap the locum
        self.client.post(f'/time-off/{req.pk}/assign-locum/', day)
        self.assertEqual(len(mail.outbox), n + 1)
        self.assertIn('Dr. Lena Kovacs', self.last_email().body)


# ─── 5. Gating & safety ──────────────────────────────────────────────────────

class GatingAndSafetyTests(EmailTestBase):

    @override_settings(SEND_NOTIFICATION_EMAILS=False,
                       EMAIL_BACKEND='django.core.mail.backends.console.EmailBackend')
    def test_switch_off_uses_console_backend_and_still_saves(self):
        # Nothing lands in an SMTP outbox; the request itself still succeeds.
        req = self.submit_request()
        self.assertEqual(req.status, 'pending')
        self.assertEqual(len(mail.outbox), 0)   # locmem outbox untouched

    @override_settings(TIME_OFF_NOTIFICATION_RECIPIENTS=[])
    def test_no_recipients_but_group_admin_still_notified(self):
        # Empty main list: NROC submission still reaches the group admins…
        self.submit_request(self.nroc_doc)
        self.assertEqual(sorted(self.last_email().to),
                         ['larry_linked@test.org', 'nroc_admin@test.org'])

    @override_settings(TIME_OFF_NOTIFICATION_RECIPIENTS=[])
    def test_no_recipients_at_all_sends_nothing(self):
        # …but a decision email (main list only) sends nothing at all.
        req = self.submit_request()
        n = len(mail.outbox)
        self.client.post(f'/time-off/{req.pk}/approve/')
        self.assertEqual(len(mail.outbox), n)
        req.refresh_from_db()
        self.assertEqual(req.status, 'approved')   # approval still worked

    def test_mail_server_failure_never_blocks_the_request(self):
        with mock.patch('django.core.mail.EmailMessage.send',
                        side_effect=Exception('SMTP down')):
            req = self.submit_request()            # no exception raised
            self.assertEqual(req.status, 'pending')
            resp = self.client.post(f'/time-off/{req.pk}/approve/')
            self.assertEqual(resp.status_code, 302)
            req.refresh_from_db()
            self.assertEqual(req.status, 'approved')

    def test_full_lifecycle_email_count(self):
        """Submit → approve → assign 2 locum days = exactly 3 emails."""
        req = self.submit_request(self.nroc_doc, start=MON, end=TUE)
        self.client.post(f'/time-off/{req.pk}/approve/')
        self.client.post(f'/time-off/{req.pk}/assign-locum/', {
            'mode_2026-10-05': 'locum', 'locum_2026-10-05': self.locum.pk,
            'clinic_2026-10-05': self.clinic_a.pk, 'hours_2026-10-05': '8',
            'mode_2026-10-06': 'locum', 'locum_2026-10-06': self.locum.pk,
            'clinic_2026-10-06': self.clinic_a.pk, 'hours_2026-10-06': '8',
        })
        self.assertEqual(len(mail.outbox), 3)
        subjects = [m.subject.split(' — ')[0] for m in mail.outbox]
        self.assertEqual(subjects, ['New Time Off Request', 'Time Off Approved',
                                    'Locum Assigned'])
