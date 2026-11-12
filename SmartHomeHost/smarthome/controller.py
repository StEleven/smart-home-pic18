"""Qt serial session controller; real control authority remains on the PIC."""
from collections import deque
import csv
from datetime import datetime
from pathlib import Path
import json
import time
import uuid

from PySide6.QtCore import QObject, QTimer, QIODevice, Signal
from PySide6.QtSerialPort import QSerialPort

from .protocol import LineFramer, ProtocolError, encode, parse, validate_state
from .simulator import Simulator


ACTION_CAP = {
    'scene': 'scene', 'door': 'door', 'window': 'window', 'curtain': 'curtain', 'demand': 'demand',
    'living': 'lights', 'bedroom': 'lights', 'hall': 'lights', 'light_effect': 'light_effect',
    'ktv_brightness': 'ktv',
    'load_switch': 'loads', 'mute': 'mute', 'night': 'night',
    'timer_start': 'timer', 'timer_pause': 'timer',
    'timer_resume': 'timer', 'timer_stop': 'timer',
}
SCENES = {'home': '回家', 'away': '普通离家', 'long_away': '长期离家',
          'sleep': '睡眠', 'movie': '观影', 'ktv': 'KTV', 'unknown': '未知'}
REASONS = {
    'OK': '已接受', 'RAIN': '雨湿限制', 'RAIN_LOCK': '雨湿限制',
    'LONG_AWAY': '长期离家限制', 'LONG_AWAY_LOCK': '长期离家限制',
    'AWAY': '离家场景限制', 'AWAY_LOCK': '离家场景限制',
    'UNKNOWN': '检测状态未知', 'INVALID': '参数不合法',
    'INPUT_UNAVAILABLE': '传感器输入不可用',
    'CLIENT_MISMATCH': '控制会话已更换，请重新握手',
    'UNSUPPORTED': '当前固件不支持', 'NO_WATER': '当前无水浸',
    'INVALID_VALUE': '参数不合法', 'RAIN_UNKNOWN': '雨滴状态未知',
    'NO_WATER_ALARM': '当前无水浸报警', 'TIMER_STATE': '计时状态不允许该操作',
    'SCENE': '当前场景不支持此操作',
}


class Controller(QObject):
    changed = Signal()
    event = Signal(str, str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.serial = QSerialPort(self)
        self.serial.readyRead.connect(self._read)
        self.serial.errorOccurred.connect(self._serial_error)
        self.mode = 'offline'
        # Local source identity also changes on a reconnect with the same boot.
        # Unlike STATE seq this number never resets during the host lifetime.
        self.generation = 0
        self.state = {}
        self.capabilities = set()
        self.boot = None
        self.client_nonce = None
        self.firmware = ''
        self.status = '未连接'
        self.last_state = 0.0
        self.last_seq = None
        self.pending = None
        self.next_id = 1
        self.request_status = '尚无操作请求'
        self.framer = LineFramer()
        self.records = deque(maxlen=20000)
        self.simulator = None
        self.started = 0.0
        self.last_tick = time.monotonic()
        self.last_hello = 0.0
        self.last_snapshot = 0.0
        self._was_fresh = False
        self.last_saved = ''
        self.archive_error = ''
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(100)

    @property
    def fresh(self):
        return bool(self.state) and self._was_fresh and self.mode != 'offline' and time.monotonic() - self.last_state < 2.0

    def can(self, action):
        return (self.fresh and self.pending is None and ACTION_CAP.get(action) in self.capabilities
                and (action != 'night' or self.state.get('scene') == 'sleep'))

    def log(self, kind, message, payload=None, visible=True):
        stamp = datetime.now().astimezone().isoformat(timespec='milliseconds')
        row = [stamp, self.mode, self.boot or '', self.firmware, kind, message,
               json.dumps(payload or {}, ensure_ascii=False, separators=(',', ':'))]
        self.records.append(row)
        if visible:
            self.event.emit(stamp[11:19], kind, message)

    def disconnect(self):
        self.generation += 1
        if self.mode != 'offline':
            self.last_saved = ''
            self.archive_error = ''
            self.log('连接', '会话已结束；最后状态仅供查看')
            try:
                folder = Path(__file__).resolve().parents[1] / 'logs' / self.mode
                folder.mkdir(parents=True, exist_ok=True)
                path = folder / (datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.csv')
                self.export(path)
                self.last_saved = str(path)
            except OSError as exc:
                self.archive_error = str(exc)
                self.log('保存失败', str(exc))
        self.mode = 'offline'
        self.client_nonce = None
        self.serial.close()
        self.simulator = None
        self.capabilities.clear()
        self.pending = None
        self.last_state = 0.0
        self._was_fresh = False
        self.status = '未连接 · 最后状态已过期' if self.state else '未连接'
        self.request_status = '未连接，控制已禁用'
        if self.last_saved:
            self.request_status += '；记录已保存：' + self.last_saved
        if self.archive_error:
            self.request_status += '；记录未保存，请先导出当前会话：' + self.archive_error
        self.changed.emit()

    def _reset(self, mode):
        self.disconnect()
        if self.archive_error:
            return False
        self.last_saved = ''
        self.generation += 1
        self.mode = mode
        self.state = {}
        self.boot = None
        self.client_nonce = uuid.uuid4().hex
        self.firmware = ''
        self.last_seq = None
        self.framer = LineFramer()
        self.records.clear()
        self.request_status = '尚无操作请求'
        self.started = self.last_tick = time.monotonic()
        self.last_hello = 0.0
        self.last_snapshot = 0.0
        return True

    def connect_port(self, name):
        if not self._reset('real'):
            return False
        self.serial.setPortName(name)
        self.serial.setBaudRate(115200)
        self.serial.setDataBits(QSerialPort.DataBits.Data8)
        self.serial.setParity(QSerialPort.Parity.NoParity)
        self.serial.setStopBits(QSerialPort.StopBits.OneStop)
        self.serial.setFlowControl(QSerialPort.FlowControl.NoFlowControl)
        if not self.serial.open(QIODevice.OpenModeFlag.ReadWrite):
            error = self.serial.errorString()
            self.disconnect()
            self.status = '串口打开失败：' + error
            self.changed.emit()
            return False
        self.serial.setDataTerminalReady(True)
        self.status = '硬件已连接 · 正在同步'
        self.log('连接', '串口已打开：' + name + '；115200 8N1，DTR开启')
        self._hello()
        self.last_hello = time.monotonic()
        self.changed.emit()
        return True

    def start_demo(self):
        if not self._reset('simulation'):
            return False
        self.simulator = Simulator()
        self.capabilities = set(self.simulator.capabilities)
        self.firmware = 'desktop-simulator-1.1'
        self.status = '离线演示 · 模拟数据'
        self.log('演示', '离线演示已启动')
        self._accept_state(self.simulator.snapshot())
        self.changed.emit()
        return True

    def set_input(self, key, value):
        if self.mode != 'simulation' or self.simulator is None:
            return
        self.simulator.set_input(key, value)
        self.log('模拟输入', key + '=' + str(value))
        self._accept_state(self.simulator.snapshot())
        self.changed.emit()

    def set_actuator(self, key, value):
        if self.mode != 'simulation' or self.simulator is None:
            return False
        self.simulator.set_actuator(key, value)
        self.log('模拟输出', key + '_target=' + str(value), {'actuator': key, 'value': str(value)})
        self._accept_state(self.simulator.snapshot())
        self.changed.emit()
        return True

    def _write(self, kind, **fields):
        if not self.serial.isOpen():
            return False
        data = encode(kind, **fields)
        if self.serial.bytesToWrite() > 4096:
            self.log('通信异常', '发送缓冲拥塞；未发送新请求')
            return False
        count = self.serial.write(data)
        if count != len(data):
            self.log('通信异常', '串口写入不完整，执行结果未知')
            self.disconnect()
            return False
        return True

    def _hello(self):
        # Retries retain one client identity so duplicate protection survives.
        if self.client_nonce is None:
            self.client_nonce = uuid.uuid4().hex
        return self._write('HELLO', nonce=self.client_nonce)

    def _restart_handshake(self, message):
        self.generation += 1
        if self.pending:
            self.log('结果未知', '会话失效，上一请求执行结果未知', self.pending)
        self.pending = None
        self.capabilities.clear()
        self.boot = None
        self._was_fresh = False
        self.client_nonce = uuid.uuid4().hex
        self.status = message
        self.request_status = '状态已过期，旧请求结果未知；等待重新握手'
        self._hello()
        self.last_hello = time.monotonic()

    def request(self, action, value):
        if not self.can(action):
            self.request_status = '暂时无法操作，请等待状态同步'
            self.changed.emit()
            return False
        value = str(value)
        if action == 'scene' and value == 'ktv' and 'ktv' not in self.capabilities:
            self.request_status = '当前固件暂不支持KTV场景'
            self.changed.emit()
            return False
        if self.mode == 'simulation':
            ok, reason = self.simulator.command(action, value)
            self.request_status = '操作成功' if ok else '操作被拒绝：' + REASONS.get(reason, reason)
            self.log('模拟操作', self.request_status, {'action': action, 'value': value})
            self._accept_state(self.simulator.snapshot())
            self.changed.emit()
            return ok
        request_id = str(self.next_id)
        self.next_id += 1
        fields = {'boot': self.boot, 'id': request_id, 'action': action, 'value': value}
        if 'session' in self.capabilities:
            fields['client'] = self.client_nonce
        if not self._write('CMD', **fields):
            self.request_status = '未完成发送，结果未知'
            self.changed.emit()
            return False
        self.pending = {'id': request_id, 'action': action, 'value': value, 'sent': time.monotonic()}
        if 'client' in fields:
            self.pending['client'] = fields['client']
        self.request_status = '正在发送指令'
        self.log('请求', self.request_status, self.pending)
        self.changed.emit()
        return True

    def _read(self):
        self.receive(bytes(self.serial.readAll()))

    def receive(self, data):
        if self.mode != 'real':
            return
        errors_before = self.framer.errors
        for line in self.framer.feed(data):
            try:
                kind, fields = parse(line)
                self._handle(kind, fields)
            except (ProtocolError, ValueError, KeyError) as exc:
                self.log('协议异常', str(exc))
        if self.framer.errors != errors_before:
            self.log('协议异常', '超长消息已丢弃，等待下一完整行')
        self.changed.emit()

    def _handle(self, kind, fields):
        if kind == 'CAPS':
            if not fields.get('boot') or not fields.get('firmware') or 'caps' not in fields:
                raise ProtocolError('握手缺少boot、firmware或caps')
            caps = set(fields['caps'].split(',')) - {''}
            if ('session' in caps and fields.get('client') != self.client_nonce) or (
                    'session' in self.capabilities and 'session' not in caps):
                self.log('握手忽略', '忽略缺少当前client或来自旧会话的能力声明')
                return
            previous_boot = self.boot or self.state.get('boot')
            if previous_boot is not None and previous_boot != fields['boot']:
                self.generation += 1
                self.log('板端重启', '清除旧状态与待确认操作')
                self.pending = None
                self.state = {}
                self.last_state = 0.0
                self.last_seq = None
                self.request_status = '板端已重启，请重新查看状态'
            self.boot = fields['boot']
            self.firmware = fields['firmware']
            self.capabilities = caps
            self.log('握手', '固件：' + self.firmware, fields)
            self._write('GET')
        elif kind == 'STATE':
            state = validate_state(fields)
            if self.boot is None:
                return
            if state['boot'] != self.boot:
                self._restart_handshake('检测到新启动标识，等待重新握手')
                return
            self._accept_state(state)
        elif kind == 'ACK':
            if fields.get('boot') != self.boot or not self.pending or fields.get('id') != self.pending['id']:
                return
            if 'client' in self.pending and fields.get('client') != self.pending['client']:
                return
            if fields.get('result') not in ('ok', 'rejected'):
                raise ProtocolError('ACK结果必须是ok或rejected')
            reason = fields.get('reason', '')
            self.request_status = ('指令已接收' if fields['result'] == 'ok'
                                   else '操作被拒绝：' + REASONS.get(reason, reason))
            self.log('响应', self.request_status, fields)
            self.pending = None
            self._write('GET')
        elif kind in ('EVENT', 'ERR'):
            if fields.get('boot') == self.boot and self.boot is not None:
                self.log(kind, fields.get('reason', fields.get('code', '板端事件')), fields)

    def _accept_state(self, fields):
        state = validate_state(fields)
        seq = int(state['seq'])
        if self.last_seq is not None:
            delta = (seq - self.last_seq) & 0xffffffff
            if delta == 0 or delta >= 0x80000000:
                return
        self.state = state
        self.boot = state['boot']
        self.last_seq = seq
        self.last_state = time.monotonic()
        self._was_fresh = True
        if self.mode == 'real':
            self.status = '硬件已连接 · 状态已同步'
        self.log('STATE', '状态快照', state, visible=False)

    def tick(self):
        now = time.monotonic()
        dt = now - self.last_tick
        self.last_tick = now
        if self.mode == 'simulation' and self.simulator is not None:
            self.simulator.tick(dt)
            if now - self.last_snapshot >= 0.2:
                self._accept_state(self.simulator.snapshot())
                self.last_snapshot = now
        elif self.mode == 'real':
            if self.boot is None and now - self.last_hello > 2:
                self._hello()
                self.last_hello = now
                if now - self.started > 5:
                    self.status = '等待兼容固件：尚未收到 SH1 握手'
            if self._was_fresh and not self.fresh:
                self.log('状态过期', '2秒未收到新的有效状态')
                self._restart_handshake('真实硬件 · 数据已过期，等待重新握手')
            if self.pending and now - self.pending['sent'] > 2:
                self.request_status = '确认超时，执行结果未知；已请求读取当前状态'
                self.log('结果未知', self.request_status, self.pending)
                self.pending = None
                self._write('GET')
        self.changed.emit()

    def _serial_error(self, error):
        fatal = (QSerialPort.SerialPortError.ResourceError, QSerialPort.SerialPortError.ReadError,
                 QSerialPort.SerialPortError.WriteError)
        if self.mode == 'real' and error in fatal:
            message = self.serial.errorString()
            self.log('串口异常', message)
            self.disconnect()
            self.status = '连接中断：' + message
            self.changed.emit()

    def export(self, path):
        def safe(value):
            value = str(value)
            return "'" + value if value.startswith(('=', '+', '-', '@', '\t', '\r')) else value
        with open(path, 'w', newline='', encoding='utf-8-sig') as handle:
            writer = csv.writer(handle)
            writer.writerow(['本地时间含时区', '来源', '板端启动标识', '固件版本', '类型', '描述', '原始字段'])
            for row in self.records:
                writer.writerow([safe(cell) for cell in row])
        self.archive_error = ''
        self.last_saved = str(path)
