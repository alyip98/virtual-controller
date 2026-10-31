# posepad

Turn your body into a game controller. posepad watches you through the
webcam, recognises poses and movements you configure, and drives a **virtual
Xbox 360 controller** (or keyboard) that any game on the machine can use.

```
jump → A     crouch → B     lean → left stick     wave → BACK     T-pose → whatever you like
```

* Poses and movements are described in one small YAML file — or **recorded by
  demonstration** with `posepad record`.
* Thresholds are in body units (shoulder widths), so they keep working as you
  move around the room.
* Profiles **hot-reload** when saved; the preview shows every gesture live.
* Losing sight of you, or pressing `p`, releases every input.

See [docs/DESIGN.md](docs/DESIGN.md) for the architecture.

## Install

```bash
pip install -e ".[linux,keyboard]"      # Linux
pip install -e ".[windows,keyboard]"    # Windows (also install the ViGEmBus driver)
pip install -e ".[macos]"               # macOS, see "macOS" below
```

The pose model (~5 MB) is downloaded on first run to `~/.cache/posepad`.

**Linux uinput permissions** — the virtual pad is created through `/dev/uinput`:

```bash
sudo modprobe uinput
echo 'KERNEL=="uinput", GROUP="input", MODE="0660"' | sudo tee /etc/udev/rules.d/99-uinput.rules
sudo usermod -aG input "$USER"     # then log out and back in
```

## macOS

macOS only lets apps signed with an Apple-restricted entitlement publish a
virtual gamepad, and a Python script can't have one. posepad gets around this
by sending its output to **[OpenJoystickDriver](https://github.com/xsyetopz/OpenJoystickDriver)**
(OJD), a free, notarized app that does have it:

1. Install OJD (macOS 12+), open it once, and give it the permissions it asks for.
2. Run posepad as usual. `output: auto` finds `ojd` and streams to `ojd virtual feed`.
   If `ojd` isn't on your PATH, set `POSEPAD_OJD=/path/to/ojd`.
3. Choose who should see the pad:

   ```yaml
   output:
     backend: ojd
     persona: sdl-compatible      # SDL games, Steam (default)
     # persona: game-controller-compatible   # native Mac games (GameController framework)
     # persona: generic
   ```

Without OJD, use keyboard output (`output: keyboard` with `key:` bindings).

**Permissions** are granted to the app you run posepad from (Terminal, iTerm,
VS Code…), not to posepad. Allow it under System Settings → Privacy & Security
→ **Camera**, plus **Accessibility** if you use keyboard output, then restart
that app. posepad detects missing Accessibility and says so; without this check,
key presses would be dropped silently.

**Apple Silicon**: any supported Python. **Intel Macs**: mediapipe stopped
shipping Intel wheels after 0.10.21, so use Python 3.9–3.12. pip then picks
0.10.21 automatically.

OJD is pre-release software, and its docs say its feed hasn't yet been tested
with games or for latency. If a game ignores the pad, try another persona.

## Quick start

```bash
posepad run starter                 # bundled profile: jump, crouch, lean, hands up, wave
posepad run starter -o log          # just print controller output, nothing is sent
```

Stand back so your whole body is in view and stay still for a second while it
calibrates. Preview keys: **q** quit · **p** pause output · **c** recalibrate · **r** reload.

Bundled profiles: `starter`, `racing` (imaginary steering wheel), `boxing`,
`keyboard` (arrow keys + space).

## Make your own profile

```bash
posepad new my.yaml
posepad run my.yaml -w "right_wrist.y" -w "shoulder_mid.vy"   # live values for tuning
```

```yaml
name: My game

gestures:
  # A pose is a condition on body points (+x = your right, +y = up, 1.0 = shoulder width)
  hands_up: left_wrist.y > head.y and right_wrist.y > head.y

  # A movement uses velocity (vx vy vz speed) or displacement from your neutral stance (dx dy dz)
  punch:
    when: right_wrist.speed > 6 and angle(right_shoulder, right_elbow, right_wrist) > 140
    cooldown: 0.3          # one punch = one press

  crouch:
    when: shoulder_mid.dy < -0.6
    release: shoulder_mid.dy > -0.4

  # Analog: any number, e.g. lean angle for steering
  lean:
    value: deadzone(clamp(-hip_mid.x * 3), 0.15)

  # Several steps in order
  wave:
    sequence: [right_wrist.x > 0.9, right_wrist.x < 0.3, right_wrist.x > 0.9]
    within: 1.5

bindings:
  - hands_up -> Y
  - punch -> X
  - crouch -> left_y=-1
  - lean -> left_x
  - wave -> key:esc
```

### Record a pose instead of writing one

```bash
posepad record t_pose -p my.yaml --joints arms
```

Strike the pose when the countdown ends. It is saved to `poses/t_pose.json`
next to the profile and immediately available as gesture `t_pose`:

```yaml
bindings:
  - t_pose -> RB
```

Adjust strictness with `gestures: { t_pose: { template: t_pose, tolerance: 0.25 } }`.

### Check and debug

```bash
posepad check my.yaml -v                     # validate without a camera
posepad reference                            # every point, attribute, function, button, axis
posepad run my.yaml --save-session s.jsonl   # record yourself playing...
posepad replay s.jsonl -p my.yaml            # ...and re-run tweaked thresholds offline
```

Mistakes are reported precisely:

```
my.yaml:
  - gestures.punch: unknown body point 'rigth_wrist' in 'rigth_wrist.speed > 6' (did you mean 'right_wrist'?)
  - bindings[2]: unknown gesture 'crunch' (did you mean 'crouch'?)
```

## Reference

**Gesture settings**: `when`, `value`, `template`, `sequence` + `within`,
`release`, `hold`, `min_on`, `cooldown`, `threshold` (analog), `tolerance`
(templates), `min_visibility`. Put shared timing under `defaults:`.

**Binding targets**: buttons `A B X Y LB RB BACK START GUIDE LS RS DPAD_UP
DPAD_DOWN DPAD_LEFT DPAD_RIGHT` (aliases: `cross circle square triangle l1 r1
up down …`), axes `left_x left_y right_x right_y lt rt` (`axis=value` for
boolean gestures), `key:<name>`. Options: `mode` (`hold`/`tap`/`toggle`),
`tap_time`, `scale`, `deadzone`, `invert`.

**Functions**: `angle(a, b, c)` joint angle at b (180 = straight),
`direction(a, b)` (0 = right, 90 = up), `dist(a, b)`, `dist3(a, b)`,
`clamp(v, lo=-1, hi=1)`, `remap(v, in_lo, in_hi, out_lo=0, out_hi=1)`,
`deadzone(v, dz)`, `between(v, lo, hi)`, `abs min max sqrt sign`.

**Profile sections**: `name`, `output` (`auto uinput vgamepad keyboard log`),
`camera` (`device width height fps mirror`), `pose` (`model: lite|full|heavy`,
confidences), `smoothing` (`min_cutoff beta calibrate_after`), `poses` (folder),
`defaults`, `gestures`, `bindings`, `watch` (expressions always shown in the preview).

## Development

```bash
pip install -e ".[dev]"
pytest
```

The core (`pipeline.py` and everything below it) needs no camera and is tested
with synthetic poses in `tests/helpers.py`.
