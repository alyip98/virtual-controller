"""Record raw landmarks to a file and replay them later.

Recording a few minutes of play lets you tune thresholds offline:
``posepad replay session.jsonl --profile my.yaml`` re-runs the gesture engine
on exactly the same movements.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import numpy as np

from .landmarks import RawPose


class SessionWriter:
    def __init__(self, path: str | Path, aspect: float):
        self.f = open(path, "w")
        self.f.write(json.dumps({"posepad_session": 1, "aspect": aspect}) + "\n")

    def write(self, t: float, raw: RawPose | None) -> None:
        rec: dict = {"t": round(t, 4)}
        if raw is not None:
            rec["p"] = np.round(raw.points, 4).tolist()
            rec["v"] = np.round(raw.visibility, 3).tolist()
        self.f.write(json.dumps(rec) + "\n")

    def close(self) -> None:
        self.f.close()


def read_session(path: str | Path) -> tuple[float, Iterator[tuple[float, RawPose | None]]]:
    lines = Path(path).read_text().splitlines()
    header = json.loads(lines[0])
    if "posepad_session" not in header:
        raise ValueError(f"{path} is not a posepad session file")

    def frames():
        for line in lines[1:]:
            rec = json.loads(line)
            t = rec["t"]
            if "p" in rec:
                yield t, RawPose(np.array(rec["p"]), np.array(rec["v"]), t)
            else:
                yield t, None
    return float(header.get("aspect", 1.0)), frames()
