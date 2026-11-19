import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings

from .offboarding import offboard
from .models import BascolIdentity


@override_settings(BASCOL_OIDC_ISSUER="https://test.example/realm")
@patch.dict("os.environ", {"PORTAL_OFFBOARD_SECRET": "s" * 32})
class OffboardTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="person", password="test-password")
        self.data = {"code": "001", "issuer": "https://test.example/realm", "subject": "subject-1"}
        self.link = BascolIdentity.objects.create(user=self.user, issuer=self.data["issuer"], subject="subject-1")

    def send(self, key):
        request = RequestFactory().post("/", json.dumps(self.data), content_type="application/json",
                                        HTTP_AUTHORIZATION="Bearer " + key)
        return offboard(request)

    def test_repeated_revocation_blocks_local_login(self):
        self.assertEqual(self.send("wrong").status_code, 403)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)
        for _ in range(2):
            self.assertEqual(self.send("s" * 32).status_code, 200)
        self.user.refresh_from_db()
        self.link.refresh_from_db()
        self.assertFalse(self.user.is_active)
        self.assertFalse(self.user.has_usable_password())
        self.assertFalse(self.link.enabled)
