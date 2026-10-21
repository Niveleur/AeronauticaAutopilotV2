# Aircraft HUD diagnostics

This is a read-only experiment. Existing boat/airship automation is unchanged.
No aircraft flight inputs or calibrated pitch/roll readings have been added.
The upstream consent prompt and Routes manager are removed from this fork's UI;
startup no longer fetches the upstream route list.
Upstream AeroHelper's MIT license and attribution remain in place.

## Windows GUI workflow

1. Open the packaged application and stop any running automation.
2. Enter a conventional aircraft's cockpit view in Roblox. Keep the HUD visible.
3. Open **Aircraft HUD Test**, then **Capture Roblox HUD (3s)**.
   AeroHelper's visible windows disappear during the three-second delay. It tries
   to bring Roblox forward; if Windows prevents that, switch to Roblox yourself.
   Capture requires Roblox to remain in front. The client area is used rather
   than the whole desktop, including when Roblox is on a second monitor.
4. Inspect the image after AeroHelper returns. Cyan is a *candidate* line;
   orange boxes follow detected paired tape rails and surround the labelled
   digital readouts. Unsupported layouts produce no guessed boxes. A high
   pixel-support score is not recognition accuracy.
5. Optionally enable **Read OCR too** and capture again. The existing OCR pipeline
   runs in the background; initial model loading/download can take time. Inspect
   the raw text against the image. Full-screen labelled readings still require
   explicit units (before or after the value). For the paired-tape HUD profile,
   separate label and digit crops are read without the waypoint fallback. Each
   crop requires consistent numeric output and a recognised instrument label.
   If a scrolling tape tick obscures that label, an expanded full-screen label
   (ALTITUDE or AIRSPEED/IAS) must independently report the exact same value.
   Dedicated label crops exclude the readout digits and most tape ticks. A
   wider label/readout crop is retried when the tight crop clips a glyph; both
   attempts and their bounding boxes are retained in the diagnostic report.
   Feet/knots are **assumed from that experimental profile**, not recognised units.
   Missing labels, mixed text or disagreements between sources remain unavailable.
   Full-screen tape ticks and chat numbers never substitute for a readout.
6. Use **Save diagnostic ZIP** to save the original image, annotated image and
   JSON report, plus isolated numeric readout crops when available. Review visible
   game/player information before sharing. No files
   are uploaded automatically. **Open screenshot** also supports offline review.

A foreground check cannot rule out another application's always-on-top overlay.
Inspect each captured image. Black frames and focus changes are rejected; use
windowed/borderless mode if capture fails. Live capture requires Windows; offline
image inspection works on the cloud machine. The diagnostic window must finish
capture/OCR before closing; it never enables automated flight controls.

## Required evidence before calibrated attitude or control

Collect original-resolution diagnostic ZIPs from the actual EXE for:

- Straight-and-level flight, several known nose-up/nose-down attitudes, and left
  and right banks. Include readable cockpit pitch marks and bank reference.
- At least two conventional aircraft, different cockpit zoom levels/resolutions,
  daylight/night/clouds and bright terrain. Include scenes with no visible HUD.
- Several independently readable altitudes and airspeeds; record exact units.
- Windowed/fullscreen and second-monitor captures. Confirm AeroHelper is absent
  from the saved original image and the client crop contains the whole HUD.

Annotate the actual zero-pitch line, ladder spacing, fixed aircraft reference,
roll reference, tape/digital readout locations, units and expected values. The
current bilateral white-line search can mistake scenery/reference marks for a
horizon, even when its support is high; it is not a general attitude estimator.
Pitch needs a validated reference and scale; screen-line slope alone is not a
calibrated bank angle. Real annotated fixtures, temporal consistency/dropout
checks, independent pitch/roll validation and an explicit disarm path are needed
before any flight inputs. Do not use an unverified single frame for control.

## Development validation

Run `python -m unittest discover -s tests -v` with the declared dependencies.
The suite includes synthetic geometry/label parsing, mocked Windows capture,
worker error handling, offscreen Qt rendering/restoration and diagnostic export.
Synthetic/mocked checks do not establish real-game recognition or Windows EXE
runtime behavior. GitHub Actions runs this suite before packaging the EXE.

The Windows build also launches the packaged EXE with an internal CI smoke-test
flag. It opens the actual HUD menu callback, resizes the native dialog, processes
a synthetic frame and verifies preview rendering. A missing/failed report blocks
artifact upload. Upload explicitly includes hidden dependency folders (NumPy's
OpenBLAS DLL lives in `numpy/.libs`). CI then downloads that artifact into a
separate directory and repeats the dependency and EXE checks with toolchain
folders removed from PATH. Only a green workflow confirms the downloadable
package passed. These checks do not capture the desktop or contact Roblox.

The first real-capture regression fixture contains only the central HUD from a
3440×1440 capture: altitude 29,841 ft, indicated airspeed 89 knots, near-horizontal
zero-pitch line at approximately y=833. Chat and player rosters are excluded.
Geometry is checked at multiple scales and a reconstructed ultrawide viewport.
CPU EasyOCR was also run on the uploaded original using the actual region OCR
pipeline; both numeric readouts matched the visible image. This one capture does
not validate other aircraft, changing instruments, bank angles or flight control.

A second central-HUD fixture covers a night capture at 29,659 ft / 88 knots.
Its original combined label/readout crop lost ALT to overlapping tape ticks.
The separate label crop and exact-value corroboration path are regression-tested;
missing, truncated or conflicting corroborating values are rejected.
