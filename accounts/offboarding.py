import json
import os
from secrets import compare_digest

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import BascolIdentity


@csrf_exempt
@never_cache
@require_POST
def offboard(request):
    secret = os.environ.get("PORTAL_OFFBOARD_SECRET", "")
    if len(secret) < 32 or not compare_digest(request.headers.get("Authorization", "").encode(),
                                              ("Bearer " + secret).encode()):
        return JsonResponse({"error": "forbidden"}, status=403)
    try:
        data = json.loads(request.body)
        issuer, subject, code = data["issuer"], data["subject"], data["code"]
        if issuer != settings.BASCOL_OIDC_ISSUER or not all(
            isinstance(value, str) and 0 < len(value.strip()) <= 255 for value in (subject, code)
        ):
            raise ValueError
    except (ValueError, TypeError, KeyError):
        return JsonResponse({"error": "invalid_identity"}, status=400)
    with transaction.atomic():
        link = BascolIdentity.objects.select_for_update().select_related("user").filter(
            issuer=issuer, subject=subject).first()
        users = get_user_model().objects
        if link is None:
            if users.filter(profile__personnel_code=code).exists() or users.filter(username=code).exists():
                return JsonResponse({"error": "local_identity_requires_review"}, status=409)
            return JsonResponse({"status": "no_link"})
        user = link.user
        if user.is_staff or user.is_superuser or user.profile.role in ("super_admin", "system_admin"):
            return JsonResponse({"error": "protected"}, status=409)
        if user.is_active or user.has_usable_password():
            user.is_active = False
            user.set_unusable_password()
            user.save(update_fields=["is_active", "password"])
        link.enabled = False
        link.save(update_fields=["enabled"])
        user.profile.is_active = False
        user.profile.save(update_fields=["is_active"])
    return JsonResponse({"status": "revoked"})
