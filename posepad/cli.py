"""Command line entry point: ``posepad <command>``."""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
from pathlib import Path

from . import __version__
from .config import ConfigError, load_profile

PROFILES_DIR = Path(__file__).resolve().parent / "profiles"


def _resolve_profile(name: str) -> Path:
    p = Path(name)
    if p.exists():
        return p
    for candidate in (PROFILES_DIR / name, PROFILES_DIR / f"{name}.yaml"):
        if candidate.exists():
            return candidate
    raise SystemExit(f"profile not found: {name}")


def cmd_run(a) -> int:
    from .app import run
    run(_resolve_profile(a.profile), output=a.output, preview=not a.no_preview,
        camera=a.camera, watch=a.watch, save_session=a.save_session, start_paused=a.paused)
    return 0


def cmd_check(a) -> int:
    status = 0
    for name in a.profiles:
        try:
            prof = load_profile(_resolve_profile(name))
        except ConfigError as e:
            print(f"✗ {e}")
            status = 1
            continue
        print(f"✓ {prof.path}: '{prof.name}' - {len(prof.gestures)} gestures, "
              f"{len(prof.bindings)} bindings, output {prof.output}")
        if a.verbose:
            for g in prof.gestures.values():
                if not g.name.startswith("_"):
                    print(f"    gesture {g.name} ({type(g).__name__.replace('Gesture', '').lower()})")
            for b in prof.bindings:
                extra = f" [{b.mode}]" if b.mode != "hold" else ""
                print(f"    {b.gesture} -> {b.target}{extra}")
        bound = {b.gesture for b in prof.bindings}
        used = set().union(*(g.dependencies() for g in prof.gestures.values()))
        for g in prof.gestures:
            if g not in bound and g not in used:
                print(f"    note: gesture '{g}' is not bound to anything")
    return status


def cmd_record(a) -> int:
    from .record import record_pose
    if a.profile:
        prof = load_profile(_resolve_profile(a.profile))
        out_dir = prof.poses_dir or Path("poses")
        mirror, model, camera = prof.camera.mirror, prof.pose.model, prof.camera.device
    else:
        out_dir, mirror, model, camera = Path(a.out or "poses"), True, "lite", 0
    if a.out:
        out_dir = Path(a.out)
    if a.camera is not None:
        camera = int(a.camera) if str(a.camera).isdigit() else a.camera
    path = record_pose(a.name, out_dir, joints=a.joints, countdown=a.countdown,
                       duration=a.duration, camera=camera, mirror=mirror, model=model)
    print(f"saved {path}")
    print(f"bind it in your profile with:   - {a.name} -> A")
    return 0


def cmd_replay(a) -> int:
    from .backends import LogBackend
    from .pipeline import Pipeline
    from .session import read_session

    prof = load_profile(_resolve_profile(a.profile))
    aspect, frames = read_session(a.session)
    pipe = Pipeline(prof, aspect)
    pad = LogBackend()
    prev: dict[str, bool] = {}
    for t, raw in frames:
        res = pipe.step(raw, t)
        for name, st in res.states.items():
            if prev.get(name) != st.active and not name.startswith("_"):
                if st.active or name in prev:
                    print(f"{t:8.2f}s  {name:<20} {'ON' if st.active else 'off'}")
            prev[name] = st.active
        if a.pad:
            pad.send(res.output)
    return 0


def cmd_new(a) -> int:
    dest = Path(a.path)
    if dest.exists() and not a.force:
        raise SystemExit(f"{dest} exists (use --force to overwrite)")
    shutil.copy(PROFILES_DIR / "starter.yaml", dest)
    print(f"created {dest}\nedit it, then:  posepad run {dest}")
    return 0


def cmd_reference(a) -> int:
    from .bindings import AXES, BUTTONS
    from .expr import FUNCTIONS, POINT_ATTRS
    from .landmarks import DERIVED_POINTS, LANDMARK_NAMES
    from .templates import JOINT_SETS
    print("Body points:\n  " + ", ".join(LANDMARK_NAMES))
    print("Derived points:\n  " + ", ".join(f"{k} ({'+'.join(v)})" for k, v in DERIVED_POINTS.items()))
    print("Point attributes:\n  " + ", ".join(sorted(POINT_ATTRS)))
    print("Functions:\n  " + ", ".join(sorted(FUNCTIONS)))
    print("Buttons:\n  " + ", ".join(BUTTONS))
    print("Axes:\n  " + ", ".join(AXES) + "   (sticks -1..1, +y = up; triggers 0..1)")
    print("Joint sets for `record --joints`:\n  " + ", ".join(JOINT_SETS))
    print("Coordinates: origin between the shoulders, 1.0 = one shoulder width,\n"
          "  +x = player's right, +y = up, +z = towards the camera.\n"
          "  vx/vy/vz are velocities (shoulder widths per second);\n"
          "  dx/dy/dz are displacement from the calibrated neutral stance.")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="posepad",
                                description="Turn body movements into a virtual game controller.")
    p.add_argument("--version", action="version", version=f"posepad {__version__}")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="start the camera and drive the virtual controller")
    r.add_argument("profile", nargs="?", default="starter")
    r.add_argument("-o", "--output", choices=["auto", "uinput", "vgamepad", "keyboard", "log"])
    r.add_argument("--camera", help="camera index or video file")
    r.add_argument("--no-preview", action="store_true")
    r.add_argument("-w", "--watch", action="append", metavar="EXPR",
                   help="show an expression's live value (repeatable), e.g. -w 'right_wrist.vx'")
    r.add_argument("--save-session", metavar="FILE", help="record landmarks for `replay`")
    r.add_argument("--paused", action="store_true", help="start with output paused")
    r.set_defaults(func=cmd_run)

    c = sub.add_parser("check", help="validate profiles without starting the camera")
    c.add_argument("profiles", nargs="+")
    c.add_argument("-v", "--verbose", action="store_true")
    c.set_defaults(func=cmd_check)

    rec = sub.add_parser("record", help="record a pose template from the camera")
    rec.add_argument("name")
    rec.add_argument("-p", "--profile", help="save into this profile's poses folder")
    rec.add_argument("--out", help="output folder (default: ./poses)")
    rec.add_argument("--joints", default="body", help="joint set or list (see `reference`)")
    rec.add_argument("--countdown", type=float, default=3.0)
    rec.add_argument("--duration", type=float, default=1.5)
    rec.add_argument("--camera")
    rec.set_defaults(func=cmd_record)

    rp = sub.add_parser("replay", help="run a profile against a saved session")
    rp.add_argument("session")
    rp.add_argument("-p", "--profile", required=True)
    rp.add_argument("--pad", action="store_true", help="also print controller output")
    rp.set_defaults(func=cmd_replay)

    n = sub.add_parser("new", help="create a profile from the starter template")
    n.add_argument("path")
    n.add_argument("--force", action="store_true")
    n.set_defaults(func=cmd_new)

    ref = sub.add_parser("reference", help="list points, functions, buttons and axes")
    ref.set_defaults(func=cmd_reference)

    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO if a.verbose else logging.WARNING,
                        format="%(levelname)s %(message)s")
    try:
        return a.func(a)
    except ConfigError as e:
        print(e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
