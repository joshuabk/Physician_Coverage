"""
Tests for the physician detail page (Physicians tab → a physician).

Run with:
    python manage.py test coverage_tracker.tests_physician_detail

Cancelled time-off requests are hidden from the Time Off History table;
every other status is still listed.

A locum's detail page lists coverage assignments for the current year
and the next year (assignments in other years are left out).
"""
from datetime import date

from django.contrib.auth.models import User
from django.test import TestCase

from .models import (
    Clinic, CoverageAssignment, Physician, TimeOffRequest, UserProfile,
)


class PhysicianDetailTimeOffHistoryTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.phys = Physician.objects.create(
            first_name='Nina', last_name='North', email='nina@t.org',
            physician_type='regular')
        cls.reqs = {}
        for i, status in enumerate(['pending', 'approved', 'denied', 'cancelled']):
            d = date(2026, 10, 5 + i * 7)
            cls.reqs[status] = TimeOffRequest.objects.create(
                physician=cls.phys, start_date=d, end_date=d,
                request_type='vacation', status=status)
        u = User.objects.create_user('admin', password='pw')
        UserProfile.objects.create(user=u, role='admin', scope='all')
        cls.admin = u

    def test_cancelled_requests_hidden_from_history(self):
        self.client.login(username='admin', password='pw')
        resp = self.client.get(f'/physicians/{self.phys.pk}/')
        self.assertEqual(resp.status_code, 200)
        shown = list(resp.context['time_off_requests'])
        self.assertNotIn(self.reqs['cancelled'], shown)
        for status in ('pending', 'approved', 'denied'):
            self.assertIn(self.reqs[status], shown)
        self.assertNotContains(resp, 'badge-cancelled">Cancelled')


class PhysicianDetailLocumAssignmentsTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.locum = Physician.objects.create(
            first_name='Lena', last_name='Locum', email='lena@t.org',
            physician_type='locum', hourly_rate=100)
        cls.clinic = Clinic.objects.create(name='Midtown')
        cls.by_year = {}
        for yr in (2025, 2026, 2027, 2028):
            cls.by_year[yr] = CoverageAssignment.objects.create(
                clinic=cls.clinic, covering_physician=cls.locum,
                date=date(yr, 3, 15), hours=8)
        u = User.objects.create_user('admin2', password='pw')
        UserProfile.objects.create(user=u, role='admin', scope='all')

    def test_shows_current_and_next_year_assignments(self):
        self.client.login(username='admin2', password='pw')
        resp = self.client.get(f'/physicians/{self.locum.pk}/?year=2026')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['year'], 2026)
        self.assertEqual(resp.context['next_year'], 2027)
        self.assertEqual(list(resp.context['coverage_this_year']), [self.by_year[2026]])
        self.assertEqual(list(resp.context['coverage_next_year']), [self.by_year[2027]])
        self.assertContains(resp, 'Mar 15, 2026')
        self.assertContains(resp, 'Mar 15, 2027')
        self.assertNotContains(resp, 'Mar 15, 2025')
        self.assertNotContains(resp, 'Mar 15, 2028')

    def test_next_year_defaults_to_year_after_current(self):
        self.client.login(username='admin2', password='pw')
        resp = self.client.get(f'/physicians/{self.locum.pk}/')
        self.assertEqual(resp.context['next_year'], resp.context['year'] + 1)
        self.assertContains(resp, f"{resp.context['year']} &amp; {resp.context['next_year']}")
