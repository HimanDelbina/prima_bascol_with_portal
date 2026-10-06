from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User

class AuthWorkflowTests(TestCase):
    def setUp(self):
        self.username = "testoperator"
        self.password = "Secr3tP@ssword!"
        self.user = User.objects.create_user(
            username=self.username,
            password=self.password,
            first_name="کاربر",
            last_name="تست"
        )
        self.client = Client()

    def test_login_page_renders_cleanly_for_anonymous_user(self):
        """Login page should render status 200 with login form for anonymous users."""
        response = self.client.get(reverse("accounts:login"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/login.html")
        self.assertContains(response, "ورود به سامانه")
        self.assertContains(response, 'name="username"')
        self.assertContains(response, 'name="password"')

    def test_login_success(self):
        """Valid credentials should log in and redirect to dashboard."""
        response = self.client.post(reverse("accounts:login"), {
            "username": self.username,
            "password": self.password
        })
        self.assertRedirects(response, reverse("dashboard:index"))

    def test_login_invalid_credentials(self):
        """Invalid credentials should show error message."""
        response = self.client.post(reverse("accounts:login"), {
            "username": self.username,
            "password": "wrongpassword"
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "نام کاربری یا رمز عبور اشتباه است")

    def test_logout_redirects_to_login(self):
        """Logout should terminate session and redirect to login page."""
        self.client.login(username=self.username, password=self.password)
        response = self.client.get(reverse("accounts:logout"))
        self.assertRedirects(response, reverse("accounts:login"))

    def test_authenticated_user_accessing_login_redirects(self):
        """Already authenticated user accessing login page should redirect to dashboard."""
        self.client.login(username=self.username, password=self.password)
        response = self.client.get(reverse("accounts:login"))
        self.assertRedirects(response, reverse("dashboard:index"))


class RevokedPermissionsPolicyTests(TestCase):
    """
    Validates that weighbridge_manager, weighbridge_operator, and viewer
    are completely forbidden from accessing:
    1. Audit Log (audit:audit_list)
    2. General Settings (core:settings)
    3. Backups (core:backup)
    4. Smart Monitoring (monitoring:dashboard, monitoring:alert_list)
    5. User Management (accounts:user_list)
    6. Executive Management Reports (management:dashboard)
    """

    def setUp(self):
        self.client = Client()

        # Target restricted roles
        self.wb_manager = User.objects.create_user(username="wb_mgr", password="password123")
        self.wb_manager.profile.role = "weighbridge_manager"
        self.wb_manager.profile.save()

        self.wb_operator = User.objects.create_user(username="wb_op", password="password123")
        self.wb_operator.profile.role = "weighbridge_operator"
        self.wb_operator.profile.save()

        self.viewer = User.objects.create_user(username="wb_view", password="password123")
        self.viewer.profile.role = "viewer"
        self.viewer.profile.save()

        # Authorized benchmark user
        self.superadmin = User.objects.create_superuser(username="superadmin_test", password="password123")

    def test_audit_log_access_forbidden(self):
        """Audit Log must be forbidden (redirected) for weighbridge manager, operator, and viewer."""
        for user in [self.wb_manager, self.wb_operator, self.viewer]:
            self.client.login(username=user.username, password="password123")
            response = self.client.get(reverse("audit:audit_list"))
            self.assertEqual(response.status_code, 302, f"{user.username} should be 302 on audit_list")
            self.assertRedirects(response, reverse("dashboard:index"))

        # Superadmin should have access
        self.client.login(username=self.superadmin.username, password="password123")
        response = self.client.get(reverse("audit:audit_list"))
        self.assertEqual(response.status_code, 200)

    def test_system_settings_and_backup_forbidden(self):
        """General settings and backups must be forbidden (redirected) for weighbridge manager, operator, and viewer."""
        for user in [self.wb_manager, self.wb_operator, self.viewer]:
            self.client.login(username=user.username, password="password123")
            
            res_settings = self.client.get(reverse("core:settings"))
            self.assertEqual(res_settings.status_code, 302, f"{user.username} should be 302 on settings")
            self.assertRedirects(res_settings, reverse("dashboard:index"))

            res_backup = self.client.get(reverse("core:backup"))
            self.assertEqual(res_backup.status_code, 302, f"{user.username} should be 302 on backup")
            self.assertRedirects(res_backup, reverse("dashboard:index"))

        # Superadmin should have access
        self.client.login(username=self.superadmin.username, password="password123")
        self.assertEqual(self.client.get(reverse("core:settings")).status_code, 200)
        self.assertEqual(self.client.get(reverse("core:backup")).status_code, 200)

    def test_user_management_forbidden(self):
        """User management must be forbidden (redirected) for weighbridge manager, operator, and viewer."""
        for user in [self.wb_manager, self.wb_operator, self.viewer]:
            self.client.login(username=user.username, password="password123")
            response = self.client.get(reverse("accounts:user_list"))
            self.assertEqual(response.status_code, 302, f"{user.username} should be 302 on user_list")
            self.assertRedirects(response, reverse("dashboard:index"))

        # Superadmin should have access
        self.client.login(username=self.superadmin.username, password="password123")
        self.assertEqual(self.client.get(reverse("accounts:user_list")).status_code, 200)

    def test_smart_monitoring_forbidden(self):
        """Smart monitoring dashboard and alerts must be forbidden (redirected) for weighbridge manager, operator, and viewer."""
        for user in [self.wb_manager, self.wb_operator, self.viewer]:
            self.client.login(username=user.username, password="password123")

            res_dash = self.client.get(reverse("monitoring:dashboard"))
            self.assertEqual(res_dash.status_code, 302, f"{user.username} should be 302 on monitoring:dashboard")
            self.assertRedirects(res_dash, reverse("dashboard:index"))

            res_alerts = self.client.get(reverse("monitoring:alert_list"))
            self.assertEqual(res_alerts.status_code, 302, f"{user.username} should be 302 on monitoring:alert_list")
            self.assertRedirects(res_alerts, reverse("dashboard:index"))

        # Superadmin should have access
        self.client.login(username=self.superadmin.username, password="password123")
        self.assertEqual(self.client.get(reverse("monitoring:dashboard")).status_code, 200)
        self.assertEqual(self.client.get(reverse("monitoring:alert_list")).status_code, 200)

    def test_executive_management_reports_forbidden(self):
        """Executive management reports must be unauthorized (302/redirect) for weighbridge manager, operator, and viewer."""
        for user in [self.wb_manager, self.wb_operator, self.viewer]:
            self.client.login(username=user.username, password="password123")

            res_mgmt = self.client.get(reverse("management:dashboard"))
            self.assertEqual(res_mgmt.status_code, 302, f"{user.username} should be redirected away from management:dashboard")

        # Superadmin should have access
        self.client.login(username=self.superadmin.username, password="password123")
        self.assertEqual(self.client.get(reverse("management:dashboard")).status_code, 200)
