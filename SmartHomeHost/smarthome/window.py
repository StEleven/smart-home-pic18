"""Windows desktop UI for live telemetry or explicitly labelled simulation."""
from datetime import datetime
from pathlib import Path
import time

from PySide6.QtCore import Qt, QRectF, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QFontDatabase, QPainter, QPen
from PySide6.QtSerialPort import QSerialPortInfo
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QComboBox, QSpinBox, QDoubleSpinBox, QGroupBox, QFormLayout,
    QGraphicsView, QGraphicsScene, QGraphicsRectItem, QTableWidget,
    QTableWidgetItem, QHeaderView, QFileDialog, QMessageBox, QScrollArea,
    QSplitter, QSizePolicy,
)
from .controller import Controller, SCENES


NAMES = {'door': '门', 'window': '窗户', 'curtain': '窗帘', 'vent': '空调风口',
         'rain': '屋外雨滴', 'water': '厨房水浸', 'living': '客厅照明',
         'bedroom': '卧室照明', 'hall': '走道照明', 'cooling': '模拟空调',
         'loads': '模拟家电', 'timer': '学习计时'}


def onoff(value):
    return {'0': '关闭', '1': '开启', '?': '未知'}.get(value, '未知')


def contact(value):
    return {'0': '开启 / 运动中', '1': '关闭状态', '?': '未知'}.get(value, '未知')


def percent(value):
    return '未知' if value in (None, '?') else value + '%'


def remaining(value):
    if value in (None, '?'):
        return '—'
    seconds = int(value)
    return f'{seconds // 60:02d}:{seconds % 60:02d}'


class DeviceItem(QGraphicsRectItem):
    def __init__(self, name, key, x, y, width, callback):
        super().__init__(0, 0, width, 51)
        self.setPos(x, y)
        self.key = key
        self.name = name
        self.callback = callback
        self.setPen(QPen(Qt.GlobalColor.black, 1))
        self.setBrush(QBrush(Qt.GlobalColor.white))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.label = None
        self.value = '未知'
        self.selected_device = False
        self.indicator = '?'

    def paint(self, painter, option, widget=None):
        painter.setPen(QPen(Qt.GlobalColor.black, 2 if self.selected_device else 1,
                            Qt.PenStyle.SolidLine if self.selected_device else Qt.PenStyle.DashLine))
        painter.setBrush(Qt.GlobalColor.white)
        painter.drawRect(self.rect())
        font = QFont('Microsoft YaHei', 10)
        font.setBold(self.selected_device)
        painter.setFont(font)
        painter.drawText(self.rect().adjusted(8, 3, -8, -25), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.name)
        font.setBold(False)
        painter.setFont(font)
        painter.drawText(self.rect().adjusted(8, 24, -8, -2), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.value)
        if self.key in ('curtain', 'vent') and self.indicator != '?':
            # A schematic of the target only; it never implies measured travel.
            x = self.rect().width() - 43
            painter.setPen(QPen(Qt.GlobalColor.black, 1))
            painter.drawRect(QRectF(x, 6, 34, 15))
            ratio = int(self.indicator) / 100
            if self.key == 'curtain':
                covered = 16 * (1 - ratio)
                for offset in range(0, int(covered) + 1, 3):
                    painter.drawLine(int(x + offset), 7, int(x + offset), 20)
                    painter.drawLine(int(x + 34 - offset), 7, int(x + 34 - offset), 20)
            else:
                for offset in (7, 16, 25):
                    painter.drawLine(int(x + offset), 8, int(x + offset + 7 * ratio), 19)

    def mousePressEvent(self, event):
        self.callback(self.key)
        event.accept()


class HouseView(QGraphicsView):
    selected = Signal(str)

    def __init__(self):
        super().__init__()
        self.house_scene = QGraphicsScene(self)
        self.setScene(self.house_scene)
        self.setSceneRect(0, 0, 660, 500)
        self.setMinimumSize(510, 395)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setBackgroundBrush(Qt.GlobalColor.white)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        for x, y, width, height, title in [(15, 70, 350, 210, '客厅'), (365, 70, 280, 210, '卧室'),
                                            (15, 280, 350, 175, '走道'), (365, 280, 280, 175, '厨房')]:
            self.house_scene.addRect(x, y, width, height, QPen(Qt.GlobalColor.black, 2), QBrush(Qt.GlobalColor.white))
            text = self.house_scene.addText(title, QFont('Microsoft YaHei', 12, QFont.Weight.Bold))
            text.setDefaultTextColor(Qt.GlobalColor.black)
            text.setPos(x + 12, y + 6)
        self.items_by_key = {}
        positions = [
            ('rain', 15, 7, 180), ('window', 205, 7, 220),
            ('living', 30, 112, 150), ('curtain', 195, 112, 150),
            ('cooling', 30, 183, 150), ('vent', 195, 183, 150),
            ('bedroom', 380, 112, 245), ('timer', 380, 183, 245),
            ('hall', 30, 330, 150), ('door', 195, 330, 150),
            ('water', 380, 323, 245), ('loads', 380, 388, 245),
        ]
        for key, x, y, width in positions:
            item = DeviceItem(NAMES[key], key, x, y, width, self.selected.emit)
            self.house_scene.addItem(item)
            self.items_by_key[key] = item
        text = self.house_scene.addText('智慧小屋 · 点选设备查看与控制', QFont('Microsoft YaHei', 10))
        text.setPos(15, 465)
        text.setDefaultTextColor(Qt.GlobalColor.black)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def update_state(self, state, selected, fresh):
        values = {
            'rain': {'0': '干燥', '1': '检测到雨湿'}.get(state.get('rain'), '未知'),
            'water': {'0': '无水浸', '1': '水浸' + (' · 已消音' if state.get('muted') == '1' else ' · 未消音')}.get(state.get('water'), '未知'),
            'door': contact(state.get('door')), 'window': contact(state.get('window')),
            'curtain': '目标 ' + percent(state.get('curtain')), 'vent': '目标 ' + percent(state.get('vent')),
            'living': percent(state.get('living')), 'bedroom': percent(state.get('bedroom')),
            'hall': percent(state.get('hall')), 'cooling': onoff(state.get('cooling')),
            'loads': '可关闭负载 ' + onoff(state.get('load_switch')),
            'timer': {'idle': '未开始', 'running': '运行 ', 'paused': '暂停 ', 'done': '已结束 '}.get(state.get('timer'), '未知 ') + (remaining(state.get('timer_s')) if state.get('timer') != 'idle' else ''),
        }
        for key, item in self.items_by_key.items():
            item.value = values[key] + (' [过期]' if state and not fresh else '')
            item.selected_device = key == selected
            item.indicator = state.get(key, '?')
            item.update()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('智慧小屋上位机')
        # Offscreen Qt has no system font discovery on Windows. Load an
        # installed font for both reproducible screenshots and fallback use.
        if not QFontDatabase.hasFamily('Microsoft YaHei'):
            font_path = Path('C:/Windows/Fonts/msyh.ttc')
            if font_path.is_file():
                QFontDatabase.addApplicationFont(str(font_path))
        self.resize(1160, 920)
        self.setMinimumSize(950, 680)
        self.controller = Controller(self)
        self.controller.changed.connect(self.refresh)
        self.controller.event.connect(self.add_event)
        self.selected_key = 'window'
        self.action_buttons = []
        self._controls_signature = None
        self.setStyleSheet('''
          QWidget {background:white;color:black;font-family:"Microsoft YaHei";font-size:13px;}
          QGroupBox {border:1px solid black;margin-top:16px;padding-top:12px;}
          QGroupBox::title {subcontrol-origin:margin;left:8px;padding:0 4px;}
          QPushButton {border:1px solid black;padding:6px 10px;min-height:18px;}
          QPushButton:pressed {border:2px solid black;}
          QPushButton:disabled {color:#777;border-color:#aaa;}
          QComboBox,QSpinBox,QDoubleSpinBox {border:1px solid black;padding:4px;min-height:20px;}
          QTableWidget {gridline-color:black;selection-background-color:white;selection-color:black;}
          QHeaderView::section {background:white;color:black;border:1px solid black;padding:4px;}
        ''')
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(18, 12, 18, 12)
        layout.setSpacing(10)
        title = QLabel('智慧小屋 · 运行与控制')
        title.setStyleSheet('font-size:21px;font-weight:bold;')
        layout.addWidget(title)
        self.status_label = QLabel('未连接')
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        connection = QHBoxLayout()
        self.ports = QComboBox()
        self.ports.setMinimumWidth(230)
        self.refresh_ports_button = QPushButton('刷新串口')
        self.refresh_ports_button.clicked.connect(self.refresh_ports)
        self.connect_button = QPushButton('连接硬件')
        self.connect_button.clicked.connect(self.connect_hardware)
        self.disconnect_button = QPushButton('断开')
        self.disconnect_button.clicked.connect(self.controller.disconnect)
        self.demo_button = QPushButton('离线演示')
        self.demo_button.clicked.connect(self.start_demo)
        for control in (self.ports, self.refresh_ports_button, self.connect_button, self.disconnect_button, self.demo_button):
            connection.addWidget(control)
        connection.addStretch()
        layout.addLayout(connection)
        scene_row = QHBoxLayout()
        self.scene_combo = QComboBox()
        for key, name in SCENES.items():
            if key != 'unknown':
                self.scene_combo.addItem(name, key)
        self.scene_combo.currentIndexChanged.connect(lambda: self.refresh())
        self.scene_send = QPushButton('请求场景切换')
        self.scene_send.clicked.connect(lambda: self.controller.request('scene', self.scene_combo.currentData()))
        self.scene_live = QLabel('生效场景：未知')
        scene_row.addWidget(self.scene_combo)
        scene_row.addWidget(self.scene_send)
        scene_row.addWidget(self.scene_live)
        scene_row.addStretch()
        layout.addLayout(scene_row)
        main = QHBoxLayout()
        self.house = HouseView()
        self.house.selected.connect(self.select_device)
        main.addWidget(self.house, 3)
        self.details = QGroupBox('窗户')
        self.details.setMinimumWidth(300)
        self.details.setMaximumWidth(420)
        self.detail_layout = QVBoxLayout(self.details)
        self.feedback_label = QLabel()
        self.feedback_label.setWordWrap(True)
        self.rules_label = QLabel()
        self.rules_label.setWordWrap(True)
        self.detail_layout.addWidget(self.feedback_label)
        self.detail_layout.addWidget(self.rules_label)
        self.controls_widget = QWidget()
        self.controls_layout = QVBoxLayout(self.controls_widget)
        self.controls_layout.setContentsMargins(0, 10, 0, 0)
        self.detail_layout.addWidget(self.controls_widget)
        self.availability = QLabel()
        self.availability.setWordWrap(True)
        self.detail_layout.addWidget(self.availability)
        self.detail_layout.addStretch()
        main.addWidget(self.details, 2)
        layout.addLayout(main, 1)
        self.environment = QLabel('温度：—　湿度：—　环境光：—')
        self.environment.setWordWrap(True)
        layout.addWidget(self.environment)
        self.away_status = QLabel()
        self.away_status.setWordWrap(True)
        layout.addWidget(self.away_status)
        self.request_label = QLabel()
        self.request_label.setWordWrap(True)
        layout.addWidget(self.request_label)
        self.demo_group = self.build_demo_inputs()
        layout.addWidget(self.demo_group)
        log_row = QHBoxLayout()
        log_row.addWidget(QLabel('动作与通信记录（当前会话；模拟和真实记录分开）'))
        log_row.addStretch()
        export_button = QPushButton('导出当前会话 CSV')
        export_button.clicked.connect(self.export_logs)
        log_row.addWidget(export_button)
        layout.addLayout(log_row)
        self.events = QTableWidget(0, 3)
        self.events.setHorizontalHeaderLabels(['时间', '类型', '内容'])
        self.events.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.events.setColumnWidth(0, 85)
        self.events.setColumnWidth(1, 100)
        self.events.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.events.setMinimumHeight(130)
        self.events.setMaximumHeight(190)
        layout.addWidget(self.events)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        self.setCentralWidget(scroll)
        self.refresh_ports()
        self.select_device('window')
        self.refresh()

    def refresh_ports(self):
        previous = self.ports.currentData()
        self.ports.clear()
        for port in QSerialPortInfo.availablePorts():
            self.ports.addItem(f'{port.portName()} · {port.description()}', port.portName())
        if self.ports.count() == 0:
            self.ports.addItem('未发现串口', None)
        index = self.ports.findData(previous)
        if index >= 0:
            self.ports.setCurrentIndex(index)

    def connect_hardware(self):
        name = self.ports.currentData()
        if not name:
            QMessageBox.information(self, '连接硬件', '请接入 Nano USB 数据线，再刷新串口。')
            return
        self.controller.connect_port(name)
        self.reload_events()

    def start_demo(self):
        if self.controller.start_demo():
            self.reload_events()
            self.sync_demo_inputs()

    def reload_events(self):
        self.events.setRowCount(0)
        for row in self.controller.records:
            if row[4] != 'STATE':
                self.add_event(row[0][11:19], row[4], row[5])

    def select_device(self, key):
        self.selected_key = key
        is_ktv = self.controller.state.get('scene') == 'ktv'
        demand_hold = 'demand_hold' in self.controller.capabilities
        self._controls_signature = (is_ktv, demand_hold)
        self.details.setTitle(NAMES[key])
        self.action_buttons.clear()
        while self.controls_layout.count():
            item = self.controls_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if key in ('door', 'window', 'curtain'):
            for title, value in [('打开', 'open'), ('关闭', 'close'), ('恢复自动', 'auto')]:
                self.add_action(title, key, value)
        elif key in ('living', 'bedroom', 'hall'):
            value = QSpinBox()
            value.setRange(0, 100)
            value.setValue(int(self.controller.state.get('ktv_brightness', '50')) if is_ktv else 30 if key == 'hall' else 70)
            value.setSuffix('%')
            value.setAccessibleName('KTV 总亮度' if is_ktv else '灯光亮度')
            self.controls_layout.addWidget(value)
            if is_ktv:
                self.add_action('设置KTV总亮度', 'ktv_brightness', lambda: str(value.value()))
                self.add_action('全灭', 'ktv_brightness', '0')
                for label, effect in [('流动彩虹', 'rainbow'), ('彩色呼吸', 'pulse'), ('节拍跳色', 'party')]:
                    self.add_action(label, 'light_effect', effect)
            else:
                self.add_action('请求设置亮度', key, lambda: str(value.value()))
                self.add_action('关灯', key, '0')
                if key == 'hall':
                    self.add_action('起夜照明（10%，30秒）', 'night', '1')
                self.add_action('恢复自动', key, 'auto')
        elif key == 'cooling':
            self.add_action('自动', 'demand', 'auto')
            self.add_action('手动开启' if demand_hold else '临时开启', 'demand', '1')
            self.add_action('手动关闭' if demand_hold else '临时关闭', 'demand', '0')
        elif key == 'loads':
            self.add_action('开启可关闭负载', 'load_switch', '1')
            self.add_action('关闭可关闭负载', 'load_switch', '0')
        elif key == 'water':
            self.add_action('消音（保留异常）', 'mute', '1')
        elif key == 'timer':
            seconds = QSpinBox()
            seconds.setRange(1, 1440)
            seconds.setValue(25)
            seconds.setSuffix(' 分钟')
            self.controls_layout.addWidget(seconds)
            self.add_action('设置并开始', 'timer_start', lambda: str(seconds.value() * 60))
            for title, action in [('暂停', 'timer_pause'), ('继续', 'timer_resume'), ('结束', 'timer_stop')]:
                self.add_action(title, action, '1')
        self.refresh()

    def add_action(self, title, action, value):
        button = QPushButton(title)
        button.setProperty('requestValue', value if isinstance(value, str) else '')
        button.clicked.connect(lambda: self.controller.request(action, value() if callable(value) else value))
        self.controls_layout.addWidget(button)
        self.action_buttons.append((button, action))

    def build_demo_inputs(self):
        group = QGroupBox('离线演示输入')
        grid = QGridLayout(group)
        self.demo_fields = {}
        for index, (key, title, values) in enumerate([
            ('rain', '屋外雨滴', [('干燥', '0'), ('雨湿', '1'), ('未知', '?')]),
            ('water', '厨房水浸', [('无水', '0'), ('有水', '1'), ('未知', '?')]),
            ('door', '门状态', [('跟随动作', 'auto'), ('关闭', '1'), ('未关闭', '0'), ('未知', '?')]),
            ('window', '窗状态', [('跟随动作', 'auto'), ('关闭', '1'), ('未关闭', '0'), ('未知', '?')]),
            ('demand', '模拟制冷需求', [('无需求', '0'), ('有需求', '1'), ('未知', '?')]),
        ]):
            combo = QComboBox()
            for label, data in values:
                combo.addItem(label, data)
            grid.addWidget(QLabel(title), 0, index)
            grid.addWidget(combo, 1, index)
            self.demo_fields[key] = combo
            combo.currentIndexChanged.connect(lambda _index, k=key, c=combo: self.controller.set_input(k, c.currentData()))
        for index, (key, title, low, high, initial, scale) in enumerate([
            ('temp', '温度 / °C', -40, 125, 26, 10),
            ('humid', '湿度 / %RH', 0, 100, 50, 10),
            ('lux', '环境光 / lx', 0, 200000, 300, 1),
        ]):
            field = QDoubleSpinBox()
            field.setRange(low, high)
            field.setDecimals(1 if scale == 10 else 0)
            field.setValue(initial)
            field.setKeyboardTracking(False)
            grid.addWidget(QLabel(title), 2, index)
            grid.addWidget(field, 3, index)
            self.demo_fields[key] = field
            field.valueChanged.connect(lambda value, k=key, s=scale: self.controller.set_input(k, str(round(value * s))))
        return group

    def sync_demo_inputs(self):
        for key, widget in self.demo_fields.items():
            value = 'auto' if key in ('door', 'window') else self.controller.state.get(key, '?')
            widget.blockSignals(True)
            if isinstance(widget, QComboBox):
                widget.setCurrentIndex(max(0, widget.findData(value)))
            elif value != '?':
                widget.setValue(int(value) / (10 if key in ('temp', 'humid') else 1))
            widget.blockSignals(False)

    def refresh(self):
        c = self.controller
        s = c.state
        fresh = c.fresh
        age = f'　最近状态：{max(0, time.monotonic() - c.last_state):.1f} 秒前' if c.last_state else ''
        self.status_label.setText(c.status + (f'　固件：{c.firmware}' if c.firmware else '') + age)
        self.setWindowTitle('智慧小屋上位机' + (' — 模拟数据' if c.mode == 'simulation' else ''))
        self.scene_live.setText('生效场景：' + SCENES.get(s.get('scene'), '未知') + ('（过期）' if s and not fresh else ''))
        ktv_item = self.scene_combo.model().item(self.scene_combo.findData('ktv'))
        if ktv_item is not None:
            ktv_item.setEnabled('ktv' in c.capabilities)
        self.scene_send.setEnabled(c.can('scene') and (self.scene_combo.currentData() != 'ktv' or 'ktv' in c.capabilities))
        if self._controls_signature != (s.get('scene') == 'ktv', 'demand_hold' in c.capabilities):
            self.select_device(self.selected_key)
            return
        self.disconnect_button.setEnabled(c.mode != 'offline')
        self.demo_group.setVisible(c.mode == 'simulation')
        self.house.update_state(s, self.selected_key, fresh)
        def number(key, divisor=1):
            v = s.get(key, '?')
            return '—' if v == '?' else f'{int(v) / divisor:g}'
        suffix = '（模拟）' if c.mode == 'simulation' else ('（过期）' if s and not fresh else '')
        self.environment.setText(f'温度：{number("temp", 10)} °C　湿度：{number("humid", 10)} %RH　环境光：{number("lux")} lx　{suffix}')
        key = self.selected_key
        rules = ''
        feedback_label = '状态'
        if c.mode == 'simulation' and c.simulator and key in ('door', 'window'):
            if getattr(c.simulator, key + '_feedback') != 'auto':
                feedback_label = '模拟反馈'
        if key == 'window':
            text = f'窗{feedback_label}：{contact(s.get("window"))}\n目标开度：{percent(s.get("window_target"))}\n控制：' + {'auto': '自动', 'manual': '手动接管'}.get(s.get('control'), '未知')
            if s.get('control') == 'manual':
                text += f'，剩余 {int(s.get("manual_ms", 0)) // 1000} 秒'
            rules = '雨湿时自动关窗，长期离家保持关闭。'
        elif key == 'door':
            text = '门' + feedback_label + '：' + contact(s.get('door'))
            rules = '回家自动开门，离家与睡眠自动关闭。'
        elif key in ('curtain', 'vent'):
            text = '目标开度：' + percent(s.get(key))
            rules = ('按光照与场景遮阳，手动控制60秒后恢复自动。' if key == 'curtain'
                     else '风口随制冷自动开启。')
        elif key == 'rain':
            text = '雨滴：' + {'0': '干燥', '1': '雨湿'}.get(s.get('rain'), '未知')
            rules = '雨停只解除防雨限制，再按场景和需求判断。'
        elif key == 'water':
            text = '水浸：' + {'0': '无水浸', '1': '检测到水浸'}.get(s.get('water'), '检测未知') + ('（报警保留）' if s.get('alarm') == '1' else '') + '\n消音：' + onoff(s.get('muted'))
            rules = '消音仅关闭提示声音，水浸异常继续显示。'
        elif key == 'loads':
            text = '可关闭负载：' + onoff(s.get('load_switch')) + '\n保留负载：' + onoff(s.get('load_keep'))
            rules = '离家关闭可关闭负载，保留常供电负载。'
        elif key == 'cooling':
            text = '制冷需求：' + onoff(s.get('demand')) + '\n模拟输出：' + onoff(s.get('cooling'))
            mode = {'auto': '自动', 'on': '手动开启', 'off': '手动关闭'}.get(s.get('demand_mode'), '未提供')
            text += '\n控制方式：' + (mode if 'demand_hold' in c.capabilities else '临时需求控制')
            rules = '手动保持，离家恢复自动。' if 'demand_hold' in c.capabilities else '旧固件使用临时需求控制。'
        elif key == 'timer':
            text = '状态：' + {'idle': '未开始', 'running': '运行', 'paused': '暂停', 'done': '已结束'}.get(s.get('timer'), '未知') + '\n剩余：' + remaining(s.get('timer_s'))
            rules = '台灯慢呼吸，暂停时常亮；窗帘保持原状态。'
            if s.get('scene') == 'ktv':
                rules += 'KTV灯效优先，计时继续。'
        else:
            is_ktv = s.get('scene') == 'ktv'
            text = ('KTV总亮度：' if is_ktv else '输出亮度：') + percent(s.get('ktv_brightness', '50') if is_ktv else s.get(key))
            text += '\n灯效：' + ({'warm': '日常暖光', 'rainbow': '流动彩虹', 'pulse': '彩色呼吸', 'party': '节拍跳色'}.get(s.get('light_effect', 'rainbow'), '未知') if is_ktv else '日常暖光')
            rules = '八灯统一调光，0%全灭。' if is_ktv else '手动亮度保持60秒，随后恢复自动。'
        if s and not fresh:
            text += '\n数据已过期'
        self.feedback_label.setText(text)
        self.rules_label.setText(rules)
        for button, action in self.action_buttons:
            button.setEnabled(c.can(action) and not (action == 'demand' and button.property('requestValue') == '1' and s.get('scene') in ('away', 'long_away')))
        self.availability.setText('' if fresh else '等待有效状态后开放控制。')
        if fresh and self.action_buttons and not any(c.can(a) for _, a in self.action_buttons):
            self.availability.setText('等待上一请求确认，或当前固件未开放此功能。')
        if s.get('scene') in ('away', 'long_away'):
            required = ['door', 'window'] if s['scene'] == 'long_away' else ['door']
            verdict = '均已关闭' if all(s[k] == '1' for k in required) else '尚未全部关闭'
            self.away_status.setText('离家检查：' + '、'.join(NAMES[k] for k in required) + ' · ' + verdict + ('（过期）' if not fresh else ''))
        else:
            self.away_status.setText('')
        self.request_label.setText(c.request_status)

    def add_event(self, stamp, kind, message):
        if self.events.rowCount() >= 300:
            self.events.removeRow(0)
        row = self.events.rowCount()
        self.events.insertRow(row)
        for col, text in enumerate((stamp, kind, message)):
            self.events.setItem(row, col, QTableWidgetItem(text))
        self.events.scrollToBottom()

    def export_logs(self):
        source = self.controller.mode if self.controller.mode != 'offline' else 'session'
        filename = f'smarthome_{source}_{datetime.now():%Y%m%d_%H%M%S}.csv'
        path, _ = QFileDialog.getSaveFileName(self, '保存当前会话', filename, 'CSV (*.csv)')
        if path:
            try:
                self.controller.export(path)
                QMessageBox.information(self, '已保存', path)
            except OSError as exc:
                QMessageBox.warning(self, '保存失败', str(exc))

    def closeEvent(self, event):
        self.controller.disconnect()
        if self.controller.archive_error:
            event.ignore()
            QMessageBox.warning(self, '记录未保存', '自动保存失败。请先导出当前会话，再关闭窗口。\n' + self.controller.archive_error)
            return
        super().closeEvent(event)
