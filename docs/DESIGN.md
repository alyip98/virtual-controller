# posepad — design

posepad turns a webcam into a game controller: it tracks the player's body,
recognises configured poses and movements, and drives a virtual gamepad (or
keyboard) on the same machine. Games see an ordinary Xbox 360 controller.

## Goals

* **Works with any game** — output is an OS-level virtual gamepad, so no
  game integration is needed (on macOS via OpenJoystickDriver). Keyboard output covers games without pad support.
* **Configurable without code** — a profile is one YAML file. Poses can be
  described with short expressions *or* recorded by demonstration.
* **Fast iteration** — profiles hot-reload on save, the preview shows every
  gesture's live state, `-w EXPR` shows any value live, and sessions can be
  recorded and replayed offline.
* **Robust to the room** — thresholds are in body units, so they keep working
  when the player moves closer, further or off-centre, and with any camera
  resolution or aspect ratio.
* **Fail safe** — losing the player, or pressing `p`, releases every input.

## Pipeline

```
 camera ──► pose estimator ──► tracker ──► gesture engine ──► bindings ──► backend
 (OpenCV,    (MediaPipe Pose     (body frame,  (expressions,     (hold/tap/   (uinput,
  own thread) Landmarker, 33 pts) smoothing,    templates,        toggle,      vgamepad,
                                  velocity,     sequences,        axis maths)  keyboard,
                                  calibration)  debouncing)                    log)
```

Each stage is a small module with no knowledge of the stages around it:

| Module | Responsibility |
| --- | --- |
| `camera.py` | Background capture thread; always hands out the newest frame (low latency). Video files are paced frame-by-frame instead, for testing. |
| `pose.py` | `PoseEstimator` interface + MediaPipe Pose Landmarker (VIDEO mode, model auto-downloaded). Any 33-point BlazePose-ordered estimator can be swapped in. |
| `landmarks.py` | Landmark names, derived points (`shoulder_mid`, `hip_mid`, `torso`, `head`, …) and the image → **body frame** conversion. |
| `filters.py`, `tracker.py` | One-Euro filtering, velocity estimation, smoothed scale, automatic neutral-stance calibration. |
| `expr.py` | The safe expression language. |
| `gestures.py` | Gesture types and the per-frame engine (dependency ordered). |
| `templates.py`, `record.py` | Recording and matching pose templates. |
| `bindings.py` | Gesture state → `ControllerState` (buttons, axes, keys). |
| `backends/` | `ControllerState` → OS virtual devices. |
| `config.py` | YAML loading and validation with precise, suggestive error messages. |
| `pipeline.py` | The camera-free core (tracker + engine + bindings): what tests and `replay` drive. |
| `app.py`, `overlay.py`, `cli.py` | Live loop, preview window, hot reload, commands. |

## The body frame

Raw landmarks are in image coordinates (0..1, y down) — useless for
thresholds because they change with distance and framing. Every frame is
converted to a player-centred frame:

* origin between the shoulders, **1.0 = one shoulder width**
* **+x = the player's own right**, +y = up, +z = towards the camera

Left/right always mean the player's anatomical side, independent of whether the
preview is mirrored. Shoulder width is smoothed over time so turning sideways
does not suddenly inflate every coordinate.

Three families of attribute are exposed on every point:

| attribute | meaning | typical use |
| --- | --- | --- |
| `x y z` | position relative to the shoulders | poses: "hand above head", "leaning" |
| `vx vy vz speed` | velocity, shoulder widths / s, camera-anchored | quick motions: punches, swipes, jumps |
| `dx dy dz` | displacement from the calibrated neutral stance | whole-body moves: crouch, side-step, jump height |

Velocities and displacements are *not* relative to the shoulders, otherwise a
jump (where everything moves together) would read as zero. Calibration happens
automatically after the player stands still for a second, and on `c`.

## Gestures

| kind | YAML | evaluates to |
| --- | --- | --- |
| pose / movement | `when: <bool expr>` (or just a string) | on/off |
| analog | `value: <number expr>` | a number (active when `\|value\| ≥ threshold`) |
| recorded pose | `template: name` (or just drop a file in `poses/`) | on/off, similarity shown |
| sequence | `sequence: [step, step, …]` + `within:` | momentary on when completed in order |

All kinds share timing controls, which is what makes motion input feel good:

* `hold` — must be true this long before triggering (rejects noise)
* `min_on` — once triggered stay on at least this long (fast motions last 1–2
  frames; games need to see the button for longer)
* `cooldown` — ignore re-triggers right after release (one punch = one press)
* `release` — a separate "off" condition, for hysteresis on analog-ish poses

Gestures can reference other gestures by name (`jab and not guard`); they are
evaluated in topological order and cycles are rejected at load time.
If a point a gesture needs is not visible, the gesture is *untracked* — inactive
with value 0 — rather than guessing.

### Expression language

Python expression syntax restricted by an AST whitelist: arithmetic,
comparisons, `and/or/not`, conditional expressions, point attributes and a
fixed set of functions (`angle`, `direction`, `dist`, `dist3`, `clamp`, `remap`,
`deadzone`, `between`, `abs`, `min`, `max`, `sqrt`, `sign`). No attribute
access except on body points, no strings, no builtins — a downloaded profile
cannot run code. Unknown names are reported with "did you mean" suggestions.

### Recorded poses

`posepad record NAME` counts down, captures ~1.5 s of the pose and stores the
mean body-frame position of a joint set (`arms`, `upper`, `lower`, `body`, or
explicit joints). Matching is the mean distance over the visible joints;
`tolerance` (default 0.35 shoulder widths) is the activation radius, and the
similarity `1 − err / (2·tolerance)` is shown in the preview. Every JSON file
in the profile's `poses/` folder becomes a gesture automatically, so the
workflow is: record → add one binding line → save (hot reload picks it up).

## Bindings

```yaml
- jump -> A                  # short form: gesture -> target
- lean -> left_x             # analog gesture drives an axis directly
- duck -> left_y=-1          # boolean gesture pushes an axis to a value
- wave -> key:space          # keyboard
- gesture: punch             # long form for options
  button: X
  mode: tap                  # hold | tap | toggle
- when: nose.y < -1          # inline condition, no named gesture needed
  button: B
```

Several bindings may drive the same axis; values are summed and clamped.
Analog options: `scale`, `deadzone`, `invert`.

## Output backends

| backend | mechanism | notes |
| --- | --- | --- |
| `uinput` | python-evdev → `/dev/uinput` | Linux; Xbox 360 IDs and xpad event codes so SDL/Steam map it automatically |
| `vgamepad` | ViGEmBus (Windows) / uinput (Linux) | Windows default |
| `ojd` | stream of JSON frames to OpenJoystickDriver's `ojd virtual feed` | macOS default; see below |
| `keyboard` | pynput | any OS; used automatically when a profile has `key:` bindings |
| `log` | stdout | testing; also the fallback when no pad backend works |

### macOS

There is no uinput or ViGEm on macOS. A process can publish a virtual HID
device (`IOHIDUserDeviceCreateWithProperties`, macOS 10.15+, or CoreHID
`HIDVirtualDevice`, macOS 15+) only if it is signed with
`com.apple.developer.hid.virtual.device`. Apple restricts that entitlement:
it is granted on request and ships in a provisioning profile, so a Python
interpreter can't carry it. The options were:

| option | verdict |
| --- | --- |
| Own signed Swift helper (CoreHID / IOHIDUserDevice) that posepad talks to | Most control. Needs an Apple Developer account, approval for the entitlement, and a notarized helper app to maintain. Possible later. |
| Disable SIP/AMFI to run without the entitlement | Rejected: weakens system security; not something to ask users to do. |
| **Delegate to OpenJoystickDriver** | **Chosen.** OJD is notarized, holds the entitlement, and has a public line-based feed (`ojd virtual feed --as <persona>`) for exactly this. |
| Keyboard only (CGEvent via pynput) | Kept as the no-install fallback. Needs Accessibility permission. |

The `ojd` backend keeps one `ojd virtual feed` process alive and writes a
frame whenever the state changes, plus a keepalive every 0.5 s (OJD drops a
pad after 2 s of silence). Mapping: A/B/X/Y → South/East/West/North,
LB/RB → LeftShoulder/RightShoulder, BACK/START/GUIDE, LS/RS → stick clicks,
D-pad → `dpad`, and axes with Y negated (OJD sticks are +y = down). Closing
stdin removes the pad.

Persona compatibility, from public reports of virtual HID pads on macOS: SDL
and Steam recognise known controller IDs. Apple's GameController framework
does not see generic virtual HID pads, so OJD's `game-controller-compatible`
persona exists for native games. Raw-HID readers such as browsers may map
buttons wrongly.

Camera access and Accessibility are granted to the launching terminal app.
posepad checks Accessibility with `AXIsProcessTrusted` before using keyboard
output, and adds a Camera hint when the camera won't open.

## Latency budget (typical laptop, 640×480)

capture ≈ 0–33 ms (newest frame only) · pose lite ≈ 15–30 ms ·
filtering/gestures < 1 ms · uinput < 1 ms. The One-Euro filter's `beta`
trades jitter against lag; `smoothing.min_cutoff/beta` are configurable.

## Extending

* **New estimator** (e.g. MoveNet, a depth camera): implement
  `PoseEstimator.process()` returning a `RawPose` in BlazePose order.
* **New output** (DualShock 4, MIDI, OSC…): subclass `Backend.send()`.
* **New expression helpers**: add to `FUNCTIONS` in `expr.py`.

## Possible next steps

* Multiple players (MediaPipe supports `num_poses > 1`; map each to a pad).
* Hand landmarks for finger gestures (pinch → trigger).
* A GUI profile editor on top of the same YAML (record, drag thresholds on live graphs).
* Learned gestures (DTW / small classifier) trained from a few recorded repetitions.
