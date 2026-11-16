import logging
import time
from functools import lru_cache

import jwt
from authlib.integrations.django_client import OAuth
from django.conf import settings
from django.contrib.auth import login, logout
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .models import BascolIdentity

logger = logging.getLogger(__name__)


def provider():
    issuer = settings.BASCOL_OIDC_ISSUER
    return OAuth().register(
        name="bascol", client_id=settings.BASCOL_OIDC_CLIENT_ID,
        client_secret=settings.BASCOL_OIDC_CLIENT_SECRET,
        server_metadata_url=issuer + "/.well-known/openid-configuration",
        client_kwargs={"scope": "openid profile roles", "code_challenge_method": "S256",
                       "token_endpoint_auth_method": "client_secret_basic", "timeout": 5},
    )


@lru_cache(maxsize=4)
def signing_keys(issuer):
    return jwt.PyJWKClient(issuer + "/protocol/openid-connect/certs", timeout=5)


def verify_access_token(token, subject):
    issuer = settings.BASCOL_OIDC_ISSUER
    client_id = settings.BASCOL_OIDC_CLIENT_ID
    key = signing_keys(issuer).get_signing_key_from_jwt(token).key
    claims = jwt.decode(token, key, algorithms=["RS256"], audience=client_id, issuer=issuer,
                        options={"require": ["iss", "aud", "exp", "iat", "sub", "azp"]})
    roles = claims.get("resource_access", {}).get(client_id, {}).get("roles", [])
    if claims["sub"] != subject or claims["azp"] != client_id or not isinstance(roles, list) or "bascol-user" not in roles:
        raise PermissionDenied()
    return claims


def eligible_identity(**filters):
    return BascolIdentity.objects.filter(
        enabled=True, user__is_active=True, user__profile__is_active=True,
        user__is_staff=False, user__is_superuser=False,
    ).exclude(user__profile__role__in=["super_admin", "system_admin"]).select_related("user").filter(**filters).first()


@never_cache
@require_GET
def start(request):
    if not settings.BASCOL_SSO_ENABLED:
        raise Http404
    request.session["bascol_sso_started"] = time.time()
    try:
        return provider().authorize_redirect(request, settings.BASCOL_OIDC_REDIRECT_URI)
    except Exception as exc:
        logger.warning("Bascol OIDC start failed: %s", type(exc).__name__)
        return HttpResponseBadRequest("ورود سازمانی فعلاً در دسترس نیست.")


@never_cache
@require_GET
def callback(request):
    if not settings.BASCOL_SSO_ENABLED:
        raise Http404
    if time.time() - request.session.pop("bascol_sso_started", 0) > 300 or not request.GET.get("code"):
        return HttpResponseBadRequest("درخواست ورود نامعتبر است. ورود را دوباره شروع کنید.")
    try:
        issuer = settings.BASCOL_OIDC_ISSUER
        client_id = settings.BASCOL_OIDC_CLIENT_ID
        tokens = provider().authorize_access_token(request, claims_options={
            "iss": {"essential": True, "value": issuer},
            "sub": {"essential": True}, "aud": {"essential": True},
        })
        claims = tokens.get("userinfo")
        if not claims or not tokens.get("id_token"):
            raise PermissionDenied()
        audiences = claims.get("aud")
        audiences = [audiences] if isinstance(audiences, str) else audiences
        if not isinstance(audiences, list) or client_id not in audiences:
            raise PermissionDenied()
        if claims.get("azp", client_id) != client_id or (len(audiences) > 1 and claims.get("azp") != client_id):
            raise PermissionDenied()
        access = verify_access_token(tokens["access_token"], claims["sub"])
        identity = eligible_identity(issuer=issuer, subject=claims["sub"])
        if identity is None:
            raise PermissionDenied()
    except (PermissionDenied, jwt.InvalidTokenError):
        raise PermissionDenied("این حساب سازمانی مجوز ورود به باسکول ندارد.")
    except Exception as exc:
        logger.warning("Bascol OIDC callback failed: %s", type(exc).__name__)
        return HttpResponseBadRequest("ورود سازمانی تأیید نشد. دوباره تلاش کنید.")
    login(request, identity.user, backend="django.contrib.auth.backends.ModelBackend")
    request.session["bascol_identity_id"] = identity.pk
    request.session["bascol_identity_expires"] = access["exp"]
    return redirect(settings.LOGIN_REDIRECT_URL)


class BascolSSOMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        identity_id = request.session.get("bascol_identity_id")
        if identity_id and request.user.is_authenticated:
            if not settings.BASCOL_SSO_ENABLED:
                logout(request)
                raise PermissionDenied()
            if request.path_info == reverse("accounts:logout"):
                return self.get_response(request)
            if not eligible_identity(pk=identity_id, user_id=request.user.pk, issuer=settings.BASCOL_OIDC_ISSUER):
                logout(request)
                raise PermissionDenied("دسترسی حساب سازمانی غیرفعال شده است.")
            if time.time() >= request.session.get("bascol_identity_expires", 0):
                logout(request)
                if request.method not in ("GET", "HEAD"):
                    raise PermissionDenied("اعتبار ورود پایان یافت. عملیات ثبت نشد.")
                return redirect("accounts:oidc_login")
        return self.get_response(request)
