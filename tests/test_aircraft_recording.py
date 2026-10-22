import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
import zipfile
from PIL import Image
from AeroHelper.ui.aircraft_recording import RecordingWorker,adi_colour_sample,instrument_crops
from AeroHelper.automation.aircraft_hud import analyze_cockpit


class RecordingTests(unittest.TestCase):
    def test_tint_evidence_is_not_reported_as_attitude(self):
        for colour,key in [((60,130,180),'blue_fraction'),((140,100,70),'brown_fraction')]:
            result=adi_colour_sample(Image.new('RGB',(20,20),colour))
            self.assertEqual(result[key],1.)
            self.assertIsNone(result['pitch_degrees'])
            self.assertIsNone(result['roll_degrees'])
            self.assertFalse(result['region_confirmed'])
        result=adi_colour_sample(Image.new('RGB',(20,20),'white'))
        self.assertEqual(result['blue_fraction'],0.)
        self.assertEqual(result['brown_fraction'],0.)

    def test_capture_failure_then_sample_exports_crops_and_agreement(self):
        image=Image.new('RGB',(3440,1440),(80,90,110))
        fixture=Path(__file__).parent/'fixtures'/'aircraft-tapes-29841ft-89kt.png'
        with Image.open(fixture) as crop:image.paste(crop,(1000,300))
        engine=Mock()
        def region_text(path):
            return {'side-panel-altitude.png':'ALTITUDE 29841 ft',
                    'altitude-label.png':'ALT','altitude-digits.png':'29841',
                    'airspeed-label.png':'SPEED','airspeed-digits.png':'089'}[Path(path).name]
        engine.extract_region_text.side_effect=region_text
        with tempfile.TemporaryDirectory() as tmp:
            worker=RecordingWorker(Path(tmp)/'session',interval=0,max_bytes=1)
            events,saved,failed=[],[],[]
            def progress(event):
                events.append(event)
                if event['latest']['status']=='sample':worker.request_stop()
            worker.progress.connect(progress)
            worker.saved.connect(saved.append)
            worker.failed.connect(failed.append)
            with patch('AeroHelper.ui.aircraft_recording.capture_roblox_client',
                       side_effect=[RuntimeError('not foreground'),(image,(0,0,3440,1440))]), \
                 patch('AeroHelper.ocr.normal_ocr.NormalOCR',return_value=engine):
                worker.run()
            self.assertEqual(failed,[])
            self.assertEqual(len(saved),1)
            engine.extract_text.assert_not_called()
            summary=saved[0]['summary']
            self.assertEqual(summary['frames'],1)
            self.assertEqual(summary['capture_failures'],1)
            self.assertEqual(summary['altitude_agreements'],1)
            self.assertEqual(summary['stop_reason'],'storage limit')
            with zipfile.ZipFile(saved[0]['path']) as archive:
                self.assertEqual(set(archive.namelist()),{'session.json','samples.jsonl',
                    '00000-adi.png','00000-hud.png','00000-left-panel.png'})
                rows=[json.loads(line) for line in archive.read('samples.jsonl').decode().splitlines()]
                self.assertEqual(rows[0]['status'],'capture_skipped')
                report=rows[1]['report']
                self.assertFalse(report['controls_enabled'])
                self.assertEqual(report['instruments']['airspeed']['value'],89)
                self.assertIsNone(report['pitch_degrees'])
                self.assertFalse(report['adi_colour']['region_confirmed'])
                self.assertGreaterEqual(report['reading_age_seconds'],0)
                with archive.open('00000-adi.png') as stream,Image.open(stream) as crop:
                    self.assertLess(crop.width,500)
                    self.assertLess(crop.height,500)
            # Source log survives separately from the ZIP.
            self.assertTrue((worker.folder/'samples.jsonl').exists())

    def test_small_images_never_produce_full_screen_adi_crop(self):
        image=Image.new('RGB',(640,480),'white')
        crops=instrument_crops(image,analyze_cockpit(image))
        self.assertEqual(set(crops),{'adi','hud','left-panel'})
        self.assertLess(crops['adi'][1].width,image.width//2)

    def test_background_thread_delivers_processed_frame_and_finishes(self):
        import time
        from PyQt5.QtWidgets import QApplication
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as tmp:
            worker=RecordingWorker(Path(tmp)/'session',max_bytes=1,interval=0)
            saved,errors=[],[]
            worker.saved.connect(saved.append)
            worker.failed.connect(errors.append)
            engine=Mock()
            engine.extract_region_text.return_value=''
            with patch('AeroHelper.ocr.normal_ocr.NormalOCR',return_value=engine), \
                 patch('AeroHelper.ui.aircraft_recording.capture_roblox_client',
                       return_value=(Image.new('RGB',(640,480),'black'),None)):
                worker.start()
                deadline=time.monotonic()+10
                while worker.isRunning() and time.monotonic()<deadline:
                    app.processEvents()
                    worker.wait(10)
                worker.request_stop()
                self.assertTrue(worker.wait(1000))
                app.processEvents()
            self.assertEqual(errors,[])
            self.assertEqual(saved[0]['summary']['frames'],1)

    def test_stop_before_thread_start_saves_an_empty_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            worker=RecordingWorker(Path(tmp)/'session')
            worker.request_stop()
            saved=[]
            worker.saved.connect(saved.append)
            with patch('AeroHelper.ocr.normal_ocr.NormalOCR'), \
                 patch('AeroHelper.ui.aircraft_recording.capture_roblox_client') as capture:
                worker.run()
            capture.assert_not_called()
            self.assertEqual(saved[0]['summary']['frames'],0)
            self.assertEqual(saved[0]['summary']['stop_reason'],'user stopped')

    def test_initialization_failure_keeps_source_folder_and_reports_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            worker=RecordingWorker(Path(tmp)/'session')
            errors=[]
            worker.failed.connect(errors.append)
            with patch('AeroHelper.ocr.normal_ocr.NormalOCR',side_effect=RuntimeError('model unavailable')):
                worker.run()
            self.assertIn('model unavailable',errors[0])
            self.assertTrue((worker.folder/'session.json').exists())
