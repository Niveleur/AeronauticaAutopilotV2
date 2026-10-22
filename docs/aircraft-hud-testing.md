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
6. Use **Save screenshot** to save a PNG of the HUD Test window's contents,
   including the preview, readings, and currently visible diagnostic text. It
   also works before capture or after a failed capture. It does not capture the
   desktop or native Windows title bar. The build ID appears in the text pane.
   **Save diagnostic ZIP** includes this window image as `hud-test-window.png`
   and the complete diagnostic text as `diagnostics.txt`, alongside the original image, annotated image and
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

## Altitude cross-check and backup

Each OCR capture reads the cockpit altitude crop and a separate left-panel
region from the **same image**. The panel requires an explicit ALTITUDE label,
a unique numeric value and feet unit; it works even if cockpit tapes are absent.
Full-screen OCR is retained for diagnostics, but is not counted as a third source
because it includes the same left panel.

- Both sources present, difference **at most 5 ft**: report agreement and retain
  the cockpit value (no averaging).
- Both present, difference **greater than 5 ft**: flag disagreement and withhold
  the combined altitude.
- Cockpit unreadable, panel readable: use an explicitly marked, unconfirmed
  left-panel fallback.
- Panel unreadable, cockpit readable: retain an explicitly unconfirmed cockpit
  reading. No usable source: altitude remains unavailable.

The GUI shows both values, difference, tolerance and source status. The ZIP
contains the source readings, comparison and left-panel crop/OCR. No values are
carried over from previous frames. Agreement is a single-frame OCR cross-check,
not calibrated accuracy or permission to enable flight controls.

If the broad left-panel crop loses the small feet suffix, OCR retries a tighter
standard-layout altitude-card crop at 3× scale. It still requires the ALTITUDE
label, an explicit feet unit and a unique value. All attempt texts/bounds and
the selected crop are recorded. A valid broad reading is never retried merely
because it disagrees with the cockpit; the 5 ft rejection policy is unchanged.
The cropped 29,921 ft card fixture contains no chat or player identifiers.

## Read-only flight recording trial

Open **Aircraft HUD Test → Start read-only recording**, choose a destination
folder, and switch to Roblox during the 3-second countdown. AeroHelper minimizes;
no flight inputs are sent. Fly normally. Restore the HUD Test from the taskbar
and press **Stop recording and save ZIP**. Stopping waits for the current OCR
operation; closing is blocked until saving finishes. Sessions stop automatically
after 10 minutes of collection or approximately 200 MB of cropped PNGs. First
OCR initialization can take additional time if models need downloading.

The session folder contains a flushed `samples.jsonl`, instrument PNGs and a
`session.json` summary. A sibling ZIP is produced on completion; upload that ZIP
for review. The source folder remains available if packaging fails. Foreground
losses are logged without saving a screenshot. Only instrument regions are
persisted, not full-screen or desktop images. Check crops before sharing: the
ADI and left-panel positions assume the standard layout and are not confirmed
for every aircraft or UI scale.

OCR is sequential with a target minimum interval of 2 seconds, not guaranteed
2-second updates. A single OCR engine is reused. Every sample includes capture
time, processing delay, missing readings, and the existing 5-ft altitude
comparison. No old reading is substituted for a missing reading. Processing over
5 seconds is flagged as delayed. Raw changes are retained for review rather than
rejected with an arbitrary climb/dive-rate limit. Full-screen OCR is skipped;
local panel text may corroborate a tape label but is never a third altitude
source. Recording and analysis occur in one worker, so OCR can reduce the crop
sampling rate; this first trial measures that limitation as well.

ADI blue/brown pixel fractions are **experimental colour evidence only**. They
do not claim a detected boundary, valid pitch, valid roll or aircraft control.
Review the collected ADI crops against cloud, ocean, terrain and snow before
calibrating any attitude estimator. The main HUD horizon also remains unverified
in snowy areas and may be off-screen during steep dives.

## Tracking, continuity and smaller exports

Recording can reuse the previous frame's tape positions for at most a 5-second
capture gap, with unchanged resolution. Reuse requires both rails to retain at
least 45% thin-line support and their top/bottom end caps to retain at least 65%
horizontal support **in the current frame**. Foreground capture failure clears
the hint. Missing geometry or failed validation does not carry forward readings.
`geometry.layout_source` distinguishes fresh detection from validated reuse.

Empty or non-numeric altitude and speed OCR crops get the padded contrast retry.
Numeric disagreements are not overwritten by a more convenient retry. Original
and retry strings are preserved. The existing 5-ft altitude comparison remains.

`continuity` flags are diagnostic, with raw readings preserved: missing,
delayed (processing over 5 seconds), reacquired after a gap over 10 seconds, or
suspicious jump. Broad review thresholds are 500 ft/s plus 10 ft of slack and
100 knots/s plus 5 knots of slack. These are not aircraft performance limits or
flight-control validation. A suspicious sample does not update the comparison
baseline. Live recording status shows these flags; summaries count suspicious
readings and delayed samples.

On completion, the full archive is accompanied by a `-logs.zip` and independent
`-images-001.zip`, `-images-002.zip`, etc. Image groups target at most 20 MiB of
source files (before ZIP headers), with logs repeated in every part. Upload the
small logs ZIP first, then image ZIPs individually. They are ordinary independent
ZIPs and do not need reassembling. This avoids the 32 MiB transfer limit for
normal instrument crops. Original source folders and full ZIPs are retained.
