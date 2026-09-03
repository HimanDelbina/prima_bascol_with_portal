from django.test import TestCase
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from rest_framework import status
from accounts.models import RoleChoices, UserProfile


class AuthAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="operator_test",
            password="password123",
            first_name="علی",
            last_name="رضایی"
        )
        self.user.profile.role = RoleChoices.WEIGHBRIDGE_OPERATOR
        self.user.profile.mobile = "09123456789"
        self.user.profile.save()

    def test_obtain_token_success(self):
        response = self.client.post("/api/v1/auth/token/", {
            "username": "operator_test",
            "password": "password123"
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)
        self.assertIn("user", response.data)
        self.assertEqual(response.data["user"]["username"], "operator_test")
        self.assertEqual(response.data["user"]["role"]["code"], RoleChoices.WEIGHBRIDGE_OPERATOR)
        self.assertIn("ticket.create", response.data["user"]["permissions"])

    def test_obtain_token_invalid_password(self):
        response = self.client.post("/api/v1/auth/token/", {
            "username": "operator_test",
            "password": "wrong_password"
        })
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_refresh_token(self):
        token_res = self.client.post("/api/v1/auth/token/", {
            "username": "operator_test",
            "password": "password123"
        })
        refresh_token = token_res.data["refresh"]

        refresh_res = self.client.post("/api/v1/auth/token/refresh/", {
            "refresh": refresh_token
        })
        self.assertEqual(refresh_res.status_code, status.HTTP_200_OK)
        self.assertIn("access", refresh_res.data)

    def test_verify_token(self):
        token_res = self.client.post("/api/v1/auth/token/", {
            "username": "operator_test",
            "password": "password123"
        })
        access_token = token_res.data["access"]

        verify_res = self.client.post("/api/v1/auth/token/verify/", {
            "token": access_token
        })
        self.assertEqual(verify_res.status_code, status.HTTP_200_OK)

    def test_current_user_me(self):
        token_res = self.client.post("/api/v1/auth/token/", {
            "username": "operator_test",
            "password": "password123"
        })
        access_token = token_res.data["access"]

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")
        me_res = self.client.get("/api/v1/auth/me/")
        self.assertEqual(me_res.status_code, status.HTTP_200_OK)
        self.assertEqual(me_res.data["username"], "operator_test")
        self.assertEqual(me_res.data["full_name"], "علی رضایی")
        self.assertEqual(me_res.data["mobile"], "09123456789")

    def test_logout_blacklist(self):
        token_res = self.client.post("/api/v1/auth/token/", {
            "username": "operator_test",
            "password": "password123"
        })
        access_token = token_res.data["access"]
        refresh_token = token_res.data["refresh"]

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")
        logout_res = self.client.post("/api/v1/auth/logout/", {
            "refresh": refresh_token
        })
        self.assertEqual(logout_res.status_code, status.HTTP_200_OK)
        self.assertTrue(logout_res.data["success"])

        # Try to refresh using blacklisted token
        refresh_again = self.client.post("/api/v1/auth/token/refresh/", {
            "refresh": refresh_token
        })
        self.assertEqual(refresh_again.status_code, status.HTTP_401_UNAUTHORIZED)
