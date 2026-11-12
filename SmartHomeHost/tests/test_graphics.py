"""Startup configuration checks; no WebEngine, window, serial, or input events."""
import os
import unittest
from unittest.mock import patch

from smarthome.graphics import configure_webengine_graphics


class GraphicsConfigurationTests(unittest.TestCase):
    def test_windows_keeps_existing_arguments_and_does_not_duplicate_flags(self):
        existing = '--log-file="C:/a path/log.txt" --disable-gpu-compositing'
        with patch('smarthome.graphics.sys.platform', 'win32'), patch.dict(os.environ, {'QTWEBENGINE_CHROMIUM_FLAGS': existing}, clear=True):
            configure_webengine_graphics()
            first = os.environ['QTWEBENGINE_CHROMIUM_FLAGS']
            configure_webengine_graphics()
            self.assertEqual(os.environ['QTWEBENGINE_CHROMIUM_FLAGS'], first)
            self.assertEqual(first, existing + ' --disable-frame-rate-limit')
            self.assertNotIn('--disable-gpu ', first)

    def test_other_platform_configuration_is_untouched(self):
        with patch('smarthome.graphics.sys.platform', 'linux'), patch.dict(os.environ, {'QTWEBENGINE_CHROMIUM_FLAGS': '--existing'}, clear=True):
            configure_webengine_graphics()
            self.assertEqual(os.environ['QTWEBENGINE_CHROMIUM_FLAGS'], '--existing')
