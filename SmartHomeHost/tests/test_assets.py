"""Loopback static-serving checks; no frontend build or network is required."""
import http.client
from pathlib import Path
import tempfile
import unittest

from smarthome.asset_server import AssetBuildError, AssetServer, resolve_asset


class AssetServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'dist'
        self.root.mkdir()
        (self.root / 'index.html').write_text('<!doctype html><title>test</title>', encoding='utf-8')
        (self.root / 'assets').mkdir()
        (self.root / 'assets/app.js').write_text('export const value=1;', encoding='utf-8')
        (self.root / 'assets/model.glb').write_bytes(b'glTF')
        (self.root / 'secret.py').write_text('not a served asset', encoding='utf-8')
        (self.root.parent / 'outside.js').write_text('secret', encoding='utf-8')

    def request(self, server, path, method='GET', headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', server._server.server_port, timeout=3)
        try:
            connection.request(method, path, headers=headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_missing_build_has_explicit_actionable_error(self):
        with self.assertRaisesRegex(AssetBuildError, 'npm run build'):
            AssetServer(self.root / 'missing')

    def test_loopback_get_head_mime_and_close(self):
        server = AssetServer(self.root)
        self.addCleanup(server.close)
        self.assertEqual(server._server.server_address[0], '127.0.0.1')
        self.assertNotEqual(server._server.server_port, 0)
        status, headers, body = self.request(server, '/')
        self.assertEqual(status, 200)
        self.assertIn(b'<title>test</title>', body)
        self.assertEqual(headers['Content-Type'], 'text/html; charset=utf-8')
        self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')
        self.assertIn("default-src 'self'", headers['Content-Security-Policy'])
        self.assertNotIn('Access-Control-Allow-Origin', headers)
        status, headers, body = self.request(server, '/assets/app.js?v=42', 'HEAD')
        self.assertEqual((status, body), (200, b''))
        self.assertEqual(headers['Content-Type'], 'text/javascript; charset=utf-8')
        self.assertGreater(int(headers['Content-Length']), 0)
        status, headers, body = self.request(server, '/assets/model.glb')
        self.assertEqual((status, body), (200, b'glTF'))
        self.assertEqual(headers['Content-Type'], 'model/gltf-binary')
        server.close()
        server.close()
        self.assertFalse(server._thread.is_alive())

    def test_no_traversal_directory_listing_unknown_mime_or_http_control(self):
        with AssetServer(self.root) as server:
            for path in (
                '/../outside.js', '/%2e%2e/outside.js', '/assets/%2e%2e/%2e%2e/outside.js',
                '/%2e%2e%5coutside.js', '/C:/outside.js', '/index.html%00', '/%FF.js',
                '/bad%xx.js', '/assets/', '/secret.py', '/missing', '/api/control',
            ):
                with self.subTest(path=path):
                    self.assertEqual(self.request(server, path)[0], 404)
            self.assertEqual(self.request(server, '/', headers={'Host': 'foreign.example'})[0], 403)
            for method in ('POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'):
                with self.subTest(method=method):
                    status, headers, _ = self.request(server, '/', method)
                    self.assertEqual(status, 405)
                    self.assertEqual(headers['Allow'], 'GET, HEAD')

    def test_path_resolver_rejects_absolute_and_ambiguous_urls(self):
        for path in ('https://example.com/index.html', '//example.com/index.html',
                     'index.html', '/./index.html', '/assets//app.js', '/assets\\app.js'):
            with self.subTest(path=path):
                self.assertIsNone(resolve_asset(self.root, path))
        self.assertEqual(resolve_asset(self.root, '/assets/app.js'), self.root / 'assets/app.js')

    def test_symlink_cannot_escape_build_directory(self):
        link = self.root / 'escape.js'
        try:
            link.symlink_to(self.root.parent / 'outside.js')
        except OSError as exc:
            self.skipTest('Filesystem does not permit symlink creation: ' + str(exc))
        self.assertIsNone(resolve_asset(self.root, '/escape.js'))
        with AssetServer(self.root) as server:
            self.assertEqual(self.request(server, '/escape.js')[0], 404)


if __name__ == '__main__':
    unittest.main()
