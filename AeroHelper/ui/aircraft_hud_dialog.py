"""Read-only capture and diagnostics; deliberately contains no flight inputs."""
from dataclasses import asdict
from datetime import datetime, timezone
import io
import json
import re
from pathlib import Path
import tempfile
import zipfile
from PIL import Image, ImageDraw, ImageOps
from PyQt5.QtCore import Qt, QThread, QTimer, pyqtSignal, QByteArray, QBuffer, QIODevice, QEvent
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import (QApplication, QCheckBox, QDialog, QFileDialog,
                            QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout, QSizePolicy)
from AeroHelper.automation.aircraft_hud import (analyze_cockpit, parse_instruments,
                                                tape_digit_boxes, tape_label_boxes, tape_label_recognized, parse_tape_readout,
                                                reconcile_instruments, InstrumentCandidate,
                                                side_panel_altitude_box, side_panel_altitude_card_box, parse_side_panel_altitude,
                                                assess_altitude)
from AeroHelper.utils.aircraft_capture import capture_roblox_client
from AeroHelper.utils.window import bring_roblox_to_front
from AeroHelper.utils.build_info import build_revision


class HudWorker(QThread):
    captured = pyqtSignal(object)
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, image=None, use_ocr=False, parent=None, engine=None, full_screen_ocr=True, previous_reading=None):
        super().__init__(parent)
        self.image = image
        self.use_ocr = use_ocr
        self.engine = engine
        self.full_screen_ocr = full_screen_ocr
        self.previous_reading = previous_reading

    def run(self):
        try:
            image, bounds = (self.image.copy(), None) if self.image is not None else capture_roblox_client()
            captured_utc = datetime.now(timezone.utc).isoformat()
            self.captured.emit(image)
            reading = analyze_cockpit(image,self.previous_reading)
            text, ocr_status = '', 'OCR not requested'
            region_ocr, tape_readings = {}, {}
            panel_reading = InstrumentCandidate(None,None,'Left-panel OCR not requested')
            panel_ocr = {'box': side_panel_altitude_box(image.size), 'text': '', 'error': None, 'attempts': []}
            if self.use_ocr:
                try:
                    # Existing platform-aware OCR pipeline, on a worker thread.
                    from AeroHelper.ocr.normal_ocr import NormalOCR
                    engine = self.engine if self.engine is not None else NormalOCR()
                    with tempfile.TemporaryDirectory(prefix='aerohelper_hud_') as tmp:
                        filename = str(Path(tmp) / 'cockpit.png')
                        if self.full_screen_ocr:
                            image.save(filename)
                        panel_reading = InstrumentCandidate(None,None,'Left-panel region unavailable')
                        # Retry source recognition, never retry to force numerical
                        # agreement with the cockpit. A valid broad result wins.
                        panel_boxes = (side_panel_altitude_box(image.size),side_panel_altitude_card_box(image.size))
                        for index,panel_box in enumerate(panel_boxes):
                            if panel_box is None:
                                continue
                            attempt = {'box': panel_box, 'text': '', 'error': None}
                            panel_ocr['attempts'].append(attempt)
                            try:
                                panel = image.crop(panel_box)
                                scale = 2 if index == 0 else 3
                                panel = panel.resize((panel.width*scale,panel.height*scale),Image.Resampling.LANCZOS)
                                name = 'side-panel-altitude.png' if index == 0 else 'side-panel-altitude-card.png'
                                panel_path = str(Path(tmp) / name)
                                panel.save(panel_path)
                                attempt['text'] = engine.extract_region_text(panel_path)
                                candidate = parse_side_panel_altitude(attempt['text'])
                                if index == 0:
                                    panel_ocr['text'] = attempt['text']
                                panel_reading = candidate
                                if candidate.value is not None:
                                    panel_ocr.update(box=panel_box,text=attempt['text'],error=None,selected_attempt=index)
                                    break
                            except Exception as exc:
                                attempt['error'] = str(exc)
                                panel_ocr['error'] = str(exc)
                                panel_reading = InstrumentCandidate(None,None,'Left-panel OCR failed')
                        text = engine.extract_text(filename) if self.full_screen_ocr else panel_ocr['text']
                        label_boxes = tape_label_boxes(reading)
                        for name,box in tape_digit_boxes(reading).items():
                            labels = image.crop(label_boxes[name])
                            labels = labels.resize((labels.width*3,labels.height*3),Image.Resampling.LANCZOS)
                            label_path = str(Path(tmp) / f'{name}-label.png')
                            labels.save(label_path)
                            label_text = engine.extract_region_text(label_path)
                            label_attempts = [{'box': label_boxes[name], 'text': label_text}]
                            if not tape_label_recognized(name,label_text):
                                wide_box = reading.altitude_box if name == 'altitude' else reading.speed_box
                                wide = image.crop(wide_box)
                                wide = wide.resize((wide.width*2,wide.height*2),Image.Resampling.LANCZOS)
                                wide_path = str(Path(tmp) / f'{name}-label-wide.png')
                                wide.save(wide_path)
                                wide_text = engine.extract_region_text(wide_path)
                                label_attempts.append({'box': wide_box, 'text': wide_text})
                                label_text = f'{label_text} | {wide_text}'
                            digits = image.crop(box)
                            digits = digits.resize((digits.width*3,digits.height*3),Image.Resampling.LANCZOS)
                            digit_path = str(Path(tmp) / f'{name}-digits.png')
                            digits.save(digit_path)
                            digit_text = engine.extract_region_text(digit_path)
                            digit_attempts = [{'preprocessing': 'original', 'text': digit_text}]
                            # Retry missing/non-numeric crops for either instrument.
                            # Numeric conflicts remain rejected; do not select a
                            # convenient retry just because the panel disagrees.
                            if not digit_text.strip() or not re.fullmatch(r'[\d.,\s]+',digit_text):
                                contrast = ImageOps.grayscale(image.crop(box)).point(
                                    lambda value: 0 if value >= 200 else 255)
                                contrast = contrast.resize((contrast.width*3,contrast.height*3),
                                                           Image.Resampling.NEAREST)
                                contrast = ImageOps.expand(contrast,border=24,fill=255)
                                contrast_path = str(Path(tmp) / f'{name}-digits-contrast.png')
                                contrast.save(contrast_path)
                                digit_text = engine.extract_region_text(contrast_path)
                                digit_attempts.append({'preprocessing': 'high_contrast_padded',
                                                       'text': digit_text})
                            region_ocr[name] = {'label_text': label_text, 'digit_text': digit_text,
                                                'digit_attempts': digit_attempts,
                                                'label_box': label_boxes[name], 'digit_box': box,
                                                'label_attempts': label_attempts}
                            tape_readings[name] = parse_tape_readout(name,label_text,digit_text,full_text=text)
                            if not self.full_screen_ocr:
                                candidate = tape_readings[name]
                                tape_readings[name] = InstrumentCandidate(candidate.value,candidate.unit,
                                    candidate.reason.replace('full-screen instrument label','left-panel instrument label'))
                    has_text = panel_ocr['text'].strip() or text.strip() or any(region['digit_text'].strip() for region in region_ocr.values())
                    ocr_status = 'OCR completed' if has_text else 'No OCR text returned; engine or model may be unavailable'
                except Exception as exc:
                    prefix = 'OCR partially available' if panel_reading.value is not None or tape_readings else 'OCR unavailable'
                    ocr_status = f'{prefix}: {exc}'
            full_screen_readings = parse_instruments(text)
            instruments = reconcile_instruments(full_screen_readings,tape_readings)
            # Full-screen OCR can include the left panel; it is not a third,
            # independent altitude source. Compare the two spatial crops only.
            cockpit_altitude = tape_readings.get('altitude',InstrumentCandidate(None,None,'Cockpit altitude unavailable'))
            altitude_check = assess_altitude(cockpit_altitude,panel_reading)
            instruments['altitude'] = altitude_check.selected
            self.completed.emit({
                'image': image, 'reading': reading,
                'report': {'captured_utc': captured_utc,
                           'source': 'imported screenshot' if self.image is not None else 'Roblox client',
                           'size': list(image.size), 'desktop_bounds': bounds,
                           'geometry': asdict(reading), 'ocr_status': ocr_status, 'raw_ocr': text,
                           'region_ocr': region_ocr,
                           'side_panel_ocr': panel_ocr,
                           'altitude_check': asdict(altitude_check),
                           'full_screen_instruments': {k: asdict(v) for k,v in full_screen_readings.items()},
                           'tape_instruments': {k: asdict(v) for k,v in tape_readings.items()},
                           'instruments': {k: asdict(v) for k,v in instruments.items()},
                           'pitch_degrees': None, 'roll_degrees': None,
                           'controls_enabled': False}})
        except Exception as exc:
            self.failed.emit(str(exc))


def annotated_image(image, reading):
    result = image.copy()
    draw = ImageDraw.Draw(result)
    width,height = result.size
    for name,box in [('Altitude readout candidate',reading.altitude_box),
                     ('Airspeed readout candidate',reading.speed_box)]:
        if box:
            draw.rectangle(box, outline='orange', width=max(1,width//600))
            draw.text((box[0],max(0,box[1]-14)),name,fill='orange')
    if reading.horizon_y is not None:
        slope = reading.horizon_slope or 0.
        draw.line([(0,reading.horizon_y-slope*width/2),
                   (width-1,reading.horizon_y+slope*(width-1-width/2))],
                  fill='cyan',width=max(1,width//500))
    return result


class AircraftHudDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        # Native window events may arrive during resize/show on Windows.
        # Initialize every event-handler field before touching window geometry.
        self._preview_image = None
        self.worker = None
        self._hidden_windows = []
        self._busy = False
        self._payload = None
        self.recorder = None
        self._record_windows = []
        self.setWindowTitle('Aircraft HUD Test — read-only')
        self.resize(960,760)
        layout = QVBoxLayout(self)
        instructions = QLabel('Enter cockpit view first. Capture hides AeroHelper for 3 seconds; switch to Roblox if needed. '
                              'Only the foreground Roblox client is captured, including on another monitor. '
                              'No flight inputs are sent. Stop existing automation before testing.')
        instructions.setWordWrap(True)
        layout.addWidget(instructions)
        buttons = QHBoxLayout()
        self.capture_button = QPushButton('Capture Roblox HUD (3s)')
        self.open_button = QPushButton('Open screenshot…')
        self.screenshot_button = QPushButton('Save screenshot…')
        self.screenshot_button.setToolTip('Save a PNG of this window, including the current preview, readings and visible diagnostic text.')
        self.save_button = QPushButton('Save diagnostic ZIP…')
        self.save_button.setEnabled(False)
        for button in (self.capture_button,self.open_button,self.screenshot_button,self.save_button): buttons.addWidget(button)
        layout.addLayout(buttons)
        self.record_button = QPushButton('Start read-only recording…')
        self.record_button.setToolTip('Record instrument crops and OCR for up to 10 minutes / 200 MB. Restore this window to stop and save.')
        layout.addWidget(self.record_button)
        self.record_button.clicked.connect(self.begin_recording)
        self.ocr_box = QCheckBox('Read OCR too (experimental; first use may download models)')
        layout.addWidget(self.ocr_box)
        self.status = QLabel('Waiting for capture. Pitch / roll: uncalibrated. Altitude / airspeed: unavailable.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.preview = QLabel('Captured image and candidate overlays will appear here.')
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumSize(400,240)
        self.preview.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Ignored)
        self.preview.installEventFilter(self)
        layout.addWidget(self.preview,1)
        self.details = QTextEdit()
        self.details.setReadOnly(True)
        self.details.setPlainText(f'Build: {build_revision()}\nWaiting for capture.')
        # Native Windows text colours can remain black when the parent gives
        # this editor a dark background. Specify both sides of the contrast.
        self.details.setStyleSheet("""
            QTextEdit {
                color: #F8FBFF;
                background-color: #0B1020;
                selection-color: #FFFFFF;
                selection-background-color: #315B86;
                border: 1px solid #53627A;
                border-radius: 6px;
                padding: 8px;
            }
        """)
        self.details.setMaximumHeight(210)
        layout.addWidget(self.details)
        self.capture_button.clicked.connect(self.begin_capture)
        self.open_button.clicked.connect(self.open_image)
        self.screenshot_button.clicked.connect(self.save_screenshot)
        self.save_button.clicked.connect(self.save_report)
        self._capture_timer = QTimer(self)
        self._capture_timer.setSingleShot(True)
        self._capture_timer.timeout.connect(self._start_live_worker)

    def set_busy(self, busy):
        self._busy = busy
        self.record_button.setEnabled(not busy or self.recorder is not None)
        self.capture_button.setEnabled(not busy)
        self.open_button.setEnabled(not busy)
        self.ocr_box.setEnabled(not busy)
        self.screenshot_button.setEnabled(not busy)
        self.save_button.setEnabled(not busy and self._payload is not None)

    def begin_recording(self):
        if self.recorder is not None:
            self.record_button.setEnabled(False)
            self.record_button.setText('Stopping after current OCR…')
            self.recorder.request_stop()
            return
        if self._busy:
            return
        folder = QFileDialog.getExistingDirectory(self,'Choose where to save the recording')
        if not folder:
            return
        from AeroHelper.ui.aircraft_recording import RecordingWorker
        name = datetime.now().strftime('aircraft-session-%Y%m%d-%H%M%S-%f')
        self._payload = None
        self._preview_image = None
        self.preview.setText('Recording instrument crops in the background. Restore this window to stop and save.')
        self.recorder = RecordingWorker(Path(folder)/name,self)
        self.recorder.progress.connect(self._record_progress)
        self.recorder.saved.connect(self._record_saved)
        self.recorder.failed.connect(self._record_failed)
        self.recorder.finished.connect(self._record_finished)
        self.set_busy(True)
        self.record_button.setText('Stop recording and save ZIP')
        self.status.setText('Recording starts in 3 seconds. Fly normally; restore this window to stop. No flight inputs sent.')
        self.details.setPlainText(f'Build: {build_revision()}\nRecording folder: {self.recorder.folder}\n'
                                  'Instrument crops only. ADI location/tints are experimental, not attitude readings.\n'
                                  'OCR speed sets the actual sample interval; readings may be delayed.\n'
                                  'Automatically stops after 10 minutes or about 200 MB.')
        self._record_windows = [w for w in QApplication.topLevelWidgets() if w.isVisible()]
        for widget in self._record_windows:
            widget.showMinimized()
        try:
            bring_roblox_to_front()
        except Exception:
            pass
        QTimer.singleShot(3000,self._launch_recording)

    def _launch_recording(self):
        if self.recorder is not None:
            self.recorder.start()

    def _record_progress(self, event):
        summary,latest = event['summary'],event['latest']
        text = f"Recording: {summary['frames']} frames; skipped captures: {summary['capture_failures']}. "
        if latest['status'] == 'sample':
            report = latest['report']
            text += ' | '.join(f"{name}: {value['value']} {value['unit']}" if value['value'] is not None
                               else f"{name}: unavailable" for name,value in report['instruments'].items())
            text += f". Processing delay: {report['reading_age_seconds']:.1f}s ({report['freshness']}). Altitude: {report['altitude_check']['status']}."
        else:
            text += latest.get('reason','Analysis unavailable')
        if latest['status'] == 'sample':
            flags = latest['report'].get('continuity',{})
            text += ' Checks: '+', '.join(f"{name}: {flag['status']}" for name,flag in flags.items())+'.'
        self.status.setText(text+' Restore this window and press Stop to save. No controls enabled.')

    def _record_saved(self, result):
        summary = result['summary']
        if result.get('logs_path'):
            self.details.append('\nSmall log ZIP: '+result['logs_path'])
            self.details.append('Image ZIPs (upload separately):\n'+'\n'.join(result.get('image_parts',[])))
        self.status.setText(f"Recording saved: {summary['frames']} frames; "
                            f"{summary['capture_failures']} skipped captures. {summary['stop_reason']}.")
        self.details.append(f"\nSaved ZIP: {result['path']}\n"
                            f"Altitude agreements: {summary['altitude_agreements']}; "
                            f"disagreements: {summary['altitude_disagreements']}; "
                            f"altitude unavailable: {summary['altitude_unavailable']}; "
                            f"airspeed unavailable: {summary['airspeed_unavailable']}.\n"
                            'ADI tints and crops need review; no pitch or roll calibration.')

    def _record_failed(self, message):
        self.status.setText('Recording failed; see details.')
        self.details.append('\n'+message)

    def _record_finished(self):
        self.recorder.deleteLater()
        self.recorder = None
        self.record_button.setText('Start read-only recording…')
        self.set_busy(False)
        for widget in self._record_windows:
            widget.showNormal()
        self._record_windows = []
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def begin_capture(self):
        if self._busy:
            return
        self.set_busy(True)
        self.status.setText('Capturing Roblox after 3 seconds. Switch to cockpit view now…')
        self._hidden_windows = [w for w in QApplication.topLevelWidgets() if w.isVisible()]
        for widget in self._hidden_windows:
            widget.hide()
        # Focus is best-effort; capture independently verifies the foreground.
        try:
            bring_roblox_to_front()
        except Exception:
            pass
        self._capture_timer.start(3000)

    def _restore_windows(self, *unused):
        for widget in self._hidden_windows:
            widget.show()
        self._hidden_windows = []
        self.show()
        self.raise_()
        self.activateWindow()

    def _start_live_worker(self):
        self._start_worker()

    def _start_worker(self, image=None):
        self.set_busy(True)
        self.status.setText('Processing captured frame…' if image is not None else 'Capturing and processing Roblox…')
        self.worker = HudWorker(image, self.ocr_box.isChecked(), self)
        self.worker.captured.connect(self._restore_windows)
        self.worker.completed.connect(self.show_result)
        self.worker.failed.connect(self.show_failure)
        self.worker.finished.connect(self._worker_finished)
        self.worker.start()

    def _worker_finished(self):
        self.set_busy(False)
        self.worker.deleteLater()
        self.worker = None

    def open_image(self):
        filename,_ = QFileDialog.getOpenFileName(self,'Open original-resolution cockpit screenshot','','Images (*.png *.jpg *.jpeg *.bmp)')
        if not filename:
            return
        try:
            with Image.open(filename) as source:
                image = source.convert('RGB')
            self._start_worker(image)
        except Exception as exc:
            self.show_failure(str(exc))

    def show_failure(self, message):
        self._restore_windows()
        self._payload = None
        self._preview_image = None
        self.preview.clear()
        self.details.setPlainText(f'Build: {build_revision()}\nCapture / analysis error: {message}')
        self.save_button.setEnabled(False)
        self.status.setText(f'Capture / analysis failed: {message}')

    def show_result(self, payload):
        try:
            self._display_result(payload)
        except Exception as exc:
            self.show_failure(f'Could not display HUD diagnostics: {exc}')

    def _display_result(self, payload):
        self._restore_windows()
        self._payload = payload
        reading,report = payload['reading'],payload['report']
        self._preview_image = annotated_image(payload['image'],reading)
        self._render_preview()
        values = []
        for name,candidate in report['instruments'].items():
            value = candidate['value']
            values.append(f"{name.title()}: {value:g} {candidate['unit']} (unverified)" if value is not None
                          else f"{name.title()}: unavailable — {candidate['reason']}")
        geometry = (f'Horizon candidate at Y={reading.horizon_y:.1f}px; slope={reading.horizon_slope:.3f}. '
                    if reading.horizon_y is not None else 'Horizon unavailable. ')
        altitude = report.get('altitude_check')
        altitude_line = ''
        if altitude:
            def source_value(candidate):
                return f"{candidate['value']:g} {candidate['unit']}" if candidate['value'] is not None else 'unavailable'
            delta = f"{altitude['difference_ft']:g} ft" if altitude['difference_ft'] is not None else 'not compared'
            state = {'agree':'agree', 'disagree':'DISAGREEMENT — altitude rejected',
                     'cockpit_only':'cockpit only (not cross-checked)',
                     'side_panel_fallback':'left-panel fallback (not cross-checked)',
                     'unavailable':'unavailable'}[altitude['status']]
            altitude_line = (f"\nAltitude sources: cockpit {source_value(altitude['cockpit'])}; "
                             f"left panel {source_value(altitude['side_panel'])}; difference {delta}; "
                             f"tolerance {altitude['tolerance_ft']:g} ft; {state}.")
        self.status.setText(geometry + f'Pixel support: {reading.horizon_confidence:.0%} (not accuracy). '
                            + reading.reason + '\n' + ' | '.join(values) + altitude_line + '\nPitch / roll: uncalibrated; no controls enabled.')
        lines = [f'Build: {build_revision()}', f"Source: {report['source']} | Resolution: {report['size']} | {report['captured_utc']}",
                 'Cyan: candidate line. Orange: tape-derived readout regions. Tape-profile units assumed: feet / knots.',
                 report['ocr_status']]
        for name,candidate in report.get('tape_instruments',{}).items():
            if candidate['value'] is not None:
                lines.append(f"{name.title()} cropped candidate: {candidate['value']:g} {candidate['unit']} — {candidate['reason']}")
        for name,region in report.get('region_ocr',{}).items():
            lines.append(f"{name.title()} crop — label OCR: {region['label_text']} | digit OCR: {region['digit_text']}")
            for attempt in region.get('digit_attempts',[]):
                lines.append(f"  Digits ({attempt['preprocessing']}): {attempt['text'] or '[no text]'}")
        if report.get('side_panel_ocr'):
            panel = report['side_panel_ocr']
            lines.append(f"Left-panel OCR: {panel['text'] or '(none)'}")
            if panel.get('error'): lines.append(f"Left-panel error: {panel['error']}")
            if len(panel.get('attempts',[])) > 1:
                lines.append('Left-panel altitude card retry attempted; all crop bounds and OCR results are recorded in the ZIP.')
        lines.extend(['Raw full-screen OCR (inspect against screenshot):',report['raw_ocr'] or '(none)'])
        self.details.setPlainText('\n'.join(lines))

    def _render_preview(self):
        if getattr(self, '_preview_image', None) is None or not hasattr(self, 'preview'):
            return
        image = self._preview_image
        data = image.tobytes('raw','RGB')
        qimage = QImage(data,image.width,image.height,image.width*3,QImage.Format_RGB888).copy()
        self.preview.setPixmap(QPixmap.fromImage(qimage).scaled(self.preview.contentsRect().size(),Qt.KeepAspectRatio,Qt.SmoothTransformation))

    def eventFilter(self, watched, event):
        if watched is getattr(self,'preview',None) and event.type() == QEvent.Resize:
            self._render_preview()
        return super().eventFilter(watched,event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._render_preview()

    def _window_screenshot_png(self):
        # Render this widget, not the desktop: no file chooser, overlapping
        # window or unrelated monitor can obscure the captured diagnostics.
        pixmap = self.grab()
        if pixmap.isNull():
            raise IOError('The HUD Test window could not be rendered')
        data = QByteArray()
        buffer = QBuffer(data)
        if not buffer.open(QIODevice.WriteOnly):
            raise IOError('Could not create screenshot buffer')
        try:
            if not pixmap.save(buffer,'PNG'):
                raise IOError('Could not encode the HUD Test screenshot')
        finally:
            buffer.close()
        return bytes(data)

    def save_screenshot(self):
        if self._busy:
            return
        filename,_ = QFileDialog.getSaveFileName(self,'Save HUD Test window screenshot',
                                                'aircraft-hud-test.png','PNG (*.png)')
        if not filename:
            return
        if not filename.lower().endswith('.png'):
            filename += '.png'
        try:
            Path(filename).write_bytes(self._window_screenshot_png())
            self.details.append('\nHUD Test window screenshot saved.')
        except Exception as exc:
            self.details.append(f'\nCould not save window screenshot: {exc}')

    def save_report(self):
        if self._payload is None:
            return
        filename,_ = QFileDialog.getSaveFileName(self,'Save diagnostics (includes visible Roblox image and OCR)',
                                                'aircraft-hud-diagnostic.zip','ZIP (*.zip)')
        if not filename:
            return
        try:
            with zipfile.ZipFile(filename,'w',compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr('report.json',json.dumps(self._payload['report'],indent=2))
                archive.writestr('hud-test-window.png',self._window_screenshot_png())
                archive.writestr('diagnostics.txt',self.details.toPlainText())
                for name,image in [('cockpit.png',self._payload['image']),('annotated.png',self._preview_image)]:
                    buffer = io.BytesIO()
                    image.save(buffer,format='PNG')
                    archive.writestr(name,buffer.getvalue())
                panel = self._payload['report'].get('side_panel_ocr')
                if panel and panel['box'] and panel['text']:
                    buffer = io.BytesIO()
                    self._payload['image'].crop(panel['box']).save(buffer,format='PNG')
                    archive.writestr('side-panel-altitude.png',buffer.getvalue())
                for name,region in self._payload['report'].get('region_ocr',{}).items():
                    if name in ('altitude','airspeed'):
                        buffer = io.BytesIO()
                        self._payload['image'].crop(region['digit_box']).save(buffer,format='PNG')
                        archive.writestr(f'{name}-readout.png',buffer.getvalue())
            self.details.append('\nDiagnostic ZIP saved. Review the images before sharing.')
        except Exception as exc:
            self.details.append(f'\nCould not save diagnostics: {exc}')

    def reject(self):
        # A running QThread must finish before the dialog can be destroyed.
        if self._busy:
            self.status.setText('Still working. Stop the recording and wait for saving, or wait for capture / OCR to finish.')
            return
        super().reject()

    def closeEvent(self, event):
        if self._busy:
            event.ignore()
        else:
            super().closeEvent(event)
