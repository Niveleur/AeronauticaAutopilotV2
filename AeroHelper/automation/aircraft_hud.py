"""Experimental, read-only HUD diagnostics. No readings authorize flight inputs.

Geometry is relative to the captured Roblox client, not the desktop. Real
cockpit fixtures and aircraft-specific calibration are required before control.
"""
from dataclasses import dataclass
import re
import numpy as np


@dataclass(frozen=True)
class CockpitReading:
    horizon_y: float | None
    horizon_slope: float | None
    horizon_confidence: float
    altitude_box: tuple | None
    speed_box: tuple | None
    reason: str = ''
    tape_rails: tuple | None = None


def _tape_layout(white):
    """Locate paired long vertical HUD tape rails, not screen-sized guesses."""
    h, w = white.shape
    start, end = int(h*.05), int(h*.93)
    columns = white[start:end].sum(axis=0)
    xs = np.flatnonzero(columns > h*.24)
    groups = np.split(xs, np.flatnonzero(np.diff(xs) > 1)+1)
    rails = []
    for group in groups:
        if not len(group):
            continue
        x = int(np.median(group))
        if not w*.18 < x < w*.82:
            continue
        rows = np.flatnonzero(white[start:end, max(0,x-1):x+2].any(axis=1)) + start
        segments = np.split(rows, np.flatnonzero(np.diff(rows) > max(3,h*.008))+1)
        segment = max(segments, key=len)
        top,bottom = int(segment[0]),int(segment[-1])
        if bottom-top > h*.25 and len(segment)/(bottom-top+1) > .85:
            rails.append((x,top,bottom))
    pairs = []
    for left,top,bottom in rails:
        for right,rt,rb in rails:
            span = bottom-top
            if (left < w/2 < right and abs((left+right)/2-w/2) < w*.04
                    and .8 < (right-left)/span < 2.
                    and abs(top-rt) < h*.025 and abs(bottom-rb) < h*.025):
                pairs.append((span,left,right,top,bottom))
    if not pairs:
        return None
    span,left,right,top,bottom = max(pairs)
    mid = (top+bottom)/2
    def box(a,b):
        return (max(0,int(a)),max(0,int(mid-.14*span)),
                min(w,int(b)),min(h,int(mid+.065*span)))
    return (left,right,top,bottom), box(right+.13*span,right+.30*span), box(left-.30*span,left-.13*span)


def analyze_cockpit(image):
    """Find a bilateral near-white line, including tilted candidates.

    Confidence means pixel support, not probability of a correct horizon.
    Repeated ladder lines are rejected as ambiguous. Instrument regions are
    derived from paired tape rails; unsupported layouts have no crop boxes.
    """
    rgb = np.asarray(image.convert('RGB') if hasattr(image, 'convert') else image)
    if rgb.ndim != 3 or rgb.shape[2] != 3 or not np.issubdtype(rgb.dtype, np.number):
        raise ValueError('Expected a numeric RGB image')
    h, w = rgb.shape[:2]
    if h < 120 or w < 200:
        return CockpitReading(None, None, 0., None, None, 'Image too small; use an original-resolution cockpit capture.')
    channels = rgb.astype(np.float32)
    native_white = (channels.min(axis=2) >= 185) & (np.ptp(channels, axis=2) < 48)
    layout = _tape_layout(native_white)
    rails,altitude,speed = layout if layout else (None,None,None)
    # Bound line-search cost; pool the native mask to retain thin HUD lines.
    scale = min(1., 1000 / w)
    if scale < 1:
        import cv2
        white = cv2.resize(native_white.astype(np.float32),
                           (int(w*scale),int(h*scale)),interpolation=cv2.INTER_AREA) >= .20
    else:
        white = native_white
    sh, sw = white.shape
    ys = np.arange(int(sh*.30), int(sh*.76))
    if rails:
        left,right,top,bottom = (value*scale for value in rails)
        gap = right-left
        spans = [np.arange(int(left+.12*gap),int(left+.35*gap)),
                 np.arange(int(right-.35*gap),int(right-.12*gap))]
        ys = np.arange(max(0,int(top)),min(sh,int(bottom)+1))
    else:
        spans = [np.arange(int(sw*a),int(sw*b)) for a,b in ((.09,.23),(.74,.88))]
    candidates = []
    # Scan slope directly: enough sampling to include tilted horizons without
    # treating the horizontal aircraft reference as calibrated pitch/roll.
    for slope in np.linspace(-.6, .6, 121):
        supports = []
        for xs in spans:
            rows = np.rint(ys[:,None] + slope*(xs[None,:] - sw/2)).astype(int)
            mask = np.zeros(rows.shape, dtype=bool)
            for offset in (-1,0,1):
                rr = rows + offset
                valid = (rr >= 0) & (rr < sh)
                mask |= valid & white[np.clip(rr,0,sh-1), xs[None,:]]
            supports.append(mask.mean(axis=1))
        scores = np.minimum(*supports)
        for idx in np.flatnonzero(scores >= .65):
            candidates.append((float(scores[idx]), float(ys[idx]), float(slope)))
    if not candidates:
        return CockpitReading(None, None, 0., altitude, speed,
                              'No supported bilateral horizon. Check cockpit view, HUD colour and scale.', rails)
    candidates.sort(reverse=True)
    score,y,slope = candidates[0]
    ambiguous = any(other >= score-.08 and abs(oy-y) > sh*.035
                    for other,oy,_ in candidates[1:])
    if ambiguous:
        return CockpitReading(None, None, score, altitude, speed,
                              'Multiple supported lines; horizon is ambiguous (possible pitch ladder).', rails)
    return CockpitReading(y/scale, slope, score, altitude, speed,
                          'Unverified line candidate. Pitch and roll require cockpit calibration.', rails)


@dataclass(frozen=True)
class InstrumentCandidate:
    value: float | None
    unit: str | None
    reason: str


def parse_instruments(text):
    """Accept only explicit labels AND units; never guess from tape digits.

    Multiple conflicting values or implausible values remain unavailable.
    These are single-frame OCR candidates, without temporal validation.
    """
    result = {}
    specs = {
        'altitude': (r'(?:ALT(?:ITUDE)?)', r'(?:FT|FEET|M)', -2000, 100000),
        'airspeed': (r'(?:IAS|AIRSPEED|SPEED)', r'(?:KTS?|KNOTS?|KM/H|MPH)', 0, 2000),
    }
    for name,(label,unit,lo,hi) in specs.items():
        pattern = rf'\b{label}\s*[:=]?\s*(-?\d+(?:,\d{{3}})*(?:\.\d+)?)\s*({unit})\b'
        matches = {(float(m.group(1).replace(',','')), m.group(2).upper())
                   for m in re.finditer(pattern, text, re.IGNORECASE)}
        unit_first = rf'\b{label}\s*[:=]?\s*({unit})\s+(-?\d+(?:,\d{{3}})*(?:\.\d+)?)\b'
        matches.update((float(m.group(2).replace(',','')),m.group(1).upper())
                       for m in re.finditer(unit_first,text,re.IGNORECASE))
        aliases = {'KT':'KTS','KNOT':'KTS','KNOTS':'KTS','FEET':'FT'}
        matches = {(value,aliases.get(unit,unit)) for value,unit in matches}
        if len(matches) != 1:
            reason = 'Conflicting labelled readings' if matches else 'No explicit label, value and unit'
            result[name] = InstrumentCandidate(None,None,reason)
            continue
        value,units = next(iter(matches))
        if not lo <= value <= hi:
            result[name] = InstrumentCandidate(None,None,'Outside diagnostic range')
        else:
            result[name] = InstrumentCandidate(value,units,'Unverified single-frame OCR candidate')
    return result


def tape_digit_boxes(reading):
    """Interior digit crops exclude tape ticks, labels and the readout border."""
    if not reading.tape_rails:
        return {}
    _,_,top,bottom = reading.tape_rails
    span = bottom-top
    middle = (top+bottom)/2
    inset_left = max(2,int(span*.02))
    inset_right = max(2,int(span*.012))
    return {name: (box[0]+inset_left,int(middle-.035*span),
                   box[2]-inset_right,int(middle+.04*span))
            for name,box in [('altitude',reading.altitude_box),('airspeed',reading.speed_box)]}


def tape_label_boxes(reading):
    """Keep the label separate from scrolling tape numbers and readout digits."""
    if not reading.tape_rails:
        return {}
    _,_,top,bottom = reading.tape_rails
    span = bottom-top
    middle = (top+bottom)/2
    boxes = {name: (box[0],round(middle-.127*span),box[2],round(middle-.058*span))
             for name,box in tape_digit_boxes(reading).items()}
    # SPEED is right-aligned above its readout and wider than its three digits.
    speed = boxes['airspeed']
    boxes['airspeed'] = (reading.speed_box[0],speed[1],reading.speed_box[2],speed[3])
    return boxes


def tape_label_recognized(name, text):
    labels = {'altitude': r'\bALT(?:ITUDE)?\b', 'airspeed': r'\b(?:SPEED|IAS|AIRSPEED)\b'}
    if name not in labels:
        raise ValueError('Unknown tape instrument')
    return 'VERTICAL' not in text.upper() and bool(re.search(labels[name],text,re.IGNORECASE))


def parse_tape_readout(name, label_text, digit_text, full_text=''):
    """Require a recognised instrument label and an isolated numeric readout.

    Units come from the experimental Aeronautica tape profile, not from OCR.
    Missing labels, mixed text and disagreements between OCR engines fail closed.
    """
    units = {'altitude': 'FT', 'airspeed': 'KTS'}
    local_label = tape_label_recognized(name,label_text)
    if not digit_text.strip() or not re.fullmatch(r'[\d.,\s]+',digit_text):
        return InstrumentCandidate(None,None,'Readout is not isolated numeric text')
    try:
        values = {float(token.replace(',','')) for token in digit_text.split()}
    except ValueError:
        return InstrumentCandidate(None,None,'Invalid numeric readout')
    if len(values) != 1:
        return InstrumentCandidate(None,None,'Conflicting cropped readouts')
    value = values.pop()
    if not 0 <= value <= (100000 if name == 'altitude' else 2000):
        return InstrumentCandidate(None,None,'Outside diagnostic range')
    if not local_label:
        # A scrolling tick can overwrite ALT. Require an independent expanded
        # label with the exact same value; never guess the label from digits.
        expanded = r'ALTITUDE' if name == 'altitude' else r'(?:AIRSPEED|IAS)'
        pattern = rf'\b{expanded}\s*[:=]?\s*(?:(?:FT|FEET|KTS?|KNOTS?)\s+)?(\d+(?:,\d{{3}})*(?:\.\d+)?)\b'
        corroborating = {float(m.group(1).replace(',',''))
                         for m in re.finditer(pattern,full_text,re.IGNORECASE)}
        if corroborating != {value}:
            return InstrumentCandidate(None,None,'Tape label not recognised or independently confirmed')
        reason = 'Tape digits confirmed by full-screen instrument label; units assumed from Aeronautica HUD profile'
    else:
        reason = 'Single-frame tape OCR; units assumed from Aeronautica HUD profile'
    return InstrumentCandidate(value,units[name],reason)


def reconcile_instruments(full_screen, tape_readings):
    result = dict(full_screen)
    for name,candidate in tape_readings.items():
        existing = result[name]
        if candidate.value is None:
            continue
        if existing.value is not None and (existing.value,existing.unit) != (candidate.value,candidate.unit):
            result[name] = InstrumentCandidate(
                None,None,f'Full-screen and tape OCR disagree (full: {existing.value:g} {existing.unit}; '
                f'crop: {candidate.value:g} {candidate.unit})')
        else:
            result[name] = candidate
    return result


ALTITUDE_TOLERANCE_FT = 5.0


def side_panel_altitude_box(size):
    """Separate left-panel OCR region, available even without cockpit tapes.

    This deliberately excludes the central HUD. Readings still require the
    explicit ALTITUDE label and feet unit, so other panel/dial numbers are ignored.
    """
    width,height = size
    if width < 200 or height < 120:
        return None
    return (0,int(height*.25),int(min(width*.16,height*.28)),int(height*.95))


def side_panel_altitude_card_box(size):
    """Experimental standard-panel retry; explicit label/unit checks still apply."""
    width,height = size
    if width < 200 or height < 120:
        return None
    return (int(min(height*.02,width*.02)),int(height*.565),
            int(min(height*.17,width*.14)),int(height*.615))


def parse_side_panel_altitude(text):
    number = r'(-?\d+(?:,\d{3})*(?:\.\d+)?)'
    patterns = (rf'\bALTITUDE\s*[:=]?\s*{number}\s*(?:FT|FEET)\b(?!\s*/)',
                rf'\bALTITUDE\s*[:=]?\s*(?:FT|FEET)\s*{number}\b')
    values = {float(match.group(1).replace(',',''))
              for pattern in patterns for match in re.finditer(pattern,text,re.IGNORECASE)}
    if len(values) != 1:
        return InstrumentCandidate(None,None,'Left-panel ALTITUDE label, feet unit and unique value required')
    value = values.pop()
    if not -2000 <= value <= 100000:
        return InstrumentCandidate(None,None,'Left-panel altitude outside diagnostic range')
    return InstrumentCandidate(value,'FT','Separate left-panel OCR; single frame')


@dataclass(frozen=True)
class AltitudeAssessment:
    cockpit: InstrumentCandidate
    side_panel: InstrumentCandidate
    selected: InstrumentCandidate
    status: str
    difference_ft: float | None
    tolerance_ft: float = ALTITUDE_TOLERANCE_FT


def assess_altitude(cockpit, side_panel, tolerance_ft=ALTITUDE_TOLERANCE_FT):
    """Cross-check same-frame sources; a lone source is explicitly unconfirmed."""
    from math import isfinite
    if not isfinite(tolerance_ft) or tolerance_ft < 0:
        raise ValueError('Altitude tolerance must be finite and nonnegative')
    def usable(reading):
        return (reading.value is not None and reading.unit == 'FT'
                and isfinite(reading.value) and -2000 <= reading.value <= 100000)
    cockpit_ok,panel_ok = usable(cockpit),usable(side_panel)
    difference = None
    if cockpit_ok and panel_ok:
        difference = abs(cockpit.value-side_panel.value)
        if difference <= tolerance_ft:
            status = 'agree'
            selected = InstrumentCandidate(cockpit.value,'FT',
                f'Cockpit and left panel agree within {tolerance_ft:g} ft (difference {difference:g} ft); single frame')
        else:
            status = 'disagree'
            selected = InstrumentCandidate(None,None,
                f'Altitude disagreement: cockpit {cockpit.value:g} ft, left panel {side_panel.value:g} ft '
                f'(difference {difference:g} ft exceeds {tolerance_ft:g} ft)')
    elif cockpit_ok:
        status = 'cockpit_only'
        selected = InstrumentCandidate(cockpit.value,'FT','Cockpit only; left panel unavailable, not cross-checked')
    elif panel_ok:
        status = 'side_panel_fallback'
        selected = InstrumentCandidate(side_panel.value,'FT','Left-panel fallback; cockpit unavailable, not cross-checked')
    else:
        status = 'unavailable'
        selected = InstrumentCandidate(None,None,'No usable cockpit or left-panel altitude in feet')
    return AltitudeAssessment(cockpit,side_panel,selected,status,difference,tolerance_ft)
