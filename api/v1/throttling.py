from rest_framework.throttling import AnonRateThrottle, UserRateThrottle, ScopedRateThrottle


class CustomAnonRateThrottle(AnonRateThrottle):
    scope = 'anon'


class CustomUserRateThrottle(UserRateThrottle):
    scope = 'user'


class AuthRateThrottle(ScopedRateThrottle):
    scope = 'auth'


class ExportRateThrottle(ScopedRateThrottle):
    scope = 'export'
