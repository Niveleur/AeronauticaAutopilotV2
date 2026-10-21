import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('PYNPUT_BACKEND', 'dummy')
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QDialog, QPushButton
from AeroHelper.ui.main_window import MainWindow


class MainWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        patches = [patch.dict(os.environ, {'AEROHELPER_CONSENT_ACCEPTED': 'false'}),
                   patch('AeroHelper.config.app_data_dir', return_value=root),
                   patch('AeroHelper.config.aerohelper_env_path', return_value=root / 'AeroHelper.env')]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        self.window = MainWindow(version='4.1.6 Beta')
        self.addCleanup(self.window.close)
        self.window.show()
        self.app.processEvents()

    def test_first_run_has_enabled_controls_and_no_consent_prompt(self):
        self.assertTrue(self.window.isVisible())
        self.assertTrue(self.window.start_button.isEnabled())
        self.assertTrue(all(button.isEnabled() for button in self.window.mode_buttons.values()))
        self.assertFalse(any(dialog.isVisible() for dialog in self.window.findChildren(QDialog)))
        # Removing the prompt must not record acceptance on the user's behalf.
        self.assertFalse(self.window.config.get_consent_accepted())

    def test_modes_and_locking_work_without_route_management_widgets(self):
        self.assertFalse(any(button.text() == 'Routes' for button in self.window.findChildren(QPushButton)))
        for mode in ('AutoPilot', 'AutoSteer', 'Monitoring'):
            self.window.on_mode_changed(mode)
            self.window.lock_fields()
            self.window.unlock_fields()
            self.assertEqual(self.window.config.get_mode(), mode)
            self.assertFalse(any(button.text() == 'Routes' for button in self.window.findChildren(QPushButton)))

    def test_start_and_stop_do_not_require_consent(self):
        started, stopped = [], []
        self.window.start_requested.connect(lambda: started.append(True))
        self.window.stop_requested.connect(lambda: stopped.append(True))
        self.window.on_mode_changed('AutoSteer')
        self.window.interval_input.setText('15')
        self.window.multiplier_input.setText('1.0')
        # No Controller is attached: this tests UI signals without flight inputs.
        QTest.mouseClick(self.window.start_button, Qt.LeftButton)
        self.assertEqual(started, [True])
        self.assertTrue(self.window.is_running)
        self.window.on_stop_clicked()
        self.assertEqual(stopped, [True])
        self.assertFalse(self.window.is_running)
        self.assertFalse(self.window.config.get_consent_accepted())


if __name__ == '__main__':
    unittest.main()
