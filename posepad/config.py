"""Loading and validating profile files.

A profile is a YAML file with ``gestures`` (what to detect) and ``bindings``
(what each gesture does on the virtual controller).  See ``profiles/`` and
the README for complete examples.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .backends import GAMEPAD_BACKENDS
from .bindings import AXES, AXIS_ALIASES, BUTTON_ALIASES, BUTTONS, MODES, Binding
from .expr import Expression, ExpressionError, _suggest
from .gestures import ExprGesture, Gesture, SequenceGesture, TemplateGesture, topological_order
from .templates import PoseTemplate

_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
TIMING_KEYS = {"hold", "min_on", "cooldown", "min_visibility", "threshold"}
GESTURE_KEYS = TIMING_KEYS | {"when", "value", "release", "template", "tolerance",
                              "sequence", "within", "description"}
BINDING_KEYS = {"gesture", "when", "value", "button", "axis", "key", "mode", "tap_time",
                "scale", "deadzone", "invert", "description"}
TOP_KEYS = {"name", "description", "camera", "pose", "output", "smoothing", "poses",
            "defaults", "gestures", "bindings", "watch"}


class ConfigError(ValueError):
    def __init__(self, path: Path | str, problems: list[str]):
        self.path, self.problems = path, problems
        super().__init__(f"{path}:\n" + "\n".join(f"  - {p}" for p in problems))


@dataclass
class CameraConfig:
    device: int | str = 0
    width: int = 640
    height: int = 480
    fps: int = 30
    mirror: bool = True     # mirror the preview (does not affect left/right in gestures)


@dataclass
class PoseConfig:
    model: str = "lite"     # lite | full | heavy
    min_detection_confidence: float = 0.5
    min_tracking_confidence: float = 0.5


@dataclass
class Profile:
    path: Path
    name: str = "profile"
    description: str = ""
    camera: CameraConfig = field(default_factory=CameraConfig)
    pose: PoseConfig = field(default_factory=PoseConfig)
    output: str = "auto"
    output_options: dict[str, Any] = field(default_factory=dict)
    smoothing: dict[str, float] = field(default_factory=dict)
    poses_dir: Path | None = None
    gestures: dict[str, Gesture] = field(default_factory=dict)
    bindings: list[Binding] = field(default_factory=list)
    watch: list[Expression] = field(default_factory=list)

    @property
    def needs_keyboard(self) -> bool:
        return any(b.key for b in self.bindings)

    @property
    def needs_gamepad(self) -> bool:
        return any(b.button or b.axis for b in self.bindings)


def load_profile(path: str | Path) -> Profile:
    path = Path(path)
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as e:
        raise ConfigError(path, [f"invalid YAML: {e}"]) from None
    except OSError as e:
        raise ConfigError(path, [str(e)]) from None
    return parse_profile(data, path)


def parse_profile(data: Any, path: Path) -> Profile:
    problems: list[str] = []
    if not isinstance(data, dict):
        raise ConfigError(path, ["the profile must be a mapping"])
    for k in data:
        if k not in TOP_KEYS:
            problems.append(f"unknown section {k!r}{_suggest(str(k), TOP_KEYS)}")

    prof = Profile(path=path, name=str(data.get("name", path.stem)),
                   description=str(data.get("description", "")))
    prof.camera = _dataclass_from(CameraConfig, data.get("camera"), "camera", problems)
    prof.pose = _dataclass_from(PoseConfig, data.get("pose"), "pose", problems)
    if prof.pose.model not in ("lite", "full", "heavy"):
        problems.append(f"pose.model must be lite, full or heavy (got {prof.pose.model!r})")

    output = data.get("output", "auto")
    if isinstance(output, dict):
        prof.output_options = {k: v for k, v in output.items() if k != "backend"}
        for k in prof.output_options:
            if k != "persona":
                problems.append(f"output.{k}: unknown setting (only 'backend' and 'persona')")
        output = output.get("backend", "auto")
    if output not in ("auto", "keyboard") + GAMEPAD_BACKENDS:
        problems.append(f"output must be one of auto, {', '.join(GAMEPAD_BACKENDS)}, keyboard "
                        f"(got {output!r})")
    persona = prof.output_options.get("persona")
    if persona is not None:
        from .backends.ojd import PERSONAS
        if persona not in PERSONAS:
            problems.append(f"output.persona must be one of {', '.join(PERSONAS)} (got {persona!r})")
    prof.output = str(output)
    prof.smoothing = dict(data.get("smoothing") or {})

    poses = data.get("poses", "poses")
    prof.poses_dir = (path.parent / poses).resolve() if poses else None

    defaults = data.get("defaults") or {}
    for k in defaults:
        if k not in TIMING_KEYS | {"tolerance"}:
            problems.append(f"defaults.{k}: unknown setting")

    raw_gestures = data.get("gestures") or {}
    if not isinstance(raw_gestures, dict):
        problems.append("gestures must be a mapping of name: definition")
        raw_gestures = {}
    raw_bindings = data.get("bindings") or []
    if not isinstance(raw_bindings, list):
        problems.append("bindings must be a list")
        raw_bindings = []

    templates = _load_templates(prof.poses_dir, problems)

    # Every name an expression may reference: declared gestures, recorded poses
    # and the anonymous gestures created for inline binding conditions.
    names = set(raw_gestures) | set(templates)

    for name, spec in raw_gestures.items():
        where = f"gestures.{name}"
        if not _NAME_RE.match(str(name)):
            problems.append(f"{where}: names must be letters, digits and _ (start with a letter)")
            continue
        try:
            prof.gestures[name] = _parse_gesture(name, spec, defaults, names, templates)
        except (ExpressionError, ValueError, TypeError) as e:
            problems.append(f"{where}: {e}")

    for name, tpl in templates.items():
        if name not in prof.gestures:
            prof.gestures[name] = TemplateGesture(
                name, template=tpl, **_timing(defaults),
                tolerance=float(defaults.get("tolerance", 0.35)))

    for i, spec in enumerate(raw_bindings):
        where = f"bindings[{i}]"
        try:
            b = _parse_binding(spec, i, defaults, names, prof)
            if b.gesture not in prof.gestures and b.gesture not in names:
                raise ValueError(f"unknown gesture {b.gesture!r}"
                                 f"{_suggest(b.gesture, prof.gestures)}")
            if b.gesture in prof.gestures:
                prof.bindings.append(b)
        except (ExpressionError, ValueError, TypeError) as e:
            problems.append(f"{where}: {e}")

    for i, src in enumerate(data.get("watch") or []):
        try:
            prof.watch.append(Expression(src, names))
        except ExpressionError as e:
            problems.append(f"watch[{i}]: {e}")

    if not problems:
        try:
            topological_order(prof.gestures)
        except ExpressionError as e:
            problems.append(str(e))
    if problems:
        raise ConfigError(path, problems)
    return prof


def _dataclass_from(cls, spec, where: str, problems: list[str]):
    if spec is None:
        return cls()
    if not isinstance(spec, dict):
        problems.append(f"{where} must be a mapping")
        return cls()
    fields = cls.__dataclass_fields__
    kwargs = {}
    for k, v in spec.items():
        if k not in fields:
            problems.append(f"{where}.{k}: unknown setting{_suggest(str(k), fields)}")
        else:
            kwargs[k] = v
    return cls(**kwargs)


def _timing(spec: dict) -> dict[str, float]:
    return {k: float(spec[k]) for k in TIMING_KEYS if k in spec}


def _load_templates(poses_dir: Path | None, problems: list[str]) -> dict[str, PoseTemplate]:
    out: dict[str, PoseTemplate] = {}
    if poses_dir is None or not poses_dir.is_dir():
        return out
    for f in sorted(poses_dir.glob("*.json")):
        if not _NAME_RE.match(f.stem):
            problems.append(f"{f.name}: pose file names must be valid gesture names")
            continue
        try:
            out[f.stem] = PoseTemplate.load(f)
        except (ValueError, KeyError, OSError) as e:
            problems.append(f"{f.name}: {e}")
    return out


def _parse_gesture(name: str, spec: Any, defaults: dict, names: set[str],
                   templates: dict[str, PoseTemplate]) -> Gesture:
    if isinstance(spec, str):
        spec = {"when": spec}
    if isinstance(spec, list):
        spec = {"sequence": spec}
    if not isinstance(spec, dict):
        raise ValueError("expected an expression string or a mapping")
    for k in spec:
        if k not in GESTURE_KEYS:
            raise ValueError(f"unknown setting {k!r}{_suggest(str(k), GESTURE_KEYS)}")
    timing = _timing(defaults) | _timing(spec)
    kinds = [k for k in ("value", "template", "sequence") if k in spec]
    if len(kinds) > 1:
        raise ValueError(f"choose one of value/template/sequence, not {' and '.join(kinds)}")
    if not kinds and "when" not in spec:
        raise ValueError("needs one of: when, value, template, sequence")

    others = names - {name}
    if "template" in spec:
        tname = str(spec["template"])
        tname = tname[:-5] if tname.endswith(".json") else tname
        if tname not in templates:
            raise ValueError(f"no recorded pose {tname!r} in the poses folder "
                             f"(record it with: posepad record {tname})")
        return TemplateGesture(name, template=templates[tname], **timing,
                               tolerance=float(spec.get("tolerance",
                                                        defaults.get("tolerance", 0.35))))
    if "sequence" in spec:
        steps = spec["sequence"]
        if not isinstance(steps, list) or len(steps) < 2:
            raise ValueError("sequence needs a list of at least two steps")
        return SequenceGesture(name, **timing, steps=[Expression(s, others) for s in steps],
                               within=float(spec.get("within", 1.0)))
    return ExprGesture(
        name, **timing,
        when=Expression(spec["when"], others) if "when" in spec else None,
        release=Expression(spec["release"], others) if "release" in spec else None,
        value_expr=Expression(spec["value"], others) if "value" in spec else None,
    )


def parse_target(text: str) -> dict[str, Any]:
    """``"A"``, ``"left_x"``, ``"left_x=-1"``, ``"key:space"`` -> binding fields."""
    t = text.strip()
    if t.lower().startswith("key:"):
        key = t[4:].strip()
        _check_key(key)
        return {"key": key}
    value = None
    if "=" in t:
        t, v = t.split("=", 1)
        t = t.strip()
        value = float(v)
    axis = AXIS_ALIASES.get(t.lower(), t.lower())
    if axis in AXES:
        return {"axis": axis, "value": value}
    if value is not None:
        raise ValueError(f"'=value' only applies to axes, not {t!r}")
    button = BUTTON_ALIASES.get(t.upper(), t.upper())
    if button in BUTTONS:
        return {"button": button}
    raise ValueError(f"unknown target {text!r}"
                     f"{_suggest(t.upper(), BUTTONS + tuple(a.upper() for a in AXES))}. "
                     f"Use a button ({', '.join(BUTTONS)}), an axis ({', '.join(AXES)}) "
                     f"or key:<name>")


def _check_key(key: str) -> None:
    if not key:
        raise ValueError("key: needs a key name, e.g. key:space")


def _parse_binding(spec: Any, index: int, defaults: dict, names: set[str],
                   prof: Profile) -> Binding:
    if isinstance(spec, str):
        if "->" not in spec:
            raise ValueError("short form is 'gesture -> target', e.g. 'jump -> A'")
        g, t = (s.strip() for s in spec.split("->", 1))
        return Binding(gesture=g, **parse_target(t))
    if not isinstance(spec, dict):
        raise ValueError("expected 'gesture -> target' or a mapping")
    for k in spec:
        if k not in BINDING_KEYS:
            raise ValueError(f"unknown setting {k!r}{_suggest(str(k), BINDING_KEYS)}")

    if ("gesture" in spec) + ("when" in spec) != 1:
        raise ValueError("give exactly one of 'gesture: <name>' or 'when: <expression>'")
    gesture = spec.get("gesture")
    if "when" in spec:
        # Inline condition: becomes an anonymous gesture.
        gesture = f"_binding{index}"
        prof.gestures[gesture] = ExprGesture(gesture, **_timing(defaults),
                                             when=Expression(spec["when"], names))

    targets = [k for k in ("button", "axis", "key") if k in spec]
    if len(targets) != 1:
        raise ValueError("give exactly one of button, axis or key")
    fields: dict[str, Any] = {}
    if "key" in spec:
        _check_key(str(spec["key"]))
        fields["key"] = str(spec["key"])
    else:
        fields = parse_target(str(spec[targets[0]]))
        if ("button" in spec) != ("button" in fields):
            raise ValueError(f"{spec[targets[0]]!r} is not a valid {targets[0]}")
    mode = spec.get("mode", "hold")
    if mode not in MODES:
        raise ValueError(f"mode must be one of {', '.join(MODES)}")
    if "value" in spec:
        fields["value"] = float(spec["value"])
    return Binding(
        gesture=str(gesture), mode=mode, **fields,
        tap_time=float(spec.get("tap_time", 0.08)),
        scale=float(spec.get("scale", 1.0)),
        deadzone=float(spec.get("deadzone", 0.0)),
        invert=bool(spec.get("invert", False)),
    )
