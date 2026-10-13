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


class PersianWordsTests(TestCase):
    def test_number_to_persian_words_basic(self):
        from core.jalali import number_to_persian_words
        self.assertEqual(number_to_persian_words(0), "صفر")
        self.assertEqual(number_to_persian_words("0"), "صفر")
        self.assertEqual(number_to_persian_words(1000), "یک هزار")
        self.assertEqual(number_to_persian_words(1250000), "یک میلیون و دویست و پنجاه هزار")
        self.assertEqual(number_to_persian_words("10,000,000"), "ده میلیون")
        self.assertEqual(number_to_persian_words("۵۰۰،۰۰۰"), "پانصد هزار")
        self.assertEqual(number_to_persian_words(None), "")
        self.assertEqual(number_to_persian_words(""), "")

    def test_persian_words_template_filter(self):
        from core.templatetags.bascol_tags import persian_words_filter
        self.assertEqual(persian_words_filter(1250000), "یک میلیون و دویست و پنجاه هزار")
        self.assertEqual(persian_words_filter(None), "")
        self.assertEqual(persian_words_filter(""), "")

