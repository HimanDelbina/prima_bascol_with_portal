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
