"""Live preview window: skeleton, gesture states, controller output."""

from __future__ import annotations

import numpy as np

from .bindings import ControllerState
from .gestures import GestureState, SequenceGesture
from .landmarks import LANDMARK_INDEX, SKELETON_EDGES, RawPose

GREEN = (80, 220, 80)
GREY = (140, 140, 140)
DIM = (90, 90, 90)
WHITE = (240, 240, 240)
AMBER = (0, 190, 255)
RED = (60, 60, 230)


class Overlay:
    def __init__(self, mirror: bool = True, title: str = "posepad"):
        import cv2
        self.cv2 = cv2
        self.mirror = mirror
        self.title = title
        cv2.namedWindow(title, cv2.WINDOW_NORMAL)

    def _text(self, img, text, org, color=WHITE, scale=0.5, thick=1):
        cv = self.cv2
        cv.putText(img, text, org, cv.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), thick + 2, cv.LINE_AA)
        cv.putText(img, text, org, cv.FONT_HERSHEY_SIMPLEX, scale, color, thick, cv.LINE_AA)

    def draw(self, bgr: np.ndarray, raw: RawPose | None, states: dict[str, GestureState],
             gestures: dict, out: ControllerState, status: list[tuple[str, tuple]],
             watch: list[tuple[str, object]]) -> np.ndarray:
        cv = self.cv2
        img = cv.flip(bgr, 1) if self.mirror else bgr.copy()
        h, w = img.shape[:2]

        if raw is not None:
            def px(name):
                x, y = raw.points[LANDMARK_INDEX[name], :2]
                if self.mirror:
                    x = 1 - x
                return int(x * w), int(y * h)
            for a, b in SKELETON_EDGES:
                if min(raw.visibility[LANDMARK_INDEX[a]], raw.visibility[LANDMARK_INDEX[b]]) > 0.5:
                    cv.line(img, px(a), px(b), (255, 200, 80), 2, cv.LINE_AA)
            for name in ("nose", "left_wrist", "right_wrist", "left_ankle", "right_ankle"):
                if raw.visibility[LANDMARK_INDEX[name]] > 0.5:
                    cv.circle(img, px(name), 5, (255, 255, 255), -1, cv.LINE_AA)

        y = 22
        for line, color in status:
            self._text(img, line, (10, y), color, 0.55)
            y += 22
        y += 6
        for name, st in states.items():
            if name.startswith("_"):
                continue
            g = gestures[name]
            color = GREEN if st.active else (GREY if st.tracked else DIM)
            label = name
            if g.analog:
                label += f"  {st.value:+.2f}"
            elif isinstance(g, SequenceGesture) and g.progress:
                label += f"  [{g.progress}/{len(g.steps)}]"
            elif hasattr(g, "tolerance"):
                label += f"  {st.value:.0%}"
            if not st.tracked:
                label += "  (not visible)"
            self._text(img, ("* " if st.active else "  ") + label, (10, y), color)
            y += 18
            if y > h - 10:
                break

        y = h - 12
        for src, val in reversed(watch):
            shown = "--" if val is None else (f"{val:+.3f}" if isinstance(val, float) else str(val))
            self._text(img, f"{src} = {shown}", (10, y), AMBER)
            y -= 18

        self._draw_pad(img, out)
        return img

    def _draw_pad(self, img, out: ControllerState) -> None:
        cv = self.cv2
        h, w = img.shape[:2]
        for i, (xa, ya) in enumerate((("left_x", "left_y"), ("right_x", "right_y"))):
            cx, cy, r = w - 150 + i * 80, 50, 30
            cv.circle(img, (cx, cy), r, WHITE, 1, cv.LINE_AA)
            dx, dy = out.axes[xa], out.axes[ya]
            cv.circle(img, (int(cx + dx * r), int(cy - dy * r)), 6,
                      GREEN if dx or dy else GREY, -1, cv.LINE_AA)
        for i, t in enumerate(("lt", "rt")):
            x0, y0 = w - 150 + i * 80 - 30, 92
            cv.rectangle(img, (x0, y0), (x0 + 60, y0 + 8), WHITE, 1)
            cv.rectangle(img, (x0, y0), (x0 + int(60 * out.axes[t]), y0 + 8), GREEN, -1)
        pressed = sorted(out.buttons) + [f"[{k}]" for k in sorted(out.keys)]
        self._text(img, " ".join(pressed), (w - 190, 125), GREEN, 0.55)

    def show(self, img) -> int:
        self.cv2.imshow(self.title, img)
        return self.cv2.waitKey(1) & 0xFF

    def close(self) -> None:
        self.cv2.destroyWindow(self.title)


__all__ = ["Overlay", "GREEN", "GREY", "AMBER", "RED", "WHITE"]
