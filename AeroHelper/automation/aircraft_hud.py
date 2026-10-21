"""Read-only cockpit HUD geometry detector.

Works on screenshot arrays (RGB), without sending any flight controls.
A candidate must be calibrated against a known straight-and-level screenshot
before its pixel offsets are interpreted as pitch or roll angles.
"""
from dataclasses import dataclass
import numpy as np

@dataclass(frozen=True)
class CockpitReading:
    horizon_y: float | None
    horizon_slope: float | None
    horizon_confidence: float
    altitude_box: tuple | None
    speed_box: tuple | None

def analyze_cockpit(image):
    """Return candidate horizon geometry and OCR crop boxes.

    image: PIL.Image or ndarray in RGB order, at any screen resolution.
    The long horizontal HUD line is detected by near-white pixels in the
    central screen band. Geometry is intentionally *not* converted to
    pitch/roll until reference markings are validated in game.
    """
    rgb = np.asarray(image.convert("RGB") if hasattr(image, "convert") else image)
    if rgb.ndim != 3 or rgb.shape[2] < 3:
        raise ValueError("Expected RGB image")
    h, w = rgb.shape[:2]
    if h < 120 or w < 200:
        return CockpitReading(None, None, 0.0, None, None)
    # Exclude the speed and altitude tapes, ladder, and center reticle.
    # Search long, near-white horizontal segments around mid-screen.
    r, g, b = (rgb[:, :, i].astype(np.int16) for i in range(3))
    white = (r >= 185) & (g >= 185) & (b >= 185) & (np.maximum.reduce([r,g,b]) - np.minimum.reduce([r,g,b]) < 48)
    y0, y1 = int(h * .40), int(h * .72)
    left = white[y0:y1, int(w*.09):int(w*.23)]
    right = white[y0:y1, int(w*.74):int(w*.88)]
    if left.shape[1] == 0 or right.shape[1] == 0:
        return CockpitReading(None, None, 0.0, None, None)
    # Both side spans must support the same candidate line. Require broad
    # pixel coverage so ordinary HUD text cannot trigger a horizon match.
    l = left.mean(axis=1)
    rr = right.mean(axis=1)
    score = np.minimum(l, rr)
    index = int(np.argmax(score))
    confidence = float(score[index])
    horizon = float(y0 + index) if confidence >= .50 else None
    return CockpitReading(
        horizon_y=horizon, horizon_slope=None,
        horizon_confidence=confidence,
        altitude_box=(int(w*.67), int(h*.42), int(w*.74), int(h*.53)),
        speed_box=(int(w*.12), int(h*.42), int(w*.19), int(h*.53)),
    )
