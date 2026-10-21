"""Packaged Windows HUD check for CI; never captures the user's desktop."""
import json
from pathlib import Path
import sys
import traceback
from PIL import Image
from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QMainWindow
from AeroHelper.ui.main_window import MainWindow
from AeroHelper.utils.build_info import build_revision


def run_hud_smoke(app, report_path):
    report = {'ok': False, 'frozen': bool(getattr(sys, 'frozen', False)),
              'build_revision': build_revision()}
    host = QMainWindow()
    host.is_running = False
    done = False
    original_hook = sys.excepthook

    def finish(error=None):
        nonlocal done
        if done:
            return
        done = True
        if error:
            report['error'] = str(error)
        else:
            report['ok'] = True
        try:
            Path(report_path).write_text(json.dumps(report, indent=2), encoding='utf-8')
        finally:
            app.exit(1 if error else 0)

    def hook(kind, value, tb):
        finish(''.join(traceback.format_exception(kind, value, tb)))

    def dialog_error(*args):
        raise RuntimeError('HUD menu startup failed: ' + str(args[-1]))

    host._show_message_dialog = dialog_error
    sys.excepthook = hook

    def check_rendered_result():
        try:
            dialog = host._aircraft_hud_dialog
            if dialog.worker is not None:
                QTimer.singleShot(50, check_rendered_result)
                return
            assert dialog.isVisible(), 'HUD dialog not visible'
            assert dialog._payload is not None, dialog.status.text()
            assert not dialog.preview.pixmap().isNull(), 'Preview did not render'
            assert dialog._payload['report']['controls_enabled'] is False
            report['preview_rendered'] = True
            finish()
        except Exception:
            finish(traceback.format_exc())

    def open_menu():
        try:
            host.show()
            # Exercise the actual menu callback and native Qt window events.
            MainWindow._open_aircraft_hud_test(host)
            dialog = host._aircraft_hud_dialog
            assert dialog.isVisible(), 'HUD menu did not open its window'
            report['menu_opened'] = True
            dialog.resize(900, 700)
            dialog._start_worker(Image.new('RGB', (640, 480), 'navy'))
            QTimer.singleShot(50, check_rendered_result)
        except Exception:
            finish(traceback.format_exc())

    QTimer.singleShot(0, open_menu)
    QTimer.singleShot(30000, lambda: finish('HUD smoke check timed out'))
    try:
        return app.exec_()
    finally:
        sys.excepthook = original_hook
        dialog = getattr(host, '_aircraft_hud_dialog', None)
        if dialog is not None and dialog.worker is not None:
            dialog.worker.wait(1000)
        host.close()
