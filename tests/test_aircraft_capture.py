import unittest
from unittest.mock import patch, Mock
from PIL import Image
from AeroHelper.utils import aircraft_capture as capture


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.gui=Mock()
        self.gui.IsIconic.return_value=False
        self.gui.GetForegroundWindow.return_value=12
        self.gui.GetClientRect.return_value=(0,0,800,600)
        self.gui.ClientToScreen.side_effect=[(-1000,50),(-200,650)]
        self.patches=[patch.object(capture.window,'IS_WINDOWS',True),
                      patch.object(capture.window,'win32gui',self.gui),
                      patch.object(capture.window,'find_roblox_window',return_value=12)]
        for p in self.patches: p.start(); self.addCleanup(p.stop)

    def test_client_capture_handles_negative_monitor_coordinates(self):
        with patch.object(capture.ImageGrab,'grab',return_value=Image.new('RGB',(800,600),'navy')) as grab:
            image,bounds=capture.capture_roblox_client()
            self.assertEqual(bounds,(-1000,50,-200,650))
            self.assertEqual(image.size,(800,600))
            grab.assert_called_once_with(bbox=bounds,all_screens=True)

    def test_nonforeground_and_minimized_never_capture(self):
        for minimized,foreground in ((True,12),(False,99)):
            self.gui.IsIconic.return_value=minimized
            self.gui.GetForegroundWindow.return_value=foreground
            with patch.object(capture.ImageGrab,'grab') as grab:
                with self.assertRaises(RuntimeError): capture.capture_roblox_client()
                grab.assert_not_called()

    def test_focus_change_discards_capture(self):
        self.gui.GetForegroundWindow.side_effect=[12,99]
        with patch.object(capture.ImageGrab,'grab',return_value=Image.new('RGB',(800,600),'navy')):
            with self.assertRaisesRegex(RuntimeError,'Focus changed'): capture.capture_roblox_client()

    def test_black_frame_rejected(self):
        with patch.object(capture.ImageGrab,'grab',return_value=Image.new('RGB',(800,600),'black')):
            with self.assertRaisesRegex(RuntimeError,'black'): capture.capture_roblox_client()


if __name__=='__main__': unittest.main()
