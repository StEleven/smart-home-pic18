"""Optional actuator target compatibility; these are software-only checks."""
import math
import unittest

from smarthome.protocol import STATE_KEYS, ProtocolError, validate_state
from smarthome.simulator import Simulator


class DoorTargetTests(unittest.TestCase):
    def test_night_is_sleep_only_30_seconds_manual_hall_has_priority(self):
        simulator = Simulator()
        self.assertFalse(simulator.command('night', '1')[0])
        simulator.command('scene', 'sleep')
        self.assertFalse(simulator.command('night', '0')[0])
        self.assertTrue(simulator.command('night', '1')[0])
        self.assertEqual((simulator.state['hall'], simulator.state['night']), ('10', '1'))
        simulator.tick(29)
        self.assertEqual(simulator.state['hall'], '10')
        simulator.tick(1)
        self.assertEqual((simulator.state['hall'], simulator.state['night']), ('0', '0'))
        simulator.command('hall', '75')
        simulator.command('night', '1')
        self.assertEqual((simulator.state['hall'], simulator.state['night']), ('75', '1'))
        simulator.tick(30)
        self.assertEqual((simulator.state['hall'], simulator.state['night']), ('75', '0'))
        simulator.command('hall', 'auto')
        simulator.command('night', '1')
        simulator.command('scene', 'home')
        simulator.command('scene', 'sleep')
        self.assertEqual((simulator.state['hall'], simulator.state['night']), ('0', '0'))

    def test_new_optional_fields_validate_without_requiring_them_for_old_firmware(self):
        state = Simulator().snapshot()
        legacy = {key: value for key, value in state.items() if key in STATE_KEYS}
        self.assertEqual(validate_state(legacy), legacy)
        for comfort in ('0', '1', '2', '3'):
            self.assertEqual(validate_state(state | {'comfort': comfort})['comfort'], comfort)
        for point in ('200', '320', '?'):
            self.assertEqual(validate_state(state | {'setpoint10': point})['setpoint10'], point)
        for key, values in {'comfort': ('?', '-1', '4', '2.0'),
                            'setpoint10': ('199', '321', 'nan'),
                            'alarm': ('?', '-1', '2'),
                            'door_manual_ms': ('?', '-1', '600001'),
                            'away_check_ok': ('?', '2'),
                            'light_effect': ('?', '', 'Rainbow', 'off'),
                            'state_source': ('measured', '?', '')}.items():
            for value in values:
                with self.subTest(key=key, value=value), self.assertRaises(ProtocolError):
                    validate_state(state | {key: value})

    def test_ktv_fields_are_optional_and_effects_are_scene_scoped(self):
        simulator = Simulator()
        self.assertTrue({'ktv', 'light_effect', 'demand_hold'}.issubset(simulator.capabilities))
        legacy = {key: value for key, value in simulator.snapshot().items() if key in STATE_KEYS}
        self.assertEqual(validate_state(legacy), legacy)
        for effect in ('warm', 'rainbow', 'pulse', 'party'):
            self.assertEqual(validate_state(legacy | {'light_effect': effect})['light_effect'], effect)
        for field, invalid in (('ktv_brightness', '-1'), ('ktv_brightness', '101'),
                               ('ktv_brightness', '?'), ('demand_mode', '1')):
            with self.subTest(field=field, invalid=invalid), self.assertRaises(ProtocolError):
                validate_state(legacy | {field: invalid})
        for effect in ('warm', 'rainbow', 'pulse', 'party'):
            self.assertEqual(simulator.command('light_effect', effect), (False, 'SCENE'))
        simulator.command('scene', 'ktv')
        self.assertEqual(simulator.state['light_effect'], 'rainbow')
        self.assertEqual(tuple(simulator.state[key] for key in ('door_target', 'window_target', 'curtain')), ('0', '0', '0'))
        for action in ('door', 'window', 'curtain'):
            self.assertEqual(simulator.command(action, 'open'), (True, 'OK'))
        self.assertEqual(tuple(simulator.state[key] for key in ('door_target', 'window_target', 'curtain')), ('100', '100', '100'))
        for room in ('living', 'bedroom', 'hall'):
            self.assertEqual(simulator.command(room, '80'), (False, 'SCENE'))
        simulator.command('ktv_brightness', '73')
        self.assertEqual(tuple(simulator.state[room] for room in ('living', 'bedroom', 'hall')), ('73',) * 3)
        simulator.tick(120)
        self.assertEqual(simulator.state['ktv_brightness'], '73')
        for scene in ('home', 'movie', 'away', 'long_away', 'sleep'):
            simulator.command('scene', scene)
            self.assertEqual(simulator.state['light_effect'], 'warm')
            self.assertEqual(simulator.command('ktv_brightness', '20'), (False, 'SCENE'))
        simulator.command('scene', 'ktv')
        self.assertEqual(simulator.state['ktv_brightness'], '73')
        self.assertEqual(simulator.state['light_effect'], 'rainbow')

    def test_ktv_eight_pixels_use_master_and_matching_integer_animation(self):
        simulator = Simulator()
        simulator.command('scene', 'ktv')
        initial = simulator.light_frame()
        self.assertEqual(initial[0], (127, 0, 0))
        self.assertEqual(initial[1], (79, 48, 0))
        self.assertEqual(len(initial), 8)
        simulator.tick(.048)
        self.assertEqual(simulator.light_frame()[0], (124, 3, 0))
        simulator.tick(6.096)
        self.assertEqual(simulator.light_frame(), initial)
        simulator.command('light_effect', 'pulse')
        self.assertEqual(simulator.light_frame()[0], (12, 0, 0))
        simulator.tick(1.2)
        self.assertEqual(simulator.light_frame()[0], (52, 75, 0))
        simulator.command('light_effect', 'party')
        frame = simulator.light_frame()
        self.assertEqual([i for i, color in enumerate(frame) if any(color)], [0, 3, 5])
        simulator.tick(.18)
        self.assertEqual([i for i, color in enumerate(simulator.light_frame()) if any(color)], [0, 2, 5])
        for effect in ('rainbow', 'pulse', 'party', 'warm'):
            simulator.command('light_effect', effect)
            simulator.command('ktv_brightness', '0')
            self.assertEqual(simulator.light_frame(), [(0, 0, 0)] * 8)
            self.assertEqual(tuple(simulator.state[room] for room in ('living', 'bedroom', 'hall')), ('0',) * 3)
        simulator.command('scene', 'home')
        self.assertEqual(simulator.light_frame()[0], (178, 147, 105))

    def test_learning_pixel_is_white_and_never_moves_curtain_or_overlays_ktv(self):
        simulator = Simulator()
        simulator.command('curtain', 'close')
        before = simulator.snapshot()
        original = simulator.light_frame()
        simulator.command('timer_start', '30')
        self.assertEqual(simulator.state['curtain'], before['curtain'])
        self.assertEqual(simulator.light_frame()[7], (25, 25, 25))
        self.assertEqual(simulator.light_frame()[:7], original[:7])
        simulator.tick(2)
        self.assertEqual(simulator.light_frame()[7], (153, 153, 153))
        simulator.command('timer_pause', '1')
        simulator.tick(10)
        self.assertEqual(simulator.light_frame()[7], (51, 51, 51))
        simulator.command('timer_stop', '1')
        self.assertEqual(simulator.light_frame()[7], original[7])
        simulator.command('timer_start', '1')
        simulator.tick(1)
        self.assertEqual(simulator.light_frame()[7], original[7])
        simulator.command('timer_start', '30')
        simulator.command('scene', 'away')
        self.assertEqual(simulator.light_frame()[7], (0, 0, 0))
        simulator.command('scene', 'ktv')
        ktv_frame = simulator.light_frame()
        simulator.command('timer_pause', '1')
        self.assertEqual(simulator.light_frame(), ktv_frame)

    def test_door_commands_follow_output_and_explicit_simulated_feedback_is_persistent(self):
        simulator = Simulator()
        self.assertEqual(simulator.snapshot()['state_source'], 'commanded')
        self.assertEqual(simulator.command('door', 'close'), (True, 'OK'))
        self.assertEqual((simulator.snapshot()['door'], simulator.snapshot()['door_target']), ('1', '0'))
        simulator.set_input('door', '0')
        simulator.tick(1)
        self.assertEqual(simulator.snapshot()['door'], '0')
        self.assertEqual(simulator.door_feedback, '0')
        simulator.set_input('door', 'auto')
        self.assertEqual(simulator.snapshot()['door'], '1')
        simulator.tick(59)
        self.assertEqual(simulator.snapshot()['door_target'], '100')
        simulator.command('scene', 'away')
        self.assertEqual(simulator.command('door', 'open'), (False, 'AWAY'))
        self.assertEqual(simulator.snapshot()['door'], '1')
        simulator.command('scene', 'home')
        self.assertEqual(simulator.command('door', 'auto'), (True, 'OK'))
        self.assertEqual(simulator.snapshot()['door'], '0')

    def test_automatic_cooling_hysteresis_invalid_temperature_and_away_limits(self):
        simulator = Simulator()
        simulator.set_input('temp', '319')
        self.assertEqual(simulator.snapshot()['demand'], '0')
        simulator.set_input('temp', '320')
        self.assertEqual(simulator.snapshot()['cooling'], '1')
        simulator.set_input('temp', '315')
        self.assertEqual(simulator.snapshot()['demand'], '1')
        simulator.set_input('temp', '310')
        self.assertEqual(simulator.snapshot()['cooling'], '0')
        simulator.command('demand', '1')
        simulator.command('scene', 'away')
        self.assertEqual(simulator.snapshot()['cooling'], '0')
        simulator.command('scene', 'home')
        simulator.command('demand', '1')
        self.assertEqual(simulator.snapshot()['cooling'], '1')
        simulator.command('demand', 'auto')
        simulator.set_input('temp', '?')
        self.assertEqual((simulator.snapshot()['demand'], simulator.snapshot()['cooling']), ('?', '0'))
        for humid, comfort in (('399','1'),('400','2'),('600','2'),('601','3'),('?','0')):
            simulator.set_input('humid', humid)
            self.assertEqual(simulator.snapshot()['comfort'], comfort)

    def test_demand_manual_holds_and_bypasses_temperature_and_window_until_auto(self):
        simulator = Simulator()
        simulator.set_input('temp', '?')
        simulator.command('window', 'open')
        simulator.command('demand', '1')
        simulator.tick(3600)
        self.assertEqual((simulator.state['demand_mode'], simulator.state['demand'], simulator.state['cooling'], simulator.state['vent']), ('on', '1', '1', '100'))
        simulator.command('window', 'open')
        self.assertEqual((simulator.state['window_target'], simulator.state['cooling']), ('100', '1'))
        for scene in ('movie', 'sleep', 'ktv', 'home'):
            simulator.command('scene', scene)
            self.assertEqual((simulator.state['demand_mode'], simulator.state['cooling']), ('on', '1'))
        simulator.command('demand', '0')
        simulator.set_input('temp', '350')
        simulator.tick(3600)
        self.assertEqual((simulator.state['demand_mode'], simulator.state['cooling']), ('off', '0'))
        simulator.command('scene', 'movie')
        self.assertEqual((simulator.state['demand_mode'], simulator.state['cooling']), ('off', '0'))
        simulator.command('demand', 'auto')
        self.assertEqual((simulator.state['demand_mode'], simulator.state['cooling']), ('auto', '1'))
        for scene, reason in (('away', 'AWAY'), ('long_away', 'AWAY')):
            simulator.command('scene', 'home')
            simulator.command('demand', '1')
            simulator.command('scene', scene)
            self.assertEqual((simulator.state['demand_mode'], simulator.state['cooling']), ('auto', '0'))
            self.assertEqual(simulator.command('demand', '1'), (False, reason))
        simulator.command('scene', 'home')
        simulator.command('window', 'open')
        self.assertEqual(simulator.state['cooling'], '0', 'automatic mode still respects open windows')

    def test_unknown_water_preserves_alarm_and_mute_until_confirmed_dry(self):
        simulator = Simulator()
        simulator.set_input('water', '1')
        simulator.set_input('water', '?')
        self.assertEqual((simulator.snapshot()['water'], simulator.snapshot()['alarm']), ('?', '1'))
        self.assertEqual(simulator.command('mute', '1'), (True, 'OK'))
        simulator.tick(30)
        self.assertEqual(simulator.snapshot()['muted'], '1')
        simulator.set_input('water', '0')
        self.assertEqual((simulator.snapshot()['alarm'], simulator.snapshot()['muted']), ('0', '0'))
        self.assertEqual(simulator.command('mute', '1'), (False, 'NO_WATER_ALARM'))

    def test_ordinary_away_allows_manual_lights_and_loads_but_long_away_locks_them(self):
        simulator = Simulator()
        simulator.command('scene', 'away')
        self.assertEqual(simulator.snapshot()['living'], '0')
        self.assertEqual(simulator.command('living', '60'), (True, 'OK'))
        self.assertEqual(simulator.command('load_switch', '1'), (True, 'OK'))
        self.assertEqual(simulator.snapshot()['load_switch'], '1')
        simulator.command('scene', 'long_away')
        self.assertEqual(simulator.command('living', '60'), (False, 'LONG_AWAY'))
        self.assertEqual(simulator.command('load_switch', '1'), (False, 'LONG_AWAY'))

    def test_original_required_schema_is_unchanged(self):
        self.assertEqual(len(STATE_KEYS), 26)
        state = Simulator().snapshot()
        state.pop('door_target')
        self.assertNotIn('door_target', validate_state(state))

    def test_optional_door_target_checks_boundaries_unknown_and_invalid_values(self):
        state = Simulator().snapshot()
        for value in ('0', '100', '?'):
            with self.subTest(value=value):
                self.assertEqual(validate_state(state | {'door_target': value})['door_target'], value)
        for value in ('-1', '101', 'nan', 'NaN', 'inf', '1.5', '+1', '', 50, None):
            with self.subTest(value=value), self.assertRaises(ProtocolError):
                validate_state(state | {'door_target': value})

    def test_simulated_door_target_and_contact_remain_independent(self):
        simulator = Simulator()
        simulator.set_input('door', '0')
        simulator.set_actuator('door', 0)
        state = simulator.snapshot()
        self.assertEqual((state['door_target'], state['door']), ('0', '0'))
        simulator.set_input('door', '1')
        simulator.set_actuator('door', '100')
        simulator.command('scene', 'long_away')
        simulator.tick(60)
        state = simulator.snapshot()
        self.assertEqual((state['door_target'], state['door']), ('0', '1'))
        simulator.set_actuator('door', '?')
        self.assertEqual(simulator.snapshot()['door_target'], '?')
        self.assertEqual(simulator.command('door', 'open'), (False, 'LONG_AWAY'))
        self.assertIn('door', simulator.capabilities)

    def test_invalid_actuator_updates_are_atomic(self):
        simulator = Simulator()
        before = simulator.state.copy()
        for key, value in (('window', 50), ('door', 101), ('door', -1),
                           ('door', True), ('door', 2.5), ('door', math.nan), ('door', 'NaN')):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                simulator.set_actuator(key, value)
            self.assertEqual(simulator.state, before)


if __name__ == '__main__':
    unittest.main()
