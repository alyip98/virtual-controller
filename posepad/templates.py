"""Recorded pose templates: "do the pose, press a key, bind it"."""

from __future__ import annotations

import json
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .landmarks import POINT_INDEX, BodyFrame

JOINT_SETS: dict[str, tuple[str, ...]] = {
    "arms": ("left_elbow", "right_elbow", "left_wrist", "right_wrist"),
    "upper": ("left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
              "left_wrist", "right_wrist", "nose"),
    "lower": ("left_hip", "right_hip", "left_knee", "right_knee", "left_ankle", "right_ankle"),
}
JOINT_SETS["body"] = JOINT_SETS["upper"] + JOINT_SETS["lower"]
JOINT_SETS["left_arm"] = ("left_elbow", "left_wrist")
JOINT_SETS["right_arm"] = ("right_elbow", "right_wrist")


def resolve_joints(spec: str | Iterable[str]) -> tuple[str, ...]:
    """``"upper"`` / ``"arms,lower"`` / ``["left_wrist", ...]`` -> joint names."""
    items = spec.split(",") if isinstance(spec, str) else list(spec)
    out: list[str] = []
    for item in (i.strip() for i in items):
        if not item:
            continue
        if item in JOINT_SETS:
            out.extend(JOINT_SETS[item])
        elif item in POINT_INDEX:
            out.append(item)
        else:
            raise ValueError(f"unknown joint or joint set {item!r}; "
                             f"sets: {', '.join(JOINT_SETS)}")
    return tuple(dict.fromkeys(out))


@dataclass
class PoseTemplate:
    name: str
    joints: tuple[str, ...]
    positions: np.ndarray        # (len(joints), 2) in the body frame
    spread: float = 0.0          # how much the pose wobbled while recording

    @classmethod
    def from_frames(cls, name: str, frames: list[BodyFrame], joints: Iterable[str],
                    min_visibility: float = 0.5) -> PoseTemplate:
        if not frames:
            raise ValueError("no frames captured - was anyone in view?")
        joints = tuple(joints)
        idx = [POINT_INDEX[j] for j in joints]
        vis = np.array([f.visibility[idx] for f in frames]).mean(axis=0)
        keep = [j for j, v in zip(joints, vis) if v >= min_visibility]
        if not keep:
            raise ValueError("none of the requested joints were visible while recording")
        kidx = [POINT_INDEX[j] for j in keep]
        stack = np.array([f.positions[kidx, :2] for f in frames])
        mean = stack.mean(axis=0)
        spread = float(np.linalg.norm(stack - mean, axis=2).mean())
        return cls(name, tuple(keep), mean, spread)

    def error(self, frame: BodyFrame, min_visibility: float = 0.5) -> float | None:
        """Mean distance (shoulder widths) between the frame and the template.

        Hidden joints are skipped; ``None`` if more than half are hidden.
        """
        idx = np.array([POINT_INDEX[j] for j in self.joints])
        visible = frame.visibility[idx] >= min_visibility
        if visible.sum() * 2 < len(idx):
            return None
        d = np.linalg.norm(frame.positions[idx, :2] - self.positions, axis=1)
        return float(d[visible].mean())

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "name": self.name,
            "recorded": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "spread": round(self.spread, 4),
            "joints": {j: [round(float(x), 4), round(float(y), 4)]
                       for j, (x, y) in zip(self.joints, self.positions)},
        }
        path.write_text(json.dumps(data, indent=2) + "\n")

    @classmethod
    def load(cls, path: Path) -> PoseTemplate:
        data = json.loads(Path(path).read_text())
        joints = tuple(data["joints"])
        for j in joints:
            if j not in POINT_INDEX:
                raise ValueError(f"{path}: unknown joint {j!r}")
        pos = np.array([data["joints"][j] for j in joints], dtype=float).reshape(-1, 2)
        return cls(data.get("name", Path(path).stem), joints, pos, float(data.get("spread", 0.0)))
