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


def analyze_cockpit(image):
    """Find a bilateral near-white line, including tilted candidates.

    Confidence means pixel support, not probability of a correct horizon.
    Repeated ladder lines are rejected as ambiguous. Side crop boxes are only
    suggested inspection regions, never a claim that the instruments are there.
    """
    rgb = np.asarray(image.convert('RGB') if hasattr(image, 'convert') else image)
    if rgb.ndim != 3 or rgb.shape[2] != 3 or not np.issubdtype(rgb.dtype, np.number):
        raise ValueError('Expected a numeric RGB image')
    h, w = rgb.shape[:2]
    if h < 120 or w < 200:
        return CockpitReading(None, None, 0., None, None, 'Image too small; use an original-resolution cockpit capture.')
    altitude = (int(w*.67), int(h*.38), int(w*.78), int(h*.62))
    speed = (int(w*.10), int(h*.38), int(w*.23), int(h*.62))
    # Bound processing cost while preserving source-image coordinates.
    from PIL import Image
    scale = min(1., 1000 / w)
    if scale < 1:
        rgb = np.asarray(Image.fromarray(rgb.astype(np.uint8)).resize((int(w*scale), int(h*scale))))
    sh, sw = rgb.shape[:2]
    channels = rgb.astype(np.float32)
    white = (channels.min(axis=2) >= 185) & (np.ptp(channels, axis=2) < 48)
    ys = np.arange(int(sh*.30), int(sh*.76))
    spans = [np.arange(int(sw*a), int(sw*b)) for a,b in ((.09,.23),(.74,.88))]
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
                              'No supported bilateral horizon. Check cockpit view, HUD colour and scale.')
    candidates.sort(reverse=True)
    score,y,slope = candidates[0]
    ambiguous = any(other >= score-.08 and abs(oy-y) > sh*.035
                    for other,oy,_ in candidates[1:])
    if ambiguous:
        return CockpitReading(None, None, score, altitude, speed,
                              'Multiple supported lines; horizon is ambiguous (possible pitch ladder).')
    return CockpitReading(y/scale, slope, score, altitude, speed,
                          'Unverified line candidate. Pitch and roll require cockpit calibration.')


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
