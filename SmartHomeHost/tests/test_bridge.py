"""Bridge validation/session regression checks without a WebEngine process."""
import json
import math
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from PySide6.QtWidgets import QApplication

from smarthome.bridge import HostBridge
from smarthome.controller import Controller
from smarthome.protocol import encode
from smarthome.simulator import Simulator


class BridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = 100.0
        self.clock = patch('smarthome.controller.time.monotonic', side_effect=lambda: self.now)
        self.clock.start()
        self.paths = patch('smarthome.controller.Path', return_value=Path(self.temp.name) / 'host/smarthome/controller.py')
        self.paths.start()
        self.c = Controller()
        self.c.timer.stop()
        self.bridge = HostBridge(self.c)
        self.signals = []
        self.events = []
        self.bridge.snapshotChanged.connect(lambda text: self.signals.append(json.loads(text)))
        self.bridge.eventAdded.connect(lambda text: self.events.append(json.loads(text)))
        self.outbound = []
        self.c._write = lambda kind, **fields: self.outbound.append((kind, fields)) or True

    def tearDown(self):
        self.bridge.dispose()
        self.c.mode = 'offline'
        self.c.serial.close()
        self.c.deleteLater()
        self.bridge.deleteLater()
        self.paths.stop()
        self.clock.stop()

    def snapshot(self):
        return json.loads(self.bridge.ready())

    def demo(self):
        self.assertTrue(json.loads(self.bridge.startDemo())['ok'])
        return self.snapshot()['sessionId']

    def real(self, boot='board-a', caps='window'):
        self.c._reset('real')
        self.c.receive(encode('CAPS', boot=boot, firmware='test-fw', caps=caps))
        self.c.receive(encode('STATE', **(Simulator().snapshot() | {'boot': boot, 'seq': '1'})))
        return self.snapshot()['sessionId']

    def action(self, session, action, value):
        return json.loads(self.bridge.requestAction(session, action, value))

    def test_initial_ready_has_complete_schema_and_does_not_start_simulator(self):
        state = self.snapshot()
        required = {'schemaVersion', 'revision', 'sessionId', 'mode', 'boot', 'seq',
                    'firmware', 'fresh', 'stateAgeMs', 'capabilities', 'pending',
                    'requestStatus', 'status', 'state', 'simulation', 'ports', 'events'}
        self.assertEqual(set(state), required)
        self.assertEqual((state['mode'], state['state'], state['fresh']), ('offline', {}, False))
        self.assertIsNone(state['simulation'])
        self.assertIsNone(self.c.simulator)
        self.assertGreater(self.snapshot()['revision'], state['revision'])

    def test_light_effect_validates_capability_and_tracks_board_state_after_ack(self):
        session = self.real(caps='lights')
        self.assertFalse(self.action(session, 'light_effect', 'rainbow')['ok'])
        self.c.receive(encode('CAPS', boot='board-a', firmware='smarthome-1.2', caps='lights,light_effect'))
        for value in ('off', 'Rainbow', '1', True, 'rainbow|bad=1'):
            self.assertFalse(self.action(session, 'light_effect', value)['ok'])
        self.assertTrue(self.action(session, 'light_effect', 'rainbow')['ok'])
        command = self.outbound[-1][1]
        self.assertEqual((command['action'], command['value']), ('light_effect', 'rainbow'))
        self.assertEqual(self.c.state['light_effect'], 'warm')
        self.c.receive(encode('ACK', boot='board-a', id=command['id'], result='ok'))
        self.assertEqual(self.c.request_status, '指令已接收')
        self.assertEqual(self.c.state['light_effect'], 'warm', 'ACK does not invent board state')
        self.c.receive(encode('STATE', **(Simulator().snapshot() | {
            'boot': 'board-a', 'seq': '2', 'light_effect': 'rainbow'})))
        self.assertEqual(self.snapshot()['state']['light_effect'], 'rainbow')
        self.c.receive(encode('STATE', **{key: value for key, value in
            (Simulator().snapshot() | {'boot': 'board-a', 'seq': '3'}).items() if key != 'light_effect'}))
        self.assertTrue(self.c.fresh)
        self.assertNotIn('light_effect', self.snapshot()['state'])

    def test_simulated_light_effect_success_uses_short_status_and_preserves_room_state(self):
        session = self.demo()
        self.assertFalse(self.action(session, 'light_effect', 'rainbow')['ok'])
        self.assertTrue(self.action(session, 'scene', 'ktv')['ok'])
        before = {room: self.c.state[room] for room in ('living', 'bedroom', 'hall')}
        self.assertTrue(self.action(session, 'light_effect', 'rainbow')['ok'])
        self.assertEqual(self.c.request_status, '操作成功')
        self.assertEqual(self.snapshot()['state']['light_effect'], 'rainbow')
        self.assertEqual({room: self.c.state[room] for room in before}, before)

    def test_ktv_brightness_requires_capability_and_scene_is_legacy_safe(self):
        session = self.real(caps='scene,lights')
        before = list(self.outbound)
        self.assertFalse(self.action(session, 'scene', 'ktv')['ok'])
        self.assertFalse(self.action(session, 'ktv_brightness', '30')['ok'])
        self.assertEqual(self.outbound, before)
        self.c.receive(encode('CAPS', boot='board-a', firmware='ktv-fw', caps='scene,ktv,lights,light_effect,demand,demand_hold'))
        for value in ('-1', '101', '?', True):
            self.assertFalse(self.action(session, 'ktv_brightness', value)['ok'])
        self.assertTrue(self.action(session, 'ktv_brightness', '0')['ok'])
        self.assertEqual((self.outbound[-1][1]['action'], self.outbound[-1][1]['value']), ('ktv_brightness', '0'))

    def test_real_door_and_demand_commands_use_capabilities_and_matching_ack(self):
        session = self.real(caps='door,demand')
        original = self.c.state.copy()
        self.assertTrue(self.action(session, 'door', 'close')['ok'])
        self.assertEqual(self.outbound[-1][0], 'CMD')
        fields = self.outbound[-1][1]
        self.assertEqual((fields['action'], fields['value'], fields['boot']), ('door', 'close', 'board-a'))
        self.assertEqual(self.c.state, original, 'request acceptance cannot invent position')
        self.assertFalse(self.action(session, 'demand', '1')['ok'])
        self.c.receive(encode('ACK', boot='board-a', id=fields['id'], result='ok'))
        self.assertEqual(self.c.state, original)
        self.assertTrue(self.action(session, 'demand', 'auto')['ok'])
        self.assertEqual(self.outbound[-1][1]['action'], 'demand')
        self.assertFalse(json.loads(self.bridge.setSimInput(session, 'rain', '1'))['ok'])
        self.assertFalse(json.loads(self.bridge.setSimInput(session, 'water', '1'))['ok'])
        self.assertEqual(self.c.state, original)

    def test_real_night_requires_sleep_and_capability_and_sends_night_command(self):
        session = self.real(caps='lights')
        self.c.receive(encode('STATE', **(self.c.state | {'scene': 'sleep', 'seq': '2'})))
        self.assertFalse(self.action(session, 'night', '1')['ok'])
        self.assertFalse(any(kind == 'CMD' for kind, _ in self.outbound))
        self.c.receive(encode('CAPS', boot='board-a', firmware='test-fw', caps='lights,night'))
        self.c.receive(encode('STATE', **(self.c.state | {'scene': 'home', 'seq': '3'})))
        self.assertFalse(self.action(session, 'night', '1')['ok'])
        self.c.receive(encode('STATE', **(self.c.state | {'scene': 'sleep', 'seq': '4'})))
        self.assertFalse(self.action(session, 'night', '0')['ok'])
        self.assertTrue(self.action(session, 'night', '1')['ok'])
        self.assertEqual((self.outbound[-1][0], self.outbound[-1][1]['action'],
                          self.outbound[-1][1]['value']), ('CMD', 'night', '1'))
        self.assertEqual(self.c.state['hall'], '30', 'acceptance cannot invent a board output')


    def test_ready_reload_does_not_replay_requests_or_restart_simulator(self):
        session = self.demo()
        self.action(session, 'timer_start', '45')
        simulator = self.c.simulator
        seq = self.c.last_seq
        before = self.snapshot()
        after = self.snapshot()
        self.assertIs(self.c.simulator, simulator)
        self.assertEqual(before['sessionId'], after['sessionId'])
        self.assertEqual((self.c.last_seq, after['state']['timer_s']), (seq, '45'))
        self.assertEqual(self.outbound, [])

    def test_ready_preserves_and_exposes_actual_window_feedback_override(self):
        session = self.demo()
        simulator = self.c.simulator
        self.assertEqual(self.snapshot()['simulation'], {'windowFeedback': 'auto', 'doorFeedback': 'auto'})
        self.action(session, 'window', 'open')
        for feedback in ('0', '1', '?', 'auto'):
            with self.subTest(feedback=feedback):
                self.assertTrue(json.loads(self.bridge.setSimInput(session, 'window', feedback))['ok'])
                seq = self.c.last_seq
                for _ in range(2):
                    snapshot = self.snapshot()
                    self.assertEqual(snapshot['sessionId'], session)
                    self.assertIs(self.c.simulator, simulator)
                    self.assertEqual(snapshot['seq'], seq)
                    self.assertEqual(snapshot['simulation'], {'windowFeedback': feedback, 'doorFeedback': 'auto'})
                    expected_contact = '0' if feedback == 'auto' else feedback
                    self.assertEqual(snapshot['state']['window'], expected_contact)
        self.bridge.disconnect()
        self.assertIsNone(self.snapshot()['simulation'])
        self.real()
        self.assertIsNone(self.snapshot()['simulation'])

    def test_revision_increases_for_pending_ack_timeout_and_stale_without_state_seq(self):
        session = self.real()
        initial = self.snapshot()
        self.assertTrue(self.action(session, 'window', 'open')['ok'])
        pending = self.snapshot()
        self.assertEqual(pending['seq'], initial['seq'])
        self.assertGreater(pending['revision'], initial['revision'])
        request_id = pending['pending']['id']
        self.c.receive(encode('ACK', boot='board-a', id=request_id, result='ok'))
        accepted = self.snapshot()
        self.assertEqual(accepted['state'], initial['state'])
        self.assertIsNone(accepted['pending'])
        self.assertGreater(accepted['revision'], pending['revision'])
        self.action(session, 'window', 'open')
        self.now += 2.01
        self.c.tick()
        expired = self.snapshot()
        self.assertEqual(expired['seq'], initial['seq'])
        self.assertFalse(expired['fresh'])
        self.assertGreaterEqual(expired['stateAgeMs'], 2000)
        self.assertIsNone(expired['pending'])
        self.assertIn('结果未知', expired['requestStatus'])
        revisions = [snapshot['revision'] for snapshot in self.signals]
        self.assertEqual(revisions, sorted(set(revisions)))

    def test_session_changes_on_disconnect_source_switch_and_same_boot_reconnect(self):
        first = self.real()
        first_revision = self.snapshot()['revision']
        self.bridge.disconnect()
        disconnected = self.snapshot()
        self.assertNotEqual(disconnected['sessionId'], first)
        self.assertFalse(disconnected['fresh'])
        second = self.real()
        self.assertNotIn(second, (first, disconnected['sessionId']))
        self.assertGreater(self.snapshot()['revision'], first_revision)
        self.assertFalse(self.action(first, 'window', 'open')['ok'])
        simulated = self.demo()
        before = self.c.state.copy()
        self.assertFalse(json.loads(self.bridge.setSimInput(second, 'rain', '1'))['ok'])
        self.assertEqual(self.c.state, before)
        self.assertNotEqual(simulated, second)

    def test_board_restart_changes_session_even_when_state_is_stale(self):
        previous = self.real()
        self.c.receive(encode('STATE', **(Simulator().snapshot() | {'boot': 'board-b'})))
        current = self.snapshot()
        self.assertNotEqual(current['sessionId'], previous)
        self.assertFalse(current['fresh'])
        self.assertFalse(self.action(previous, 'window', 'open')['ok'])
        self.c.receive(encode('CAPS', boot='board-b', firmware='test-fw', caps='window'))
        self.c.receive(encode('STATE', **(Simulator().snapshot() | {'boot': 'board-b'})))
        self.assertTrue(self.snapshot()['fresh'])
        before_caps = self.snapshot()['sessionId']
        self.c.receive(encode('CAPS', boot='board-c', firmware='test-fw', caps='window'))
        self.assertNotEqual(self.snapshot()['sessionId'], before_caps)

    def test_real_actions_reject_invalid_values_capabilities_and_pending(self):
        session = self.real()
        before = list(self.outbound)
        for action, value in (('door', 'open'), ('window', 'open|bad=1'),
                              ('window', True), ('living', 101), ('living', math.nan),
                              ('timer_start', '86401'), ('scene', 'unknown')):
            with self.subTest(action=action, value=value):
                self.assertFalse(self.action(session, action, value)['ok'])
        self.assertFalse(self.action(session, 'scene', 'home')['ok'])
        self.assertEqual(self.outbound, before)
        self.assertTrue(self.action(session, 'window', 'open')['ok'])
        self.assertFalse(self.action(session, 'window', 'close')['ok'])
        self.assertEqual(sum(kind == 'CMD' for kind, _ in self.outbound), 1)

    def test_rain_priority_water_mute_and_simulated_output_follow_controller(self):
        session = self.demo()
        self.assertTrue(self.action(session, 'window', 'open')['ok'])
        self.bridge.setSimInput(session, 'rain', '1')
        self.assertFalse(self.action(session, 'window', 'open')['ok'])
        self.assertEqual(self.snapshot()['state']['window_target'], '0')
        self.bridge.setSimInput(session, 'water', '1')
        self.assertTrue(self.action(session, 'mute', '1')['ok'])
        self.assertEqual((self.c.state['water'], self.c.state['muted']), ('1', '1'))
        self.bridge.setSimInput(session, 'door', '0')
        self.assertTrue(json.loads(self.bridge.setSimActuator(session, 'door', 0))['ok'])
        self.assertEqual((self.c.state['door'], self.c.state['door_target']), ('0', '0'))
        self.assertTrue(json.loads(self.bridge.setSimActuator(session, 'door', '100'))['ok'])
        self.assertEqual(self.c.state['door'], '0')
        self.assertTrue(any(event['kind'] == '模拟输出' for event in self.events))
        self.assertEqual(self.outbound, [])

    def test_simulation_slots_reject_real_mode_unknown_nan_and_out_of_range(self):
        session = self.real()
        self.assertFalse(json.loads(self.bridge.setSimActuator(session, 'door', 20))['ok'])
        self.assertFalse(json.loads(self.bridge.setSimInput(session, 'rain', '1'))['ok'])
        session = self.demo()
        original = self.c.state.copy()
        for key, value in (('door', 101), ('door', math.nan), ('window', 20)):
            self.assertFalse(json.loads(self.bridge.setSimActuator(session, key, value))['ok'])
        for key, value in (('temp', '1251'), ('temp', math.nan), ('door_target', '50')):
            self.assertFalse(json.loads(self.bridge.setSimInput(session, key, value))['ok'])
        self.assertEqual(self.c.state, original)

    def test_event_history_is_bounded_with_source_and_isolated_on_switch(self):
        self.demo()
        for index in range(75):
            self.c.log('TEST', str(index))
        history = self.snapshot()['events']
        self.assertEqual(len(history), 60)
        self.assertEqual((history[0]['message'], history[-1]['message']), ('15', '74'))
        self.assertTrue(all(event['source'] == 'simulation' for event in history))
        self.demo()
        self.assertFalse(any(event['kind'] == 'TEST' for event in self.snapshot()['events']))

    def test_connect_only_accepts_names_from_native_port_enumeration(self):
        class Port:
            def portName(self):
                return 'COM_TEST'
            def description(self):
                return 'Test port'
        with patch('smarthome.bridge.QSerialPortInfo.availablePorts', return_value=[Port()]), \
                patch.object(self.c, 'connect_port', return_value=True) as connect:
            self.assertTrue(json.loads(self.bridge.refreshPorts())['ok'])
            self.assertEqual(self.snapshot()['ports'], [{'name': 'COM_TEST', 'description': 'Test port'}])
            self.assertFalse(json.loads(self.bridge.connectPort('other-port'))['ok'])
            connect.assert_not_called()
            self.assertTrue(json.loads(self.bridge.connectPort('COM_TEST'))['ok'])
            connect.assert_called_once_with('COM_TEST')

    def test_failed_archive_blocks_switch_until_native_export_recovers(self):
        session = self.demo()
        rows = list(self.c.records)
        with patch.object(self.c, 'export', side_effect=OSError('test disk full')):
            self.assertFalse(json.loads(self.bridge.startDemo())['ok'])
        self.assertEqual(self.c.mode, 'offline')
        self.assertTrue(all(row in self.c.records for row in rows))
        self.assertFalse(self.action(session, 'window', 'open')['ok'])
        reports = []
        self.bridge.exportReport.connect(lambda text: reports.append(json.loads(text)))
        path = str(Path(self.temp.name) / 'recovered.csv')
        with patch('smarthome.bridge.QFileDialog.getSaveFileName', return_value=(path, 'CSV (*.csv)')):
            self.assertTrue(json.loads(self.bridge.exportLogs())['ok'])
        self.assertFalse(self.c.archive_error)
        self.assertTrue(Path(path).is_file())
        self.assertTrue(reports[-1]['ok'])
        self.assertTrue(json.loads(self.bridge.startDemo())['ok'])

    def test_export_cancel_error_and_duplicate_dialog_are_explicit_results(self):
        self.demo()
        with patch('smarthome.bridge.QFileDialog.getSaveFileName', return_value=('', '')):
            self.assertTrue(json.loads(self.bridge.exportLogs())['cancelled'])
        with patch('smarthome.bridge.QFileDialog.getSaveFileName', side_effect=OSError('denied')):
            self.assertFalse(json.loads(self.bridge.exportLogs())['ok'])
        self.assertFalse(self.bridge._exporting)
        self.bridge._exporting = True
        with patch('smarthome.bridge.QFileDialog.getSaveFileName') as dialog:
            self.assertFalse(json.loads(self.bridge.exportLogs())['ok'])
            dialog.assert_not_called()
        original_source = self.snapshot()['sessionId']
        self.assertFalse(json.loads(self.bridge.startDemo())['ok'])
        self.assertFalse(json.loads(self.bridge.disconnect())['ok'])
        self.assertFalse(json.loads(self.bridge.connectPort('COM_TEST'))['ok'])
        self.assertEqual(self.snapshot()['sessionId'], original_source)
        self.bridge._exporting = False


if __name__ == '__main__':
    unittest.main()
