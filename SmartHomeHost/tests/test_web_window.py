"""Native host layout checks without starting Chromium or displaying a window."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication, QStatusBar, QWidget

from smarthome.web_window import MainWindow


class FakeWebView(QWidget):
    def load(self, url):
        self.loaded_url = url

    def stop(self):
        pass


class FullScreenRequest:
    def __init__(self, on):
        self.on = on
        self.accepted = False

    def origin(self):
        return QUrl('http://127.0.0.1:9999')

    def toggleOn(self):
        return self.on

    def accept(self):
        self.accepted = True

    def reject(self):
        self.accepted = False


class WebWindowLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.paths = patch('smarthome.controller.Path', return_value=Path(self.temp.name) / 'host/smarthome/controller.py')
        self.paths.start()
        self.addCleanup(self.paths.stop)
        self.server = patch('smarthome.web_window.AssetServer')
        server_class = self.server.start()
        self.addCleanup(self.server.stop)
        server_class.return_value.url = 'http://127.0.0.1:9999/'
        server_class.return_value.origin = 'http://127.0.0.1:9999'

        def create_web_view(window):
            window.view = FakeWebView(window.stack)
            window.stack.addWidget(window.view)
            window._view_ready = True

        with patch.object(MainWindow, '_create_web_view', create_web_view):
            self.window = MainWindow()
        self.window.controller.timer.stop()
        self.addCleanup(self.close_window)

    def close_window(self):
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def assert_content_fills_window(self):
        self.app.processEvents()
        self.assertIsNone(self.window.findChild(QStatusBar))
        self.assertEqual(self.window.stack.geometry(), self.window.contentsRect())
        self.assertEqual(self.window.view.geometry(), self.window.stack.contentsRect())

    def test_load_and_native_fullscreen_leave_no_bottom_statusbar(self):
        self.window.show()
        self.assert_content_fills_window()
        self.window._load_finished(True)
        self.assert_content_fills_window()
        for on in (True, False, True, False):
            request = FullScreenRequest(on)
            self.window._fullscreen_requested(request)
            self.assertTrue(request.accepted)
            self.assertEqual(self.window.isFullScreen(), on)
            self.assert_content_fills_window()
        self.window.reload_frontend()
        self.assert_content_fills_window()

    def test_security_notice_and_export_do_not_create_a_statusbar(self):
        self.window._navigation_blocked('https://example.com/')
        self.assertIsNone(self.window.findChild(QStatusBar))
        self.window._show_error('加载失败')
        with patch.object(self.window.bridge, 'exportLogs', return_value=json.dumps({'message': '已导出'})):
            self.window._export_from_failure()
        self.assertEqual(self.window.error_label.text(), '加载失败\n\n已导出')
        self.assertIsNone(self.window.findChild(QStatusBar))


if __name__ == '__main__':
    unittest.main()
