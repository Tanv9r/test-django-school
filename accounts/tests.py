from django.test import TestCase
from django.urls import reverse

from accounts.models import Role, User
from accounts.permissions import CAPABILITIES, has_capability
from core.models import AuditLog
from core.testing import PASSWORD, make_user


class AuthenticationTests(TestCase):
    def test_login_redirects_admin_to_admin_panel(self):
        make_user(Role.ADMIN, username="boss")
        response = self.client.post(reverse("accounts:login"), {"username": "boss", "password": PASSWORD}, follow=True)
        self.assertRedirects(response, reverse("adminpanel:overview"))

    def test_login_redirects_staff_to_staff_dashboard(self):
        make_user(Role.NURSE, username="nina")
        response = self.client.post(reverse("accounts:login"), {"username": "nina", "password": PASSWORD}, follow=True)
        self.assertRedirects(response, reverse("dashboard:index"))

    def test_failed_login_is_audited(self):
        self.client.post(reverse("accounts:login"), {"username": "ghost", "password": "wrong"})
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.LOGIN_FAILED).exists())

    def test_passwords_are_hashed(self):
        user = make_user(Role.DOCTOR)
        self.assertNotEqual(user.password, PASSWORD)
        self.assertTrue(user.check_password(PASSWORD))

    def test_anonymous_users_are_redirected_to_login(self):
        for url in ["/dashboard/", "/patients/", "/billing/invoices/", "/admin-panel/"]:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302, url)
            self.assertIn(reverse("accounts:login"), response["Location"])

    def test_logout_requires_post(self):
        self.client.force_login(make_user())
        self.assertEqual(self.client.get(reverse("accounts:logout")).status_code, 405)
        self.assertEqual(self.client.post(reverse("accounts:logout")).status_code, 302)

    def test_superuser_is_always_admin(self):
        user = User.objects.create_superuser("root", "root@example.com", PASSWORD)
        self.assertEqual(user.role, Role.ADMIN)


class ProfileTests(TestCase):
    def test_user_can_update_own_profile_and_password(self):
        user = make_user(Role.PHARMACIST)
        self.client.force_login(user)
        response = self.client.post(reverse("accounts:profile"), {"first_name": "Pat", "last_name": "Pill", "email": "p@example.com", "phone": ""})
        self.assertRedirects(response, reverse("accounts:profile"))
        user.refresh_from_db()
        self.assertEqual(user.first_name, "Pat")
        response = self.client.post(reverse("accounts:password_change"), {
            "old_password": PASSWORD, "new_password1": "An0ther-Strong-Pass", "new_password2": "An0ther-Strong-Pass",
        })
        self.assertRedirects(response, reverse("accounts:profile"))
        user.refresh_from_db()
        self.assertTrue(user.check_password("An0ther-Strong-Pass"))


class RolePermissionTests(TestCase):
    def test_capability_matrix_core_rules(self):
        users = {role: make_user(role) for role in Role.values}
        self.assertTrue(has_capability(users[Role.ADMIN], "adminpanel_access"))
        self.assertFalse(has_capability(users[Role.DOCTOR], "adminpanel_access"))
        self.assertTrue(has_capability(users[Role.DOCTOR], "records_manage"))
        self.assertFalse(has_capability(users[Role.RECEPTIONIST], "records_view"))
        self.assertFalse(has_capability(users[Role.ACCOUNTANT], "records_view"))
        self.assertTrue(has_capability(users[Role.ACCOUNTANT], "billing_manage"))
        self.assertFalse(has_capability(users[Role.PHARMACIST], "billing_view"))
        self.assertTrue(has_capability(users[Role.PHARMACIST], "prescriptions_dispense"))

    def test_inactive_user_has_no_capabilities(self):
        user = make_user(Role.ADMIN, is_active=False)
        self.assertFalse(any(has_capability(user, cap) for cap in CAPABILITIES))

    def test_restricted_urls_return_403(self):
        cases = [
            (Role.RECEPTIONIST, "/records/"),
            (Role.ACCOUNTANT, "/records/prescriptions/"),
            (Role.NURSE, "/billing/invoices/"),
            (Role.PHARMACIST, "/patients/"),
            (Role.DOCTOR, "/admin-panel/"),
            (Role.RECEPTIONIST, "/admin-panel/users/"),
            (Role.ACCOUNTANT, "/pharmacy/new/"),
        ]
        for role, url in cases:
            self.client.force_login(make_user(role))
            self.assertEqual(self.client.get(url).status_code, 403, f"{role} -> {url}")

    def test_admin_panel_user_creation_and_role_change(self):
        admin = make_user(Role.ADMIN)
        self.client.force_login(admin)
        response = self.client.post(reverse("adminpanel:user_create"), {
            "username": "newnurse", "first_name": "New", "last_name": "Nurse", "email": "", "phone": "",
            "role": Role.NURSE, "is_active": "on", "password1": "Very-Strong-Pass1", "password2": "Very-Strong-Pass1",
        })
        self.assertEqual(response.status_code, 302)
        created = User.objects.get(username="newnurse")
        self.assertEqual(created.role, Role.NURSE)
        self.assertTrue(created.check_password("Very-Strong-Pass1"))

    def test_last_admin_cannot_demote_self(self):
        admin = make_user(Role.ADMIN, username="only_admin")
        self.client.force_login(admin)
        self.client.post(reverse("adminpanel:user_edit", args=[admin.pk]), {
            "username": "only_admin", "first_name": "A", "last_name": "B", "email": "", "phone": "", "role": Role.NURSE, "is_active": "on",
        })
        admin.refresh_from_db()
        self.assertEqual(admin.role, Role.ADMIN)
