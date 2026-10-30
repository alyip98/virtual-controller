"""A tiny, safe expression language for describing poses and movements.

Expressions are ordinary Python syntax restricted to arithmetic, comparisons,
``and``/``or``/``not``, ``x if c else y`` and a fixed set of functions::

    left_wrist.y > head.y and right_wrist.y > head.y
    angle(right_shoulder, right_elbow, right_wrist) > 150
    clamp(-shoulder_mid.dx * 2, -1, 1)
    punch and not block            # other gestures by name

The AST is validated against a whitelist before anything is compiled, and
evaluation runs with no builtins, so profiles cannot execute arbitrary code.
"""

from __future__ import annotations

import ast
import difflib
import math
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from .landmarks import ALL_POINTS, Point

POINT_ATTRS = {"x", "y", "z", "vx", "vy", "vz", "dx", "dy", "dz", "speed", "visibility", "visible"}


class ExpressionError(ValueError):
    pass


class Missing(Exception):
    """Raised during evaluation when a referenced landmark is not visible."""


def _pt(p: Any) -> Point:
    if not isinstance(p, Point):
        raise ExpressionError(f"expected a body point, got {p!r}")
    return p


def angle(a: Point, b: Point, c: Point) -> float:
    """Angle at ``b`` in degrees (2D, in the image plane). 180 = straight limb."""
    a, b, c = _pt(a), _pt(b), _pt(c)
    v1 = (a.x - b.x, a.y - b.y)
    v2 = (c.x - b.x, c.y - b.y)
    n = math.hypot(*v1) * math.hypot(*v2)
    if n < 1e-9:
        return 0.0
    cos = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / n))
    return math.degrees(math.acos(cos))


def direction(a: Point, b: Point) -> float:
    """Direction from ``a`` to ``b`` in degrees: 0 = player's right, 90 = up."""
    a, b = _pt(a), _pt(b)
    return math.degrees(math.atan2(b.y - a.y, b.x - a.x))


def dist(a: Point, b: Point) -> float:
    a, b = _pt(a), _pt(b)
    return math.hypot(a.x - b.x, a.y - b.y)


def dist3(a: Point, b: Point) -> float:
    a, b = _pt(a), _pt(b)
    return math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2 + (a.z - b.z) ** 2)


def clamp(v: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def remap(v: float, in_lo: float, in_hi: float, out_lo: float = 0.0, out_hi: float = 1.0) -> float:
    """Linearly map ``v`` from [in_lo, in_hi] to [out_lo, out_hi], clamped."""
    if in_hi == in_lo:
        return out_lo
    t = max(0.0, min(1.0, (v - in_lo) / (in_hi - in_lo)))
    return out_lo + t * (out_hi - out_lo)


def deadzone(v: float, dz: float) -> float:
    if abs(v) <= dz:
        return 0.0
    return math.copysign((abs(v) - dz) / (1.0 - dz), v) if dz < 1 else 0.0


def between(v: float, lo: float, hi: float) -> bool:
    return lo <= v <= hi


FUNCTIONS: dict[str, Callable[..., Any]] = {
    "angle": angle, "direction": direction, "dist": dist, "dist3": dist3,
    "clamp": clamp, "remap": remap, "deadzone": deadzone, "between": between,
    "abs": abs, "min": min, "max": max, "sqrt": math.sqrt,
    "sign": lambda v: (v > 0) - (v < 0),
}
CONSTANTS = {"pi": math.pi, "true": True, "false": False}

_ALLOWED_NODES = (
    ast.Expression, ast.BoolOp, ast.And, ast.Or, ast.UnaryOp, ast.Not, ast.USub, ast.UAdd,
    ast.BinOp, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.Pow, ast.FloorDiv,
    ast.Compare, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
    ast.IfExp, ast.Call, ast.Name, ast.Load, ast.Attribute, ast.Constant,
)


class Expression:
    """A validated, compiled expression.

    ``names`` lists the free identifiers (points, gestures, ``held``...) so the
    config loader can report typos and gesture dependency cycles up front.
    """

    def __init__(self, source: str, extra_names: Iterable[str] = ()):
        self.source = str(source).strip()
        try:
            tree = ast.parse(self.source, mode="eval")
        except SyntaxError as e:
            raise ExpressionError(f"syntax error in {self.source!r}: {e.msg}") from None
        self.points: set[str] = set()
        self.names: set[str] = set()
        known = set(ALL_POINTS) | set(extra_names) | set(CONSTANTS)
        for node in ast.walk(tree):
            self._check(node, known)
        self._code = compile(tree, f"<{self.source}>", "eval")

    def _check(self, node: ast.AST, known: set[str]) -> None:
        if not isinstance(node, _ALLOWED_NODES):
            raise ExpressionError(f"{type(node).__name__} is not allowed in {self.source!r}")
        if isinstance(node, ast.Constant) and not isinstance(node.value, (int, float, bool)):
            raise ExpressionError(f"only numbers are allowed as constants in {self.source!r}")
        if isinstance(node, ast.Attribute):
            if not isinstance(node.value, ast.Name):
                raise ExpressionError(f"attributes are only allowed on body points ({self.source!r})")
            if node.value.id not in ALL_POINTS:
                raise ExpressionError(f"unknown body point {node.value.id!r} in {self.source!r}"
                                      f"{_suggest(node.value.id, ALL_POINTS)}")
            if node.attr not in POINT_ATTRS:
                raise ExpressionError(
                    f"unknown attribute .{node.attr} in {self.source!r}"
                    f"{_suggest(node.attr, POINT_ATTRS)}; use one of {', '.join(sorted(POINT_ATTRS))}")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS:
                fname = getattr(node.func, "id", "?")
                raise ExpressionError(f"unknown function {fname}() in {self.source!r}"
                                      f"{_suggest(fname, FUNCTIONS)}")
            if node.keywords:
                raise ExpressionError(f"keyword arguments are not supported in {self.source!r}")
        if isinstance(node, ast.Name) and node.id not in FUNCTIONS:
            if node.id not in known:
                raise ExpressionError(f"unknown name {node.id!r} in {self.source!r}"
                                      f"{_suggest(node.id, known)}")
            if node.id in ALL_POINTS:
                self.points.add(node.id)
            elif node.id not in CONSTANTS:
                self.names.add(node.id)

    def evaluate(self, scope: Mapping[str, Any]) -> Any:
        """Evaluate against ``scope``; raises :class:`Missing` if a point is hidden."""
        try:
            return eval(self._code, {"__builtins__": {}}, _Scope(scope))  # noqa: S307 - whitelisted AST
        except (ZeroDivisionError, ValueError, OverflowError, TypeError) as e:
            raise ExpressionError(f"error evaluating {self.source!r}: {e}") from None

    def __repr__(self) -> str:
        return f"Expression({self.source!r})"


class _Scope(dict):
    """Lazy lookup: functions, constants, then the caller's mapping."""

    def __init__(self, inner: Mapping[str, Any]):
        super().__init__()
        self.inner = inner

    def __missing__(self, key: str) -> Any:
        if key in FUNCTIONS:
            return FUNCTIONS[key]
        if key in CONSTANTS:
            return CONSTANTS[key]
        return self.inner[key]

    def __getitem__(self, key: str) -> Any:
        if dict.__contains__(self, key):
            return dict.__getitem__(self, key)
        return self.__missing__(key)


def _suggest(word: str, options: Iterable[str]) -> str:
    match = difflib.get_close_matches(word, list(options), n=1)
    return f" (did you mean {match[0]!r}?)" if match else ""
