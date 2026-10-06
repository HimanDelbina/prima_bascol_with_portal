import threading
import ipaddress

_thread_locals = threading.local()

def get_current_user():
    return getattr(_thread_locals, "user", None)

def get_current_ip():
    return getattr(_thread_locals, "ip_address", "127.0.0.1")

def is_valid_ip(ip_str: str) -> bool:
    """Validate IPv4 or IPv6 address string."""
    if not ip_str or not isinstance(ip_str, str):
        return False
    try:
        ipaddress.ip_address(ip_str.strip())
        return True
    except ValueError:
        return False

def is_probable_gateway_or_docker(ip_str: str) -> bool:
    """
    Check if an IP address is a typical router gateway or Docker bridge gateway.
    E.g. 172.17.0.1, 172.18.0.1, 192.168.1.1, 10.0.0.1, ending in .1 or .254 or loopback.
    """
    if not is_valid_ip(ip_str):
        return False
    try:
        ip_obj = ipaddress.ip_address(ip_str.strip())
        if ip_obj.is_loopback:
            return True
        if ip_obj.version == 4:
            octets = ip_str.strip().split(".")
            if len(octets) == 4 and (octets[3] == "1" or octets[3] == "254"):
                return True
        return False
    except ValueError:
        return False

def extract_client_ip(request) -> str:
    """
    Extract the real client IP from incoming request headers with support
    for reverse proxies (Nginx, Traefik, HAProxy, Cloudflare) and internal networks.
    Disambiguates proxy/gateway IPs in X-Forwarded-For chains to capture the real workstation IP.
    """
    meta = request.META

    # 1. Cloudflare / CDN headers (priority if present)
    cf_ip = meta.get("HTTP_CF_CONNECTING_IP")
    if cf_ip and is_valid_ip(cf_ip):
        return cf_ip.strip()

    true_client_ip = meta.get("HTTP_TRUE_CLIENT_IP")
    if true_client_ip and is_valid_ip(true_client_ip):
        return true_client_ip.strip()

    # 2. Collect candidate IPs from all standard proxy headers
    candidates = []

    # X-Real-IP (set by Nginx / reverse proxies)
    x_real_ip = meta.get("HTTP_X_REAL_IP")

    # X-Forwarded-For chain
    x_forwarded_for = meta.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        raw_ips = [ip.strip() for ip in x_forwarded_for.split(",") if ip.strip()]
        valid_ips = [ip for ip in raw_ips if is_valid_ip(ip)]
        candidates.extend(valid_ips)

    if x_real_ip and is_valid_ip(x_real_ip) and x_real_ip.strip() not in candidates:
        candidates.append(x_real_ip.strip())

    # Other common proxy headers
    for header in ("HTTP_X_CLIENT_IP", "HTTP_CLIENT_IP", "HTTP_X_CLUSTER_CLIENT_IP", "HTTP_FORWARDED_FOR"):
        val = meta.get(header)
        if val and is_valid_ip(val) and val.strip() not in candidates:
            candidates.append(val.strip())

    # Fallback: REMOTE_ADDR
    remote_addr = meta.get("REMOTE_ADDR")
    if remote_addr and is_valid_ip(remote_addr) and remote_addr.strip() not in candidates:
        candidates.append(remote_addr.strip())

    if not candidates:
        return remote_addr or "127.0.0.1"

    if len(candidates) == 1:
        return candidates[0]

    # If multiple candidates, prioritize the workstation IP (non-gateway/non-docker-bridge)
    non_gateways = [ip for ip in candidates if not is_probable_gateway_or_docker(ip)]
    if non_gateways:
        return non_gateways[0]

    return candidates[0]

class ThreadLocalRequestMiddleware:
    """Middleware to capture current user and client IP for automatic audit logging."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        _thread_locals.user = user if (user and getattr(user, "is_authenticated", False)) else None
        
        # Get client IP using multi-proxy/gateway aware extractor
        _thread_locals.ip_address = extract_client_ip(request)

        response = self.get_response(request)
        
        # Clear thread locals
        _thread_locals.user = None
        _thread_locals.ip_address = None
        
        return response
