"""Widget-level integration checks against the offline simulator only."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from smarthome.window import MainWindow


class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.paths = patch('smarthome.controller.Path', return_value=Path(self.temp.name) / 'host/smarthome/controller.py')
        self.paths.start()
        self.w = MainWindow()
        self.w.controller.timer.stop()
        self.w.show()
        self.app.processEvents()

    def tearDown(self):
        self.w.close()
        self.w.deleteLater()
        self.app.processEvents()
        self.paths.stop()
        self.temp.cleanup()

    def click_action(self, text):
        button = next(b for b, _ in self.w.action_buttons if b.text() == text)
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        self.app.processEvents()

    def select_map(self, key):
        item = self.w.house.items_by_key[key]
        pos = self.w.house.mapFromScene(item.sceneBoundingRect().center())
        QTest.mouseClick(self.w.house.viewport(), Qt.MouseButton.LeftButton, pos=pos)
        self.app.processEvents()
        self.assertEqual(self.w.selected_key, key)

    def test_map_controls_rain_priority_and_disconnect(self):
        self.assertTrue(all(not b.isEnabled() for b, _ in self.w.action_buttons))
        QTest.mouseClick(self.w.demo_button, Qt.MouseButton.LeftButton)
        self.app.processEvents()
        self.select_map('window')
        self.click_action('打开')
        self.assertEqual(self.w.controller.state['window_target'], '100')
        self.w.demo_fields['rain'].setCurrentIndex(1)
        self.assertEqual(self.w.controller.state['window_target'], '0')
        self.click_action('打开')
        self.assertIn('拒绝', self.w.request_label.text())
        self.w.controller.disconnect()
        self.assertIn('过期', self.w.feedback_label.text())
        self.assertTrue(all(not b.isEnabled() for b, _ in self.w.action_buttons))

    def test_inputs_water_mute_and_failed_window_closure(self):
        self.w.start_demo()
        self.w.demo_fields['water'].setCurrentIndex(1)
        self.select_map('water')
        self.click_action('消音（保留异常）')
        self.assertEqual(self.w.controller.state['water'], '1')
        self.assertEqual(self.w.controller.state['muted'], '1')
        self.assertIn('检测到水浸', self.w.feedback_label.text())
        combo = self.w.demo_fields['window']
        combo.setCurrentIndex(combo.findData('0'))
        self.w.demo_fields['demand'].setCurrentIndex(1)
        self.assertEqual(self.w.controller.state['window_target'], '0')
        self.assertEqual(self.w.controller.state['cooling'], '0')
        self.w.demo_fields['door'].setCurrentIndex(self.w.demo_fields['door'].findData('0'))
        self.w.controller.request('scene', 'long_away')
        self.assertIn('尚未全部关闭', self.w.away_status.text())

    def test_night_light_timer_and_session_event_isolation(self):
        self.w.start_demo()
        self.select_map('hall')
        night_button = next(b for b, a in self.w.action_buttons if a == 'night')
        self.assertFalse(night_button.isEnabled())
        self.w.controller.request('scene', 'sleep')
        self.assertTrue(night_button.isEnabled())
        self.click_action('起夜照明（10%，30秒）')
        self.assertEqual(self.w.controller.state['hall'], '10')
        self.select_map('timer')
        self.click_action('设置并开始')
        self.assertEqual(self.w.controller.state['timer_s'], '1500')
        self.click_action('暂停')
        self.w.controller.simulator.tick(60)
        self.assertEqual(self.w.controller.simulator.state['timer_s'], '1500')
        self.click_action('继续')
        self.w.controller.simulator.tick(1500)
        self.w.controller.set_input('rain', '0')
        self.assertIn('已结束', self.w.feedback_label.text())
        self.w.start_demo()
        messages = [self.w.events.item(row, 2).text() for row in range(self.w.events.rowCount())]
        self.assertFalse(any('会话已结束' in message for message in messages))

    def test_ktv_controls_use_one_brightness_for_every_room_and_normal_has_no_effects(self):
        self.w.start_demo()
        self.select_map('living')
        self.assertFalse(any(a == 'light_effect' for _, a in self.w.action_buttons))
        self.w.controller.request('scene', 'ktv')
        for room in ('living', 'bedroom', 'hall'):
            self.w.select_device(room)
            self.assertIn('KTV总亮度', self.w.feedback_label.text())
            self.assertFalse(any(a in ('living', 'bedroom', 'hall') for _, a in self.w.action_buttons))
            self.click_action('全灭')
            self.assertEqual(tuple(self.w.controller.state[r] for r in ('living', 'bedroom', 'hall')), ('0',) * 3)
        for label, effect in (('流动彩虹', 'rainbow'), ('彩色呼吸', 'pulse'), ('节拍跳色', 'party')):
            self.click_action(label)
            self.assertEqual(self.w.controller.state['light_effect'], effect)
            self.assertIn(label, self.w.feedback_label.text())
        self.w.controller.capabilities.remove('light_effect')
        self.w.refresh()
        self.assertTrue(all(not button.isEnabled() for button, action in self.w.action_buttons if action == 'light_effect'))
        self.w.controller.capabilities.remove('ktv')
        self.w.refresh()
        self.assertFalse(self.w.scene_combo.model().item(self.w.scene_combo.findData('ktv')).isEnabled())

    def test_manual_cooling_labels_are_persistent_only_with_hold_capability(self):
        self.w.start_demo()
        self.w.select_device('cooling')
        self.click_action('手动开启')
        self.assertEqual(self.w.controller.state['demand_mode'], 'on')
        self.assertIn('手动保持', self.w.rules_label.text())
        self.click_action('手动关闭')
        self.assertEqual(self.w.controller.state['cooling'], '0')
        self.click_action('自动')
        self.assertEqual(self.w.controller.state['demand_mode'], 'auto')
        self.w.controller.capabilities.remove('demand_hold')
        self.w.refresh()
        labels = [button.text() for button, _ in self.w.action_buttons]
        self.assertIn('临时开启', labels)
        self.assertNotIn('手动开启', labels)


if __name__ == '__main__':
    unittest.main()
