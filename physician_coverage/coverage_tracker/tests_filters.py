"""
Tests for the physician filter on the Time Off page.

Run with:
    python manage.py test coverage_tracker.tests_filters

The filter is available to EVERY login, but the dropdown is scoped:
  - admins and nursing logins see both NROC and PSA physicians
  - NROC-scoped logins (physicians / physician admins) see NROC only
  - PSA-scoped logins see PSA only
Filtering by a physician outside your scope returns no rows rather than
leaking the other group's requests.
"""
from datetime import date

from django.contrib.auth.models import User
from django.test import TestCase

from .models import Physician, TimeOffRequest, UserProfile

MON, TUE = date(2026, 10, 5), date(2026, 10, 6)


class PhysicianFilterBase(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.nroc1 = Physician.objects.create(
            first_name='Nina', last_name='North', email='nina@t.org',
            physician_type='regular')
        cls.nroc2 = Physician.objects.create(
            first_name='Ned', last_name='Nolan', email='ned@t.org',
            physician_type='regular')
        cls.psa1 = Physician.objects.create(
            first_name='Paul', last_name='South', email='paul@t.org',
            physician_type='psa')
        cls.locum = Physician.objects.create(
            first_name='Lou', last_name='Cummings', email='lou@t.org',
            physician_type='locum')
        cls.inactive = Physician.objects.create(
            first_name='Iggy', last_name='Gone', email='iggy@t.org',
            physician_type='regular', is_active=False)

        for phys, status in [(cls.nroc1, 'approved'), (cls.nroc2, 'pending'),
                             (cls.psa1, 'approved')]:
            r = TimeOffRequest.objects.create(
                physician=phys, start_date=MON, end_date=TUE,
                request_type='vacation', status=status)
            r.ensure_day_rows()
            r.days.update(status=status if status != 'pending' else 'pending')

        def make(username, role, scope):
            u = User.objects.create_user(username, password='pw')
            UserProfile.objects.create(user=u, role=role, scope=scope)
            return u

        cls.admin = make('admin', 'admin', 'all')
        cls.nroc_phys = make('nroc_phys', 'physician', 'nroc')
        cls.psa_phys = make('psa_phys', 'physician', 'psa')
        cls.nroc_padmin = make('nroc_padmin', 'physician_admin', 'nroc')
        cls.nurse = make('nurse', 'nursing', 'all')

    def dropdown(self):
        return list(self.resp.context['physicians'])

    def rows(self):
        return [i['req'].physician for i in self.resp.context['enriched_requests']]

    def get(self, username, params=''):
        self.client.login(username=username, password='pw')
        self.resp = self.client.get(f'/time-off/{params}')
        return self.resp


class DropdownScopingTests(PhysicianFilterBase):

    def test_admin_dropdown_has_both_groups(self):
        self.get('admin')
        self.assertCountEqual(self.dropdown(), [self.nroc1, self.nroc2, self.psa1])

    def test_nroc_physician_dropdown_lists_nroc_only(self):
        self.get('nroc_phys')
        self.assertCountEqual(self.dropdown(), [self.nroc1, self.nroc2])

    def test_psa_physician_dropdown_lists_psa_only(self):
        self.get('psa_phys')
        self.assertCountEqual(self.dropdown(), [self.psa1])

    def test_nroc_physician_admin_dropdown_lists_nroc_only(self):
        self.get('nroc_padmin')
        self.assertCountEqual(self.dropdown(), [self.nroc1, self.nroc2])

    def test_nursing_dropdown_has_both_groups(self):
        self.get('nurse')
        self.assertCountEqual(self.dropdown(), [self.nroc1, self.nroc2, self.psa1])

    def test_dropdown_excludes_locums_and_inactive(self):
        self.get('admin')
        self.assertNotIn(self.locum, self.dropdown())
        self.assertNotIn(self.inactive, self.dropdown())

    def test_filter_form_renders_for_non_admin(self):
        resp = self.get('nroc_phys')
        self.assertContains(resp, 'name="physician"')
        # Status dropdown stays admin-only
        self.assertNotContains(resp, 'name="status"')

    def test_status_dropdown_still_renders_for_admin(self):
        resp = self.get('admin')
        self.assertContains(resp, 'name="status"')


class FilterBehaviorTests(PhysicianFilterBase):

    def test_admin_filter_narrows_to_one_physician(self):
        self.get('admin', f'?physician={self.nroc1.pk}')
        self.assertEqual(self.rows(), [self.nroc1])

    def test_nroc_physician_filter_narrows_to_one_physician(self):
        self.get('nroc_phys', f'?physician={self.nroc2.pk}')
        self.assertEqual(self.rows(), [self.nroc2])

    def test_unfiltered_nroc_view_shows_all_nroc_requests(self):
        self.get('nroc_phys')
        self.assertCountEqual(self.rows(), [self.nroc1, self.nroc2])

    def test_nroc_login_filtering_by_psa_physician_gets_nothing(self):
        """Out-of-scope filter must not leak the other group's requests."""
        self.get('nroc_phys', f'?physician={self.psa1.pk}')
        self.assertEqual(self.rows(), [])

    def test_psa_login_filtering_by_nroc_physician_gets_nothing(self):
        self.get('psa_phys', f'?physician={self.nroc1.pk}')
        self.assertEqual(self.rows(), [])

    def test_nursing_filter_narrows_and_stays_approved_only(self):
        self.get('nurse', f'?physician={self.nroc1.pk}')
        self.assertEqual(self.rows(), [self.nroc1])
        # nroc2's request is pending — filtered nursing view must not show it
        self.get('nurse', f'?physician={self.nroc2.pk}')
        self.assertEqual(self.rows(), [])

    def test_garbage_filter_value_is_harmless(self):
        resp = self.get('admin', '?physician=')
        self.assertEqual(resp.status_code, 200)
        resp = self.get('nroc_phys', '?physician=')
        self.assertEqual(resp.status_code, 200)
