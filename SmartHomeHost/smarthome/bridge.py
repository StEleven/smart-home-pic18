"""Small, validated QObject API shared by the 3D page and the native host."""
from __future__ import annotations

from collections import deque
from datetime import datetime
import json
import re
import time
import uuid

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtSerialPort import QSerialPortInfo
from PySide6.QtWidgets import QFileDialog

from .controller import ACTION_CAP, Controller


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def _scalar(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError('参数须为整数字符串或整数')
    text = str(value)
    if len(text) > 64:
        raise ValueError('参数过长')
    return text


def _integer(text, lower, upper):
    return bool(re.fullmatch(r'[0-9]+', text, flags=re.ASCII)) and lower <= int(text) <= upper


def validate_action(action, value):
    """Validate every public action before it can reach a real serial port."""
    if not isinstance(action, str) or action not in ACTION_CAP:
        raise ValueError('不支持的操作')
    text = _scalar(value)
    if action == 'scene':
        valid = text in {'home', 'away', 'long_away', 'sleep', 'movie', 'ktv'}
    elif action in {'door', 'window', 'curtain'}:
        valid = text in {'open', 'close', 'auto'}
    elif action == 'demand':
        valid = text in {'0', '1', 'auto'}
    elif action in {'living', 'bedroom', 'hall'}:
        valid = text == 'auto' or _integer(text, 0, 100)
    elif action == 'ktv_brightness':
        valid = _integer(text, 0, 100)
    elif action == 'light_effect':
        valid = text in {'warm', 'rainbow', 'pulse', 'party'}
    elif action == 'load_switch':
        valid = text in {'0', '1'}
    elif action == 'timer_start':
        valid = _integer(text, 1, 86400)
    else:
        valid = text == '1'
    if not valid:
        raise ValueError('操作参数不合法')
    return text


class HostBridge(QObject):
    snapshotChanged = Signal(str)
    eventAdded = Signal(str)
    portsChanged = Signal(str)
    exportReport = Signal(str)

    def __init__(self, controller: Controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self._revision = 0
        self._generation = controller.generation
        self._session_id = uuid.uuid4().hex
        self._events = deque(maxlen=60)
        self._ports = []
        self._exporting = False
        self._disposed = False
        # If attached to an existing controller, ready still supplies history.
        for row in controller.records:
            if row[4] != 'STATE':
                self._events.append({'stamp': row[0][11:19], 'kind': row[4],
                                     'message': row[5], 'source': row[1]})
        controller.changed.connect(self._publish)
        controller.event.connect(self._on_event)
        self._refresh_ports()

    @property
    def session_id(self):
        self._sync_session()
        return self._session_id

    @property
    def revision(self):
        return self._revision

    def _sync_session(self):
        if self.controller.generation != self._generation:
            self._generation = self.controller.generation
            self._session_id = uuid.uuid4().hex
            self._events.clear()

    def snapshot(self):
        self._sync_session()
        c = self.controller
        self._revision += 1
        age = max(0, int((time.monotonic() - c.last_state) * 1000)) if c.last_state else None
        return {
            'schemaVersion': 1, 'revision': self._revision, 'sessionId': self._session_id,
            'mode': c.mode, 'boot': c.boot, 'seq': c.last_seq, 'firmware': c.firmware,
            'fresh': c.fresh, 'stateAgeMs': age, 'capabilities': sorted(c.capabilities),
            'pending': dict(c.pending) if c.pending else None,
            'requestStatus': c.request_status, 'status': c.status, 'state': dict(c.state),
            'simulation': ({'windowFeedback': c.simulator.window_feedback,
                            'doorFeedback': c.simulator.door_feedback}
                           if c.mode == 'simulation' and c.simulator is not None else None),
            'ports': [dict(port) for port in self._ports],
            'events': [dict(event) for event in self._events],
        }

    def _publish(self):
        if not self._disposed:
            self.snapshotChanged.emit(_json(self.snapshot()))

    def _on_event(self, stamp, kind, message):
        if self._disposed:
            return
        self._sync_session()
        event = {'stamp': stamp, 'kind': kind, 'message': message, 'source': self.controller.mode}
        self._events.append(event)
        self.eventAdded.emit(_json(event))

    def _reject(self, message):
        self.controller.request_status = message
        self.controller.log('请求拒绝', message)
        self.controller.changed.emit()
        return {'ok': False, 'message': message}

    def _execute(self, callback):
        if self._disposed:
            return _json({'ok': False, 'message': '窗口已关闭'})
        try:
            return _json(callback())
        except Exception as exc:
            # JS must receive an explicit failure; a Qt slot must not leak a
            # Python exception into the event loop or terminate the desktop UI.
            return _json(self._reject('操作失败：' + str(exc)))

    def _check_session(self, session_id):
        if not isinstance(session_id, str) or session_id != self.session_id:
            raise ValueError('会话已更换，请使用最新状态重试')

    def _check_source_change(self):
        # A native file dialog runs a nested event loop. Switching source there
        # would save the wrong session under the old dialog's filename.
        if self._exporting:
            raise ValueError('保存对话框已打开，请先完成或取消保存')

    @Slot(result=str)
    def ready(self):
        # Frontend connects signals first. A delayed ready response has its own
        # revision, so it cannot overwrite a newer signal already delivered.
        return _json(self.snapshot())

    @Slot(str, str, 'QVariant', result=str)
    def requestAction(self, session_id, action, value):
        def action_request():
            self._check_session(session_id)
            text = validate_action(action, value)
            c = self.controller
            if not c.fresh:
                return self._reject('数据未就绪或已过期，控制已禁用')
            if c.pending is not None:
                return self._reject('上一请求正在等待确认')
            if ACTION_CAP[action] not in c.capabilities:
                return self._reject('当前固件暂不支持此操作')
            ok = c.request(action, text)
            return {'ok': bool(ok), 'message': c.request_status}
        return self._execute(action_request)

    @Slot(result=str)
    def startDemo(self):
        def start():
            self._check_source_change()
            ok = self.controller.start_demo()
            return {'ok': bool(ok), 'message': self.controller.request_status if not ok else self.controller.status}
        return self._execute(start)

    @Slot(result=str)
    def disconnect(self):
        def disconnect_source():
            self._check_source_change()
            self.controller.disconnect()
            return {'ok': not bool(self.controller.archive_error), 'message': self.controller.request_status}
        return self._execute(disconnect_source)

    def _refresh_ports(self):
        self._ports = [
            {'name': name, 'description': description}
            for name, description in sorted({(port.portName(), port.description())
                                             for port in QSerialPortInfo.availablePorts()})
        ]

    @Slot(result=str)
    def refreshPorts(self):
        def refresh():
            self._refresh_ports()
            self.portsChanged.emit(_json(self._ports))
            self._publish()
            return {'ok': True, 'message': '串口列表已更新'}
        return self._execute(refresh)

    @Slot(str, result=str)
    def connectPort(self, name):
        def connect():
            self._check_source_change()
            self._refresh_ports()
            self.portsChanged.emit(_json(self._ports))
            if not isinstance(name, str) or name not in {port['name'] for port in self._ports}:
                return self._reject('串口不存在，请刷新列表后选择')
            ok = self.controller.connect_port(name)
            return {'ok': bool(ok), 'message': self.controller.status if ok else self.controller.request_status + '；' + self.controller.status}
        return self._execute(connect)

    def _simulation(self, session_id):
        self._check_session(session_id)
        if self.controller.mode != 'simulation' or self.controller.simulator is None:
            raise ValueError('此入口仅用于离线演示')

    @Slot(str, str, 'QVariant', result=str)
    def setSimInput(self, session_id, key, value):
        def set_input():
            self._simulation(session_id)
            self.controller.set_input(key, value)
            return {'ok': True, 'message': '模拟输入已更新'}
        return self._execute(set_input)

    @Slot(str, str, 'QVariant', result=str)
    def setSimActuator(self, session_id, key, value):
        def set_output():
            self._simulation(session_id)
            self.controller.set_actuator(key, value)
            return {'ok': True, 'message': '模拟输出已更新'}
        return self._execute(set_output)

    @Slot(result=str)
    def exportLogs(self):
        if self._exporting:
            return _json({'ok': False, 'message': '保存对话框已打开'})
        self._exporting = True
        def export():
            source = self.controller.mode if self.controller.mode != 'offline' else 'session'
            filename = f'smarthome_{source}_{datetime.now():%Y%m%d_%H%M%S}.csv'
            path, _ = QFileDialog.getSaveFileName(self.parent(), '保存当前会话', filename, 'CSV (*.csv)')
            if not path:
                return {'ok': False, 'cancelled': True, 'message': '已取消保存'}
            self.controller.export(path)
            self.controller.request_status = '记录已保存：' + path
            self.controller.changed.emit()
            return {'ok': True, 'message': '记录已保存：' + path}
        try:
            result = self._execute(export)
            self.exportReport.emit(result)
            return result
        finally:
            self._exporting = False

    def dispose(self):
        if self._disposed:
            return
        self._disposed = True
        self.controller.changed.disconnect(self._publish)
        self.controller.event.disconnect(self._on_event)


# Convenient public name for non-UI integration code.
Bridge = HostBridge
