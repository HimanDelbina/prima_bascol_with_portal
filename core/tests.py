from django.test import TestCase, RequestFactory
from core.middleware import extract_client_ip, ThreadLocalRequestMiddleware, get_current_ip

class ClientIPExtractionTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_direct_connection(self):
        req = self.factory.get("/")
        req.META["REMOTE_ADDR"] = "192.168.1.45"
        self.assertEqual(extract_client_ip(req), "192.168.1.45")

    def test_x_real_ip_overrides_remote_addr_gateway(self):
        req = self.factory.get("/")
        req.META["REMOTE_ADDR"] = "192.168.1.1"  # Gateway
        req.META["HTTP_X_REAL_IP"] = "192.168.1.88"  # Internal workstation
        self.assertEqual(extract_client_ip(req), "192.168.1.88")

    def test_x_forwarded_for_disambiguates_gateway_first(self):
        req = self.factory.get("/")
        req.META["HTTP_X_FORWARDED_FOR"] = "192.168.1.1, 192.168.1.50"
        self.assertEqual(extract_client_ip(req), "192.168.1.50")

    def test_x_forwarded_for_disambiguates_gateway_last(self):
        req = self.factory.get("/")
        req.META["HTTP_X_FORWARDED_FOR"] = "192.168.1.50, 192.168.1.1"
        self.assertEqual(extract_client_ip(req), "192.168.1.50")

    def test_docker_bridge_gateway_disambiguated(self):
        req = self.factory.get("/")
        req.META["REMOTE_ADDR"] = "172.17.0.1"  # Docker gateway
        req.META["HTTP_X_FORWARDED_FOR"] = "172.17.0.1, 192.168.10.15"
        self.assertEqual(extract_client_ip(req), "192.168.10.15")

    def test_cloudflare_connecting_ip_priority(self):
        req = self.factory.get("/")
        req.META["HTTP_CF_CONNECTING_IP"] = "5.120.30.40"
        req.META["HTTP_X_FORWARDED_FOR"] = "192.168.1.1, 172.17.0.1"
        self.assertEqual(extract_client_ip(req), "5.120.30.40")

    def test_middleware_stores_in_thread_locals(self):
        req = self.factory.get("/")
        req.META["HTTP_X_REAL_IP"] = "192.168.1.99"
        
        captured_ip = None
        def mock_view(request):
            nonlocal captured_ip
            captured_ip = get_current_ip()
            from django.http import HttpResponse
            return HttpResponse("OK")
            
        middleware = ThreadLocalRequestMiddleware(mock_view)
        middleware(req)
        self.assertEqual(captured_ip, "192.168.1.99")
