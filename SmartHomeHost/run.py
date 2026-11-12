import argparse
import sys
import traceback
from pathlib import Path
from PySide6.QtWidgets import QApplication, QMessageBox


def main():
    parser = argparse.ArgumentParser(description='智慧小屋 Windows 上位机')
    parser.add_argument('--demo', action='store_true', help='启动独立离线演示，不连接硬件')
    parser.add_argument('--legacy', action='store_true', help='使用旧版二维诊断界面')
    args = parser.parse_args()
    if args.legacy:
        from smarthome.window import MainWindow
    else:
        from smarthome.web_window import MainWindow
    app = QApplication(sys.argv[:1])
    app.setApplicationName('智慧小屋上位机')
    def report_error(exc_type, exc, tb):
        message = ''.join(traceback.format_exception(exc_type, exc, tb))
        folder = Path(__file__).resolve().parent / 'logs'
        try:
            folder.mkdir(exist_ok=True)
            with (folder / 'application_errors.log').open('a', encoding='utf-8') as handle:
                handle.write(message + '\n')
        except OSError:
            pass
        QMessageBox.critical(None, '程序错误', str(exc) + '\n详见 logs/application_errors.log')
    sys.excepthook = report_error
    window = MainWindow()
    window.show()
    if args.demo:
        window.start_demo()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
