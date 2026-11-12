"""Read-only built frontend server, bound to a loopback ephemeral port.

No control API, directory indexes, SPA fallbacks, or arbitrary MIME guessing
are exposed here. WebChannel is the sole device-control transport.
"""
from __future__ import annotations

from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import threading
from urllib.parse import unquote_to_bytes, urlsplit


class AssetBuildError(RuntimeError):
    """The packaged frontend is missing or cannot be served."""


MIME_TYPES = {
    '.html': 'text/html; charset=utf-8',
    '.js': 'text/javascript; charset=utf-8',
    '.mjs': 'text/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.json': 'application/json; charset=utf-8',
    '.gltf': 'model/gltf+json',
    '.glb': 'model/gltf-binary',
    '.bin': 'application/octet-stream',
    '.wasm': 'application/wasm',
    '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
    '.webp': 'image/webp', '.avif': 'image/avif', '.svg': 'image/svg+xml',
    '.ico': 'image/x-icon', '.hdr': 'image/vnd.radiance',
    '.woff': 'font/woff', '.woff2': 'font/woff2',
    '.ttf': 'font/ttf', '.otf': 'font/otf',
}


def resolve_asset(root: Path, request_path: str) -> Path | None:
    """Resolve a URL path inside root, rejecting encoded traversal and links out.

    A missing/unsupported file returns None; malformed paths do too so callers
    need not disclose which files exist outside the frontend build.
    """
    try:
        url = urlsplit(request_path)
        if url.scheme or url.netloc or not url.path.startswith('/'):
            return None
        if re.search(r'%(?![0-9a-fA-F]{2})', url.path):
            return None
        path = unquote_to_bytes(url.path).decode('utf-8', errors='strict')
        if '\\' in path or ':' in path or any(ord(char) < 32 or ord(char) == 127 for char in path):
            return None
        segments = path.split('/')[1:]
        if any(segment in ('.', '..') for segment in segments):
            return None
        # A directory is never an implicit index except for the application root.
        if path != '/' and (path.endswith('/') or any(not part for part in segments)):
            return None
        relative = 'index.html' if path == '/' else '/'.join(segments)
        candidate = (root / relative).resolve()
        if not candidate.is_relative_to(root) or candidate.suffix.lower() not in MIME_TYPES:
            return None
        return candidate if candidate.is_file() else None
    except (OSError, RuntimeError, UnicodeError, ValueError):
        return None


class _AssetHandler(BaseHTTPRequestHandler):
    server_version = 'SmartHomeAssets'
    sys_version = ''

    def __init__(self, *args, root: Path, **kwargs):
        self.root = root
        super().__init__(*args, **kwargs)

    def log_message(self, _format, *args):
        # Normal asset access is not a device or diagnostic event.
        pass

    def _serve(self, body: bool):
        expected_host = f'127.0.0.1:{self.server.server_port}'
        if self.headers.get('Host') != expected_host:
            self.send_error(403, 'Loopback application origin required')
            return
        path = resolve_asset(self.root, self.path)
        if path is None:
            self.send_error(404, 'Asset not found')
            return
        try:
            with path.open('rb') as stream:
                self.send_response(200)
                self.send_header('Content-Type', MIME_TYPES[path.suffix.lower()])
                self.send_header('Content-Length', str(path.stat().st_size))
                self.send_header('Cache-Control', 'no-store')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.send_header('X-Frame-Options', 'DENY')
                self.send_header('Referrer-Policy', 'no-referrer')
                self.send_header('Content-Security-Policy',
                                 "default-src 'self'; script-src 'self'; "
                                 "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
                                 "font-src 'self'; connect-src 'self'; worker-src 'self' blob:; "
                                 "object-src 'none'; frame-src 'none'; base-uri 'self'; frame-ancestors 'none'")
                self.end_headers()
                if body:
                    while data := stream.read(64 * 1024):
                        self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except OSError:
            # Avoid exposing absolute filesystem paths in HTTP errors.
            self.send_error(404, 'Asset unavailable')

    def do_GET(self):
        self._serve(True)

    def do_HEAD(self):
        self._serve(False)

    def _unsupported(self):
        self.send_response(405)
        self.send_header('Allow', 'GET, HEAD')
        self.send_header('Content-Length', '0')
        self.end_headers()

    do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _unsupported


class AssetServer:
    """Own the server thread; close it when the native window closes."""

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        if not self.root.is_dir() or not (self.root / 'index.html').is_file():
            raise AssetBuildError(
                '3D 界面资源尚未构建，未找到 frontend/dist/index.html。\n'
                '请在 SmartHomeHost/frontend 执行 npm ci 和 npm run build；'
                '构建后运行程序无需 Node.js。\n' + str(self.root))
        if resolve_asset(self.root, '/') is None:
            raise AssetBuildError('frontend/dist/index.html 必须是构建目录内可读取的静态文件。')
        self._server = ThreadingHTTPServer(('127.0.0.1', 0), partial(_AssetHandler, root=self.root))
        self._server.daemon_threads = True
        self.origin = f'http://127.0.0.1:{self._server.server_port}'
        self.url = self.origin + '/'
        self._thread = threading.Thread(
            target=self._server.serve_forever, kwargs={'poll_interval': 0.1},
            name='smarthome-assets', daemon=True)
        self._closed = False
        self._thread.start()

    def close(self):
        if self._closed:
            return
        self._closed = True
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()
