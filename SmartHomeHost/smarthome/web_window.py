"""Native Qt WebEngine host for the packaged Three.js frontend."""
from __future__ import annotations

import json
from pathlib import Path

from .graphics import configure_webengine_graphics

configure_webengine_graphics()

from PySide6.QtCore import QFile, QIODevice, QUrl, Qt, Signal
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import (
    QWebEnginePage, QWebEngineProfile, QWebEngineScript, QWebEngineSettings,
    QWebEngineUrlRequestInterceptor, QWebEngineUrlRequestInfo,
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QLabel, QMainWindow, QMessageBox, QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from .asset_server import AssetBuildError, AssetServer
from .bridge import HostBridge
from .controller import Controller


def same_origin(url: QUrl, origin: QUrl) -> bool:
    return (url.isValid() and url.scheme() == origin.scheme()
            and url.host() == origin.host() and url.port() == origin.port()
            and not url.userName() and not url.password())


class LocalRequestInterceptor(QWebEngineUrlRequestInterceptor):
    """Prevent external network/file requests even from a local document."""

    def __init__(self, origin, parent=None):
        super().__init__(parent)
        self.origin = QUrl(origin)

    def interceptRequest(self, info):
        url = info.requestUrl()
        if same_origin(url, self.origin):
            return
        # Embedded textures and loader-created blobs need no remote transport.
        images = (QWebEngineUrlRequestInfo.ResourceType.ResourceTypeImage,
                  QWebEngineUrlRequestInfo.ResourceType.ResourceTypeFontResource)
        if url.scheme() == 'data' and info.resourceType() in images:
            return
        if url.scheme() == 'blob' and url.toString().startswith('blob:' + self.origin.toString() + '/'):
            return
        info.block(True)


class LocalPage(QWebEnginePage):
    navigationBlocked = Signal(str)

    def __init__(self, profile, origin, parent=None):
        super().__init__(profile, parent)
        self.origin = QUrl(origin)

    def acceptNavigationRequest(self, url, _navigation_type, _is_main_frame):
        allowed = same_origin(url, self.origin)
        if not allowed:
            self.navigationBlocked.emit(url.toString())
        return allowed

    def createWindow(self, _window_type):
        return None


def install_webchannel_script(page):
    # Importing QtWebChannel registers this Qt resource. No copied JS or CDN is
    # needed, and DocumentCreation guarantees availability before frontend code.
    resource = QFile(':/qtwebchannel/qwebchannel.js')
    if not resource.open(QIODevice.OpenModeFlag.ReadOnly):
        raise AssetBuildError('Qt WebChannel 内置脚本无法读取，请重新安装 PySide6。')
    try:
        source = bytes(resource.readAll()).decode('utf-8')
    finally:
        resource.close()
    script = QWebEngineScript()
    script.setName('smarthome-qwebchannel')
    script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
    script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
    script.setRunsOnSubFrames(False)
    script.setSourceCode(source)
    page.scripts().insert(script)
    return script


class MainWindow(QMainWindow):
    def __init__(self, parent=None, *, dist_path=None):
        super().__init__(parent)
        self.setWindowTitle('智慧小屋 · 3D 上位机')
        self.resize(1440, 900)
        self.setMinimumSize(960, 600)
        self.controller = Controller(self)
        self.bridge = HostBridge(self.controller, self)
        self.asset_server = None
        self.profile = None
        self.page = None
        self.view = None
        self.channel = None
        self.interceptor = None
        self._view_ready = False
        self.load_error = ''
        self._closing = False
        self._dist = Path(dist_path) if dist_path else Path(__file__).resolve().parents[1] / 'frontend' / 'dist'
        self.stack = QStackedWidget(self)
        self.setCentralWidget(self.stack)
        self.failure = QWidget(self.stack)
        layout = QVBoxLayout(self.failure)
        layout.setContentsMargins(48, 48, 48, 48)
        layout.addStretch()
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setTextFormat(Qt.TextFormat.PlainText)
        self.error_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.error_label)
        retry = QPushButton('重试加载 3D 界面')
        retry.clicked.connect(self.reload_frontend)
        layout.addWidget(retry)
        export = QPushButton('导出当前会话记录')
        export.clicked.connect(self._export_from_failure)
        layout.addWidget(export)
        hint = QLabel('旧版诊断界面可使用 run.py --legacy 启动。')
        layout.addWidget(hint)
        layout.addStretch()
        self.stack.addWidget(self.failure)
        self.reload_frontend()

    def _show_error(self, message):
        self.load_error = message
        self.error_label.setText(message)
        self.stack.setCurrentWidget(self.failure)

    def _export_from_failure(self):
        result = json.loads(self.bridge.exportLogs())
        if not result.get('cancelled'):
            self.error_label.setText(self.load_error + '\n\n' + result['message'])

    def reload_frontend(self):
        try:
            if self.asset_server is None:
                self.asset_server = AssetServer(self._dist)
            if not self._view_ready:
                self._create_web_view()
            self.load_error = ''
            self.stack.setCurrentWidget(self.view)
            self.view.load(QUrl(self.asset_server.url))
        except (AssetBuildError, OSError, RuntimeError) as exc:
            self._show_error(str(exc))

    def _create_web_view(self):
        if self.view is not None:
            # A failed initialization must not retry with QWebEngineView's
            # unrestricted default page or a half-configured WebChannel.
            self.view.deleteLater()
            self.view = None
            if self.profile is not None:
                self.profile.deleteLater()
        self.view = QWebEngineView(self.stack)
        # A private profile keeps bridge-enabled pages out of persistent browser
        # history, and never shares cookies/service workers with remote browsing.
        self.profile = QWebEngineProfile(self)
        self.interceptor = LocalRequestInterceptor(self.asset_server.origin, self.profile)
        self.profile.setUrlRequestInterceptor(self.interceptor)
        self.profile.downloadRequested.connect(lambda download: download.cancel())
        self.page = LocalPage(self.profile, self.asset_server.origin, self.view)
        self.page.navigationBlocked.connect(self._navigation_blocked)
        settings = self.page.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.FullScreenSupportEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)
        self.channel = QWebChannel(self.page)
        self.channel.registerObject('host', self.bridge)
        self.page.setWebChannel(self.channel, QWebEngineScript.ScriptWorldId.MainWorld)
        install_webchannel_script(self.page)
        self.view.setPage(self.page)
        self.view.loadFinished.connect(self._load_finished)
        self.page.fullScreenRequested.connect(self._fullscreen_requested)
        self.page.renderProcessTerminated.connect(self._renderer_terminated)
        self.stack.addWidget(self.view)
        self._view_ready = True

    def _navigation_blocked(self, url):
        self.controller.log('页面安全', '已阻止外部页面导航：' + url[:200])

    def _load_finished(self, ok):
        if self._closing:
            return
        if ok:
            self.load_error = ''
        else:
            self._show_error('本地 3D 页面加载失败。请确认 frontend/dist 构建完整后重试。')

    def _renderer_terminated(self, _status, exit_code):
        if not self._closing:
            self._show_error(f'3D 渲染进程已退出（代码 {exit_code}）。请重试；若持续失败，请检查显卡驱动及 WebGL2 支持。')

    def _fullscreen_requested(self, request):
        if not same_origin(request.origin(), QUrl(self.asset_server.origin)):
            request.reject()
            return
        request.accept()
        if request.toggleOn():
            self.showFullScreen()
        else:
            self.showNormal()

    def start_demo(self):
        return self.bridge.startDemo()

    def closeEvent(self, event):
        if self.bridge._exporting:
            event.ignore()
            return
        if self._closing:
            event.accept()
            return
        self.controller.disconnect()
        if self.controller.archive_error:
            event.ignore()
            QMessageBox.warning(self, '记录未保存',
                                '自动保存失败。请先导出当前会话，再关闭窗口。\n' + self.controller.archive_error)
            return
        self._closing = True
        self.controller.timer.stop()
        self.bridge.dispose()
        if self.view is not None:
            self.view.stop()
        if self.asset_server is not None:
            self.asset_server.close()
        super().closeEvent(event)
