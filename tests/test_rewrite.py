import importlib.util
import os
from pathlib import Path
import unittest

from aiohttp.test_utils import TestClient, TestServer

ROOT = Path(__file__).resolve().parents[1]
os.environ["OPTIONS_PATH"] = str(Path(__file__).with_name("options.json"))
MODULE = ROOT / "unifi_protect_ingress/rootfs/opt/unifi-protect-ingress/proxy.py"
spec = importlib.util.spec_from_file_location("protect_proxy", MODULE)
proxy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proxy)


class RewriteTests(unittest.TestCase):
    def test_public_https_url_gets_start_path(self):
        original = proxy.PUBLIC_URL
        try:
            proxy.PUBLIC_URL = "https://protect.example.com"
            self.assertEqual(
                proxy.public_entry_url(),
                "https://protect.example.com/protect/",
            )
        finally:
            proxy.PUBLIC_URL = original

    def test_public_url_must_use_https(self):
        original = proxy.PUBLIC_URL
        try:
            proxy.PUBLIC_URL = "http://protect.example.com"
            with self.assertRaises(ValueError):
                proxy.public_entry_url()
        finally:
            proxy.PUBLIC_URL = original

    def test_local_ingress_wrapper_uses_current_ha_hostname(self):
        original = proxy.PUBLIC_ENTRY
        try:
            proxy.PUBLIC_ENTRY = ""
            response = proxy.embedded_wrapper()
            body = response.body.decode("utf-8")
            self.assertIn("location.hostname+':8099/__ha_auth?token='", body)
            self.assertIn("/protect/", body)
        finally:
            proxy.PUBLIC_ENTRY = original

    def test_back_button_can_be_enabled_with_ha_target(self):
        original_enabled = proxy.BACK_BUTTON_ENABLED
        original_target = proxy.BACK_BUTTON_TARGET
        try:
            proxy.BACK_BUTTON_ENABLED = True
            proxy.BACK_BUTTON_TARGET = "/dashboard-camera/0"
            body = proxy.embedded_wrapper().body.decode("utf-8")
            self.assertIn('id="ha-back"', body)
            self.assertIn('window.open("/dashboard-camera/0",\'_top\')', body)
        finally:
            proxy.BACK_BUTTON_ENABLED = original_enabled
            proxy.BACK_BUTTON_TARGET = original_target

    def test_back_button_is_absent_when_disabled(self):
        original = proxy.BACK_BUTTON_ENABLED
        try:
            proxy.BACK_BUTTON_ENABLED = False
            body = proxy.embedded_wrapper().body.decode("utf-8")
            self.assertNotIn('id="ha-back"', body)
        finally:
            proxy.BACK_BUTTON_ENABLED = original

    def test_back_button_target_accepts_paths_and_http_urls(self):
        self.assertEqual("/lovelace/home", proxy.normalize_back_button_target("lovelace/home"))
        self.assertEqual("/", proxy.normalize_back_button_target(""))
        self.assertEqual(
            "https://ha.example.com/dashboard/0",
            proxy.normalize_back_button_target("https://ha.example.com/dashboard/0"),
        )
        self.assertEqual(
            "/evil.example/dashboard",
            proxy.normalize_back_button_target("//evil.example/dashboard"),
        )

    def test_absolute_protect_paths_are_scoped(self):
        body = b'<html><head></head><body><script src="/proxy/protect/app.js"></script></body></html>'
        result = proxy.rewrite_body(body, "text/html", "/api/hassio_ingress/token")
        self.assertIn(b'/api/hassio_ingress/token/proxy/protect/app.js', result)
        self.assertIn(b'XMLHttpRequest', result)

    def test_redirect_is_scoped(self):
        self.assertEqual(
            proxy.rewrite_location("https://192.0.2.1/protect/login", "/api/hassio_ingress/token"),
            "/api/hassio_ingress/token/protect/login",
        )

    def test_unifi_browser_history_gets_ingress_basename(self):
        source = b'e.basename?l(s(e.basename)):""'
        result = proxy.rewrite_body(source, "application/javascript", "/api/hassio_ingress/token")
        self.assertIn(b'e.basename?l(s(e.basename)):"/api/hassio_ingress/token"', result)

    def test_rspack_lazy_chunks_use_ingress_public_path(self):
        source = b'p.p="/",p.rv=()=>"1.7.5"'
        result = proxy.rewrite_body(source, "application/javascript", "/api/hassio_ingress/token")
        self.assertIn(b'p.p="/api/hassio_ingress/token/"', result)

    def test_javascript_routes_are_not_double_prefixed(self):
        source = b'const route="/protect/dashboard"'
        result = proxy.rewrite_body(source, "application/javascript", "/api/hassio_ingress/token")
        self.assertEqual(source, result)

    def test_unifi_cdn_is_proxied_through_ingress(self):
        source = b'{"uiCdn":"https://cdn.pkg.svc.ui.com/unifi-protect-ui/7.2.36"}'
        result = proxy.rewrite_body(source, "application/json", "/api/hassio_ingress/token")
        self.assertIn(
            b'"uiCdn":"/api/hassio_ingress/token/_unifi_cdn/unifi-protect-ui/7.2.36"',
            result,
        )

    def test_protect_swai_history_gets_ingress_basename(self):
        source = b"const d=(0,i.zR)({basename:n})"
        result = proxy.rewrite_body(source, "application/javascript", "/api/hassio_ingress/token")
        self.assertIn(b'{basename:"/api/hassio_ingress/token/protect"}', result)

    def test_cookie_domain_removed_and_path_scoped(self):
        result = proxy.rewrite_cookie(
            "TOKEN=x; Domain=192.0.2.1; Path=/; Secure; HttpOnly", "/api/hassio_ingress/token"
        )
        self.assertNotIn("Domain=", result)
        self.assertIn("Path=/api/hassio_ingress/token/", result)

    def test_secure_cookie_is_downgraded_for_local_http(self):
        result = proxy.rewrite_cookie(
            "TOKEN=x; Path=/; Secure; HttpOnly; SameSite=None",
            "/api/hassio_ingress/token", False
        )
        self.assertNotIn("Secure", result)
        self.assertIn("HttpOnly", result)
        self.assertIn("SameSite=Lax", result)


class RootProxyAccessTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = TestClient(TestServer(proxy.create_app()))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    async def test_health_does_not_require_browser_cookie(self):
        response = await self.client.get("/health")
        self.assertEqual(200, response.status)

    async def test_direct_root_proxy_request_is_forbidden(self):
        response = await self.client.get("/protect/dashboard")
        self.assertEqual(403, response.status)

    async def test_ingress_bootstrap_issues_root_proxy_cookie(self):
        response = await self.client.get(
            "/__ha_auth",
            params={"token": proxy.ACCESS_TOKEN, "next": "/protect/dashboard"},
            allow_redirects=False,
        )
        self.assertEqual(302, response.status)
        self.assertEqual("/protect/dashboard", response.headers["Location"])
        cookie = response.headers["Set-Cookie"]
        self.assertIn(proxy.ROOT_AUTH_COOKIE + "=", cookie)
        self.assertIn("HttpOnly", cookie)

    async def test_ingress_bootstrap_rejects_wrong_token(self):
        response = await self.client.get(
            "/__ha_auth", params={"token": "wrong"}, allow_redirects=False
        )
        self.assertEqual(403, response.status)


if __name__ == "__main__":
    unittest.main()
