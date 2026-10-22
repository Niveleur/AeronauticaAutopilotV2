import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
os.environ.setdefault('PYNPUT_BACKEND','dummy')
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch, Mock
import zipfile
from PIL import Image
from PyQt5.QtWidgets import QApplication, QWidget
from PyQt5.QtTest import QTest
from PyQt5.QtCore import Qt, QTimer, QSize
from PyQt5.QtGui import QResizeEvent
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

    def test_resize_during_construction_before_preview_exists(self):
        class EarlyResizeDialog(AircraftHudDialog):
            def resize(self, width, height):
                super().resize(width, height)
                # Native Windows may deliver this synchronously during setup.
                self.resizeEvent(QResizeEvent(QSize(width,height),QSize()))
        dialog=EarlyResizeDialog(self.parent)
        self.addCleanup(dialog.close)
        dialog.show()
        self.app.processEvents()
        self.assertTrue(dialog.isVisible())

    def test_menu_constructor_failure_keeps_main_window_and_logs_error(self):
        from AeroHelper.ui.main_window import MainWindow
        self.parent.is_running=False
        self.parent._show_message_dialog=Mock()
        with tempfile.TemporaryDirectory() as tmp:
            log=Path(tmp)/'AeroHelper.log'
            with patch('AeroHelper.ui.aircraft_hud_dialog.AircraftHudDialog',side_effect=RuntimeError('startup test failure')), \
                 patch('AeroHelper.ui.main_window.default_log_path',return_value=log):
                MainWindow._open_aircraft_hud_test(self.parent)
            self.assertIn('startup test failure',log.read_text())
        self.assertTrue(self.parent.isVisible())
        self.parent._show_message_dialog.assert_called_once()
        self.assertIn('still running',self.parent._show_message_dialog.call_args.args[-1])

    def test_display_failure_is_reported_without_escaping_qt_callback(self):
        payload={'image':Image.new('RGB',(640,480),'navy'),'reading':None,'report':{}}
        with patch('AeroHelper.ui.aircraft_hud_dialog.annotated_image',side_effect=RuntimeError('preview test failure')):
            self.dialog.show_result(payload)
        self.assertTrue(self.dialog.isVisible())
        self.assertIsNone(self.dialog._payload)
        self.assertIn('preview test failure',self.dialog.status.text())

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
                self.assertEqual(set(archive.namelist()),{'report.json','cockpit.png','annotated.png','hud-test-window.png','diagnostics.txt'})
                report=json.loads(archive.read('report.json'))
                self.assertEqual(report['size'],[640,480])
                self.assertIn('Source:',archive.read('diagnostics.txt').decode())
                with Image.open(archive.open('hud-test-window.png')) as screenshot:
                    self.assertEqual(screenshot.format,'PNG')
                    self.assertGreater(screenshot.width,640)
                self.assertIsNone(report['instruments']['altitude']['value'])

    def test_save_window_screenshot_works_without_a_successful_capture(self):
        self.dialog.status.setText('Capture failed: test diagnostic message')
        self.dialog.details.setPlainText('Build: test-build\nDiagnostic text visible without highlighting')
        self.assertIsNone(self.dialog._payload)
        self.assertTrue(self.dialog.screenshot_button.isEnabled())
        with tempfile.TemporaryDirectory() as tmp:
            filename=str(Path(tmp)/'hud-window')
            with patch('AeroHelper.ui.aircraft_hud_dialog.QFileDialog.getSaveFileName',return_value=(filename,'PNG')):
                QTest.mouseClick(self.dialog.screenshot_button,Qt.LeftButton)
            with Image.open(filename+'.png') as screenshot:
                self.assertEqual(screenshot.format,'PNG')
                ratio=self.dialog.devicePixelRatioF()
                self.assertEqual(screenshot.size,(round(self.dialog.width()*ratio),round(self.dialog.height()*ratio)))
        self.assertIn('screenshot saved',self.dialog.details.toPlainText())

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

    def test_real_hud_worker_uses_isolated_crops_and_exports_them(self):
        fixture=Path(__file__).parent/'fixtures'/'aircraft-tapes-29841ft-89kt.png'
        with Image.open(fixture) as image:
            worker=HudWorker(image.copy(),use_ocr=True)
        results=[]
        worker.completed.connect(results.append)
        engine=Mock()
        engine.extract_text.return_value='ALTITUDE 29841 GS 87 TAS 89'
        def region_text(path):
            if Path(path).name in ('side-panel-altitude.png','side-panel-altitude-card.png'): return ''
            name=Path(path).name
            return {'altitude-label.png':'ALT 00 29841', 'altitude-digits.png':'29841 29841',
                    'airspeed-label.png':'SPEED', 'airspeed-digits.png':'089'}[name]
        engine.extract_region_text.side_effect=region_text
        with patch('AeroHelper.ocr.normal_ocr.NormalOCR',return_value=engine):
            worker.run()
        self.assertEqual(len(results),1)
        report=results[0]['report']
        self.assertEqual(report['instruments']['altitude']['value'],29841)
        self.assertEqual(report['instruments']['airspeed']['value'],89)
        self.assertEqual(engine.extract_region_text.call_count,6)
        self.assertIsNone(report['pitch_degrees'])
        self.assertIsNone(report['roll_degrees'])
        self.assertFalse(report['controls_enabled'])
        self.dialog.show_result(results[0])
        self.app.processEvents()
        self.assertLessEqual(self.dialog.preview.pixmap().width(),self.dialog.preview.contentsRect().width())
        self.assertLessEqual(self.dialog.preview.pixmap().height(),self.dialog.preview.contentsRect().height())
        with tempfile.TemporaryDirectory() as tmp:
            filename=str(Path(tmp)/'regions.zip')
            with patch('AeroHelper.ui.aircraft_hud_dialog.QFileDialog.getSaveFileName',return_value=(filename,'ZIP')):
                self.dialog.save_report()
            with zipfile.ZipFile(filename) as archive:
                self.assertIn('altitude-readout.png',archive.namelist())
                self.assertIn('airspeed-readout.png',archive.namelist())
                exported=json.loads(archive.read('report.json'))
                self.assertEqual(exported['region_ocr']['airspeed']['digit_text'],'089')

    def test_wide_label_retry_preserves_day_capture_when_tight_label_is_clipped(self):
        fixture=Path(__file__).parent/'fixtures'/'aircraft-tapes-29841ft-89kt.png'
        with Image.open(fixture) as image: worker=HudWorker(image.copy(),use_ocr=True)
        results=[]
        worker.completed.connect(results.append)
        engine=Mock()
        engine.extract_text.return_value=''
        def region_text(path):
            if Path(path).name in ('side-panel-altitude.png','side-panel-altitude-card.png'): return ''
            return {'altitude-label.png':'ILT','altitude-label-wide.png':'ALT 00 29841',
                    'altitude-digits.png':'29841','airspeed-label.png':'SPEED',
                    'airspeed-digits.png':'089'}[Path(path).name]
        engine.extract_region_text.side_effect=region_text
        with patch('AeroHelper.ocr.normal_ocr.NormalOCR',return_value=engine):worker.run()
        self.assertEqual(len(results),1)
        report=results[0]['report']
        self.assertEqual(report['instruments']['altitude']['value'],29841)
        self.assertEqual(len(report['region_ocr']['altitude']['label_attempts']),2)
        self.assertEqual(report['ocr_status'],'OCR completed')
        self.assertFalse(report['controls_enabled'])

    def test_night_worker_confirms_an_occluded_alt_label_without_guessing(self):
        fixture=Path(__file__).parent/'fixtures'/'aircraft-tapes-night-29659ft-88kt.png'
        with Image.open(fixture) as image:
            worker=HudWorker(image.copy(),use_ocr=True)
        results=[]
        worker.completed.connect(results.append)
        engine=Mock()
        engine.extract_text.return_value='AIRSPEED 88 Knots ALTITUDE 29659 VERTICAL SPEED 0.1 ft/s'
        def region_text(path):
            if Path(path).name in ('side-panel-altitude.png','side-panel-altitude-card.png'): return ''
            return {'altitude-label.png':'AT','altitude-digits.png':'29659',
                    'airspeed-label.png':'SPEED','airspeed-digits.png':'088',
                    'altitude-label-wide.png':'29659'}[Path(path).name]
        engine.extract_region_text.side_effect=region_text
        with patch('AeroHelper.ocr.normal_ocr.NormalOCR',return_value=engine):worker.run()
        self.assertEqual(len(results),1)
        report=results[0]['report']
        self.assertEqual(report['instruments']['altitude']['value'],29659)
        self.assertEqual(report['instruments']['airspeed']['value'],88)
        self.assertIn('confirmed',report['tape_instruments']['altitude']['reason'])
        self.assertFalse(report['controls_enabled'])

    def test_panel_comparison_is_visible_and_exported_with_five_foot_tolerance(self):
        fixture=Path(__file__).parent/'fixtures'/'aircraft-tapes-night-29659ft-88kt.png'
        with Image.open(fixture) as image: worker=HudWorker(image.copy(),use_ocr=True)
        results=[]
        worker.completed.connect(results.append)
        engine=Mock()
        engine.extract_text.return_value='ALTITUDE 29664 ft AIRSPEED 88 Knots'
        def region_text(path):
            return {'side-panel-altitude.png':'ALTITUDE 29664 ft VERTICAL SPEED 0.1 ft/s',
                    'altitude-label.png':'ALT','altitude-digits.png':'29659',
                    'airspeed-label.png':'SPEED','airspeed-digits.png':'088'}[Path(path).name]
        engine.extract_region_text.side_effect=region_text
        with patch('AeroHelper.ocr.normal_ocr.NormalOCR',return_value=engine):worker.run()
        report=results[0]['report']
        self.assertEqual(report['altitude_check']['status'],'agree')
        self.assertEqual(report['altitude_check']['difference_ft'],5)
        self.assertEqual(report['instruments']['altitude']['value'],29659)
        self.dialog.show_result(results[0])
        self.assertIn('difference 5 ft',self.dialog.status.text())
        self.assertIn('left panel 29664 FT',self.dialog.status.text())
        with tempfile.TemporaryDirectory() as tmp:
            filename=str(Path(tmp)/'altitude-sources.zip')
            with patch('AeroHelper.ui.aircraft_hud_dialog.QFileDialog.getSaveFileName',return_value=(filename,'ZIP')):
                self.dialog.save_report()
            with zipfile.ZipFile(filename) as archive:
                self.assertIn('side-panel-altitude.png',archive.namelist())
                data=json.loads(archive.read('report.json'))
                self.assertEqual(data['altitude_check']['difference_ft'],5)
                self.assertEqual(data['altitude_check']['side_panel']['value'],29664)

    def test_panel_fallback_survives_a_full_screen_ocr_failure(self):
        worker=HudWorker(Image.new('RGB',(3440,1440),'navy'),use_ocr=True)
        results=[]
        worker.completed.connect(results.append)
        engine=Mock()
        engine.extract_region_text.return_value='ALTITUDE 29659 ft'
        engine.extract_text.side_effect=RuntimeError('full-screen OCR failed')
        with patch('AeroHelper.ocr.normal_ocr.NormalOCR',return_value=engine):worker.run()
        report=results[0]['report']
        self.assertEqual(report['altitude_check']['status'],'side_panel_fallback')
        self.assertEqual(report['instruments']['altitude']['value'],29659)
        self.assertIn('partially available',report['ocr_status'])
        self.assertFalse(report['controls_enabled'])

    def test_panel_card_retry_recovers_missing_feet_unit(self):
        fixture=Path(__file__).parent/'fixtures'/'aircraft-tapes-night-29659ft-88kt.png'
        with Image.open(fixture) as image: worker=HudWorker(image.copy(),use_ocr=True)
        results=[]
        worker.completed.connect(results.append)
        engine=Mock()
        engine.extract_text.return_value='ALTITUDE 29659 AIRSPEED 88 Knots'
        def region_text(path):
            return {'side-panel-altitude.png':'ALTITUDE 29659 VERTICAL SPEED 0.1 ft/s',
                    'side-panel-altitude-card.png':'ALTITUDE 29659 ft',
                    'altitude-label.png':'ALT','altitude-digits.png':'29659',
                    'airspeed-label.png':'SPEED','airspeed-digits.png':'088'}[Path(path).name]
        engine.extract_region_text.side_effect=region_text
        with patch('AeroHelper.ocr.normal_ocr.NormalOCR',return_value=engine):worker.run()
        report=results[0]['report']
        self.assertEqual(report['altitude_check']['status'],'agree')
        self.assertEqual(report['altitude_check']['difference_ft'],0)
        self.assertEqual(report['side_panel_ocr']['selected_attempt'],1)
        self.assertEqual(len(report['side_panel_ocr']['attempts']),2)
        self.assertFalse(report['controls_enabled'])

    def test_valid_disagreeing_panel_is_not_retried_to_force_agreement(self):
        fixture=Path(__file__).parent/'fixtures'/'aircraft-tapes-night-29659ft-88kt.png'
        with Image.open(fixture) as image: worker=HudWorker(image.copy(),use_ocr=True)
        results=[]
        worker.completed.connect(results.append)
        engine=Mock()
        engine.extract_text.return_value='ALTITUDE 29659 AIRSPEED 88 Knots'
        def region_text(path):
            return {'side-panel-altitude.png':'ALTITUDE 29640 ft',
                    'altitude-label.png':'ALT','altitude-digits.png':'29659',
                    'airspeed-label.png':'SPEED','airspeed-digits.png':'088'}[Path(path).name]
        engine.extract_region_text.side_effect=region_text
        with patch('AeroHelper.ocr.normal_ocr.NormalOCR',return_value=engine):worker.run()
        report=results[0]['report']
        self.assertEqual(report['altitude_check']['status'],'disagree')
        self.assertIsNone(report['instruments']['altitude']['value'])
        self.assertEqual(len(report['side_panel_ocr']['attempts']),1)
        self.assertNotIn('side-panel-altitude-card.png',[Path(c.args[0]).name for c in engine.extract_region_text.call_args_list])

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
