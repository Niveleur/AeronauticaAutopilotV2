"""Read-only session collection. No keyboard, mouse or flight-control inputs."""
from datetime import datetime, timezone
from pathlib import Path
import json
import time
import threading
import zipfile
import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal
from AeroHelper.utils.aircraft_capture import capture_roblox_client
from AeroHelper.utils.build_info import build_revision


def instrument_crops(image, reading):
    """Save instrument regions only; the ADI box is an unconfirmed layout guess."""
    w,h = image.size
    boxes = {
        'adi': (int(h*.25),int(h*.70),min(w,int(h*.54)),int(h*.995)),
        'left-panel': (0,int(h*.46),min(w,int(h*.18)),int(h*.70)),
    }
    if reading.tape_rails:
        left,right,top,bottom = reading.tape_rails
        margin = int((bottom-top)*.35)
        boxes['hud'] = (max(0,left-margin),max(0,top-margin),
                        min(w,right+margin),min(h,bottom+margin))
    else:
        boxes['hud'] = (int(w*.30),int(h*.12),int(w*.70),int(h*.92))
    return {name: (box,image.crop(box)) for name,box in boxes.items() if box[2]>box[0] and box[3]>box[1]}


def adi_colour_sample(image):
    """Chroma evidence for later review, NOT calibrated attitude or a boundary."""
    rgb = np.asarray(image.convert('RGB')).astype(np.int16)
    red,green,blue = rgb[:,:,0],rgb[:,:,1],rgb[:,:,2]
    return {'blue_fraction': float(((blue-red>18)&(blue>green)).mean()),
            'brown_fraction': float(((red-blue>18)&(red>green)).mean()),
            'pitch_degrees': None, 'roll_degrees': None,
            'region_confirmed': False,
            'reason': 'Unconfirmed standard-layout ADI crop; scenery can affect tint counts.'}


class RecordingWorker(QThread):
    progress = pyqtSignal(object)
    saved = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, folder, parent=None, duration=600, interval=2, max_bytes=200*1024*1024):
        super().__init__(parent)
        self.folder = Path(folder)
        self.duration, self.interval, self.max_bytes = duration,interval,max_bytes
        self._stop = threading.Event()

    def request_stop(self):
        self._stop.set()
        self.requestInterruption()

    def run(self):
        # Source files remain on disk even if ZIP creation fails or the app exits.
        try:
            self.folder.mkdir(parents=True,exist_ok=False)
            summary = {'build':build_revision(),'started_utc':datetime.now(timezone.utc).isoformat(),
                       'controls_enabled':False,'target_interval_seconds':self.interval,
                       'maximum_duration_seconds':self.duration,'frames':0,'capture_failures':0,'analysis_failures':0,
                       'altitude_agreements':0,'altitude_disagreements':0,
                       'altitude_unavailable':0,'airspeed_unavailable':0,
                       'attitude_calibrated':False,'stop_reason':'time limit'}
            (self.folder/'session.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
            from AeroHelper.ocr.normal_ocr import NormalOCR
            from AeroHelper.ui.aircraft_hud_dialog import HudWorker
            engine = NormalOCR()  # Reused across frames; model initialization only once.
            started = time.monotonic()
            used_bytes = 0
            with (self.folder/'samples.jsonl').open('a',encoding='utf-8') as log:
                while time.monotonic()-started < self.duration:
                    if self._stop.is_set():
                        summary['stop_reason'] = 'user stopped'
                        break
                    began = time.monotonic()
                    stamp = datetime.now(timezone.utc).isoformat()
                    try:
                        image,bounds = capture_roblox_client()
                    except Exception as exc:
                        summary['capture_failures'] += 1
                        record = {'captured_utc':stamp,'status':'capture_skipped','reason':str(exc),
                                  'controls_enabled':False}
                    else:
                        # Run synchronously inside this worker. There is no queue
                        # of screenshots accumulating while slow OCR is running.
                        analyzer = HudWorker(image,use_ocr=True,engine=engine,full_screen_ocr=False)
                        results,errors = [],[]
                        analyzer.completed.connect(results.append)
                        analyzer.failed.connect(errors.append)
                        analyzer.run()
                        if not results:
                            summary['analysis_failures'] += 1
                            record = {'captured_utc':stamp,'status':'analysis_failed','reason':'; '.join(errors)}
                        else:
                            payload = results[0]
                            report = payload['report']
                            report.update(captured_utc=stamp,source='Roblox client recording',desktop_bounds=bounds)
                            index = summary['frames']
                            report['crops'] = {}
                            for name,(box,crop) in instrument_crops(image,payload['reading']).items():
                                filename = f'{index:05d}-{name}.png'
                                crop.save(self.folder/filename)
                                used_bytes += (self.folder/filename).stat().st_size
                                report['crops'][name] = {'file':filename,'box':box}
                                if name == 'adi': report['adi_colour'] = adi_colour_sample(crop)
                            summary['frames'] += 1
                            status = report['altitude_check']['status']
                            if status == 'agree': summary['altitude_agreements'] += 1
                            if status == 'disagree': summary['altitude_disagreements'] += 1
                            if report['instruments']['altitude']['value'] is None: summary['altitude_unavailable'] += 1
                            if report['instruments']['airspeed']['value'] is None: summary['airspeed_unavailable'] += 1
                            report['processing_seconds'] = time.monotonic()-began
                            report['reading_age_seconds'] = report['processing_seconds']
                            report['freshness'] = 'delayed' if report['reading_age_seconds'] > 5 else 'recent'
                            record = {'status':'sample','report':report}
                        image.close()
                    log.write(json.dumps(record)+'\n')
                    log.flush()
                    self.progress.emit({'summary':dict(summary),'latest':record})
                    if used_bytes >= self.max_bytes:
                        summary['stop_reason'] = 'storage limit'
                        break
                    while time.monotonic()-began < self.interval and not self._stop.is_set():
                        self.msleep(100)
            summary['elapsed_seconds'] = time.monotonic()-started
            summary['ended_utc'] = datetime.now(timezone.utc).isoformat()
            (self.folder/'session.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
            archive_path = self.folder.with_suffix('.zip')
            with zipfile.ZipFile(archive_path,'w',compression=zipfile.ZIP_DEFLATED) as archive:
                for path in sorted(self.folder.iterdir()):
                    archive.write(path,path.name)
            self.saved.emit({'path':str(archive_path),'summary':summary})
        except Exception as exc:
            self.failed.emit(f'{exc}. Saved source files, if any: {self.folder}')
