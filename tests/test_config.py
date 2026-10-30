from pathlib import Path

import pytest

from posepad.cli import PROFILES_DIR
from posepad.config import ConfigError, load_profile, parse_profile
from posepad.gestures import ExprGesture, SequenceGesture, TemplateGesture


@pytest.mark.parametrize("path", sorted(PROFILES_DIR.glob("*.yaml")), ids=lambda p: p.name)
def test_bundled_profiles_are_valid(path):
    prof = load_profile(path)
    assert prof.bindings


def parse(data, tmp_path=Path(".")):
    return parse_profile(data, tmp_path / "p.yaml")


def test_short_forms(tmp_path):
    p = parse({
        "gestures": {
            "up": "right_wrist.y > head.y",
            "lean": {"value": "clamp(-hip_mid.x * 3)"},
            "wave": ["right_wrist.x > 1", "right_wrist.x < 0.3"],
        },
        "bindings": ["up -> a", "lean -> lx", "up -> left_y=-0.5", "wave -> key:space",
                     {"when": "nose.y < 0", "button": "B", "mode": "tap"}],
    }, tmp_path)
    assert isinstance(p.gestures["up"], ExprGesture)
    assert p.gestures["lean"].analog
    assert isinstance(p.gestures["wave"], SequenceGesture)
    targets = [b.target for b in p.bindings]
    assert targets == ["button A", "axis left_x", "axis left_y", "key space", "button B"]
    assert p.bindings[2].value == -0.5
    assert p.bindings[4].gesture in p.gestures
    assert p.needs_keyboard and p.needs_gamepad


def test_errors_are_collected_with_locations(tmp_path):
    with pytest.raises(ConfigError) as ei:
        parse({
            "gestur": {},
            "gestures": {"up": "rigth_wrist.y > 0", "ok": "nose.y > 0"},
            "bindings": ["ok -> Q", "nope -> A", {"gesture": "ok", "button": "A", "mdoe": "tap"}],
        }, tmp_path)
    text = str(ei.value)
    assert "unknown section 'gestur'" in text and "did you mean 'gestures'" in text
    assert "gestures.up" in text and "right_wrist" in text
    assert "bindings[0]: unknown target 'Q'" in text
    assert "bindings[1]: unknown gesture 'nope'" in text
    assert "bindings[2]" in text and "'mode'" in text


def test_recorded_poses_become_gestures(tmp_path):
    (tmp_path / "poses").mkdir()
    (tmp_path / "poses" / "t_pose.json").write_text(
        '{"name": "t_pose", "joints": {"left_wrist": [-1.9, 0], "right_wrist": [1.9, 0]}}')
    p = parse({"bindings": ["t_pose -> Y"],
               "gestures": {"strict": {"template": "t_pose", "tolerance": 0.1}}}, tmp_path)
    assert isinstance(p.gestures["t_pose"], TemplateGesture)
    assert p.gestures["strict"].tolerance == 0.1


def test_missing_template_explains_how_to_record(tmp_path):
    with pytest.raises(ConfigError, match="posepad record t_pose"):
        parse({"gestures": {"t": {"template": "t_pose"}}}, tmp_path)
