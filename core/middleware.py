import threading

_thread_locals = threading.local()

def get_current_user():
    return getattr(_thread_locals, "user", None)

def get_current_ip():
    return getattr(_thread_locals, "ip_address", "127.0.0.1")

class ThreadLocalRequestMiddleware:
    """Middleware to capture current user and client IP for automatic audit logging."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        _thread_locals.user = getattr(request, "user", None) if request.user.is_authenticated else None
        
        # Get client IP
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            ip = x_forwarded_for.split(",")[0].strip()
        else:
            ip = request.META.get("REMOTE_ADDR", "127.0.0.1")
        _thread_locals.ip_address = ip

        response = self.get_response(request)
        
        # Clear thread locals
        _thread_locals.user = None
        _thread_locals.ip_address = None
        
        return response
