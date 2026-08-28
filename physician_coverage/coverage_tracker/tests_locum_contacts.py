"""Access tests for the Locum Contacts page.

Admins: full access (view + edit).
PSA physician administrators (scope 'psa' or 'all'): read-only view.
NROC physician admins, physicians, nursing: no access.
"""
from django.contrib.auth.models import User
from django.test import TestCase

from .models import Physician, UserProfile


class LocumContactsAccessTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.locum = Physician.objects.create(
            first_name='Lou', last_name='Cummings', email='lou@t.org',
            physician_type='locum', phone='555-0100')

        def make(username, role, scope):
            u = User.objects.create_user(username, password='pw')
            UserProfile.objects.create(user=u, role=role, scope=scope)
            return u

        cls.admin = make('admin', 'admin', 'all')
        cls.psa_padmin = make('psa_padmin', 'physician_admin', 'psa')
        cls.all_padmin = make('all_padmin', 'physician_admin', 'all')
        cls.nroc_padmin = make('nroc_padmin', 'physician_admin', 'nroc')
        cls.psa_phys = make('psa_phys', 'physician', 'psa')
        cls.nurse = make('nurse', 'nursing', 'all')

    def _get(self, user):
        self.client.login(username=user.username, password='pw')
        return self.client.get('/locum-contacts/')

    def _post(self, user, **overrides):
        self.client.login(username=user.username, password='pw')
        data = {'locum_pk': self.locum.pk, 'phone': '555-9999',
                'email': 'lou@t.org', 'contact_notes': 'changed'}
        data.update(overrides)
        return self.client.post('/locum-contacts/', data)

    # -- viewing -----------------------------------------------------------
    def test_admin_can_view_and_sees_edit_controls(self):
        r = self._get(self.admin)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Lou Cummings')
        self.assertContains(r, 'class="btn btn-ghost btn-sm edit-btn"')

    def test_psa_physician_admin_can_view_read_only(self):
        r = self._get(self.psa_padmin)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Lou Cummings')
        self.assertContains(r, '555-0100')
        self.assertNotContains(r, 'class="btn btn-ghost btn-sm edit-btn"')
        self.assertNotContains(r, 'type="submit"')
        # no link into the admin-only physician detail page
        self.assertNotContains(r, f'/physicians/{self.locum.pk}/')

    def test_all_scope_physician_admin_can_view(self):
        self.assertEqual(self._get(self.all_padmin).status_code, 200)

    def test_nroc_physician_admin_denied(self):
        r = self._get(self.nroc_padmin)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.url, '/time-off/')

    def test_physician_denied(self):
        self.assertEqual(self._get(self.psa_phys).status_code, 302)

    def test_nursing_denied(self):
        r = self._get(self.nurse)
        self.assertEqual(r.status_code, 302)

    def test_anonymous_redirected_to_login(self):
        r = self.client.get('/locum-contacts/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/login/', r.url)

    # -- editing -----------------------------------------------------------
    def test_admin_can_edit(self):
        r = self._post(self.admin)
        self.assertEqual(r.status_code, 302)
        self.locum.refresh_from_db()
        self.assertEqual(self.locum.phone, '555-9999')
        self.assertEqual(self.locum.contact_notes, 'changed')

    def test_psa_physician_admin_cannot_edit(self):
        r = self._post(self.psa_padmin)
        self.assertEqual(r.status_code, 302)
        self.locum.refresh_from_db()
        self.assertEqual(self.locum.phone, '555-0100')
        self.assertEqual(self.locum.contact_notes, '')

    # -- nav ---------------------------------------------------------------
    def test_nav_link_shown_for_psa_physician_admin(self):
        self.client.login(username='psa_padmin', password='pw')
        r = self.client.get('/time-off/')
        self.assertContains(r, 'href="/locum-contacts/"')

    def test_nav_link_hidden_for_nroc_physician_admin(self):
        self.client.login(username='nroc_padmin', password='pw')
        r = self.client.get('/time-off/')
        self.assertNotContains(r, 'href="/locum-contacts/"')
