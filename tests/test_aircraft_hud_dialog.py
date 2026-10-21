import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
os.environ.setdefault('PYNPUT_BACKEND','dummy')
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile
from PIL import Image
from PyQt5.QtWidgets import QApplication, QWidget
from PyQt5.QtTest import QTest
from PyQt5.QtCore import Qt, QTimer
from AeroHelper.ui.aircraft_hud_dialog import AircraftHudDialog, HudWorker


class DialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.parent=QWidget(); self.parent.show()
        self.dialog=AircraftHudDialog(self.parent); self.dialog.show()
        self.app.processEvents()
        self.addCleanup(self.parent.close)
        self.addCleanup(self.dialog.close)

    def wait_for_worker(self):
        deadline=time.monotonic()+10
        while self.dialog.worker is not None and time.monotonic()<deadline:
            QTest.qWait(10)
        self.assertIsNone(self.dialog.worker,'worker did not finish')

    def test_main_window_opens_persistent_modal_without_exec_loop(self):
        from AeroHelper.ui.main_window import MainWindow
        self.dialog.close()
        self.parent.is_running=False
        # Guard makes a regression to blocking exec_ fail instead of hanging.
        guard=QTimer()
        guard.setSingleShot(True)
        guard.timeout.connect(lambda: [w.reject() for w in self.app.topLevelWidgets()
                                       if isinstance(w,AircraftHudDialog)])
        guard.start(1000)
        start=time.monotonic()
        MainWindow._open_aircraft_hud_test(self.parent)
        elapsed=time.monotonic()-start
        guard.stop()
        self.dialog=self.parent._aircraft_hud_dialog
        self.assertLess(elapsed,.8,'HUD opener must not use exec_ because hide ends its event loop')
        self.assertEqual(self.dialog.windowModality(),Qt.ApplicationModal)
        self.assertTrue(self.dialog.isVisible())
        first=self.dialog
        MainWindow._open_aircraft_hud_test(self.parent)
        self.assertIs(first,self.parent._aircraft_hud_dialog)

    def test_countdown_hides_windows_and_success_restores_them(self):
        with patch('AeroHelper.ui.aircraft_hud_dialog.bring_roblox_to_front',return_value=False), \
             patch('AeroHelper.ui.aircraft_hud_dialog.capture_roblox_client',return_value=(Image.new('RGB',(640,480),'navy'),(0,0,640,480))):
            self.dialog.begin_capture()
            self.assertFalse(self.parent.isVisible())
            self.assertFalse(self.dialog.isVisible())
            self.assertTrue(self.dialog._capture_timer.isActive())
            self.assertFalse(self.dialog.capture_button.isEnabled())
            self.dialog._capture_timer.stop()
            self.dialog._start_live_worker()
            self.wait_for_worker()
        self.assertTrue(self.parent.isVisible())
        self.assertTrue(self.dialog.isVisible())
        self.assertTrue(self.dialog.capture_button.isEnabled())
        self.assertTrue(self.dialog.save_button.isEnabled())
        self.assertFalse(self.dialog.preview.pixmap().isNull())
        self.assertIsNone(self.dialog._payload['report']['pitch_degrees'])
        self.assertFalse(self.dialog._payload['report']['controls_enabled'])
        with tempfile.TemporaryDirectory() as tmp:
            filename=str(Path(tmp)/'capture.zip')
            with patch('AeroHelper.ui.aircraft_hud_dialog.QFileDialog.getSaveFileName',return_value=(filename,'ZIP')):
                self.dialog.save_report()
            with zipfile.ZipFile(filename) as archive:
                self.assertEqual(set(archive.namelist()),{'report.json','cockpit.png','annotated.png'})
                report=json.loads(archive.read('report.json'))
                self.assertEqual(report['size'],[640,480])
                self.assertIsNone(report['instruments']['altitude']['value'])

    def test_failed_capture_restores_ui_and_removes_stale_results(self):
        self.dialog._payload={'stale':True}
        with patch('AeroHelper.ui.aircraft_hud_dialog.bring_roblox_to_front'), \
             patch('AeroHelper.ui.aircraft_hud_dialog.capture_roblox_client',side_effect=RuntimeError('Roblox not foreground')):
            self.dialog.begin_capture()
            self.dialog._capture_timer.stop()
            self.dialog._start_live_worker()
            self.wait_for_worker()
        self.assertTrue(self.dialog.isVisible())
        self.assertTrue(self.parent.isVisible())
        self.assertIsNone(self.dialog._payload)
        self.assertFalse(self.dialog.save_button.isEnabled())
        self.assertIn('not foreground',self.dialog.status.text())

    def test_import_and_worker_ocr_failures_are_diagnostic(self):
        with tempfile.TemporaryDirectory() as tmp:
            filename=str(Path(tmp)/'cockpit.png')
            Image.new('RGB',(640,480),'navy').save(filename)
            with patch('AeroHelper.ui.aircraft_hud_dialog.QFileDialog.getOpenFileName',return_value=(filename,'PNG')):
                self.dialog.open_image()
                self.wait_for_worker()
            self.assertEqual(self.dialog._payload['report']['source'],'imported screenshot')
        results=[]
        worker=HudWorker(Image.new('RGB',(640,480),'navy'),use_ocr=True)
        worker.completed.connect(results.append)
        with patch('AeroHelper.ocr.normal_ocr.NormalOCR',side_effect=RuntimeError('model unavailable')):
            worker.run()
        self.assertEqual(len(results),1)
        self.assertIn('model unavailable',results[0]['report']['ocr_status'])
        self.assertIsNone(results[0]['report']['instruments']['altitude']['value'])


if __name__=='__main__': unittest.main()
