"""macOS permission checks.

macOS attributes privacy permissions to the app that launched Python (Terminal,
iTerm, VS Code...), not to posepad itself, and denied permissions usually fail
silently - key presses go nowhere, the camera returns no frames.  These helpers
turn that into a clear message.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import sys

SETTINGS = "System Settings > Privacy & Security"


def accessibility_trusted() -> bool | None:
    """Whether this process may post keyboard events; ``None`` if it cannot be checked."""
    if sys.platform != "darwin":
        return None
    try:
        lib = ctypes.cdll.LoadLibrary(ctypes.util.find_library("ApplicationServices"))
        lib.AXIsProcessTrusted.restype = ctypes.c_bool
        return bool(lib.AXIsProcessTrusted())
    except (OSError, AttributeError, TypeError):
        return None


def accessibility_help() -> str:
    return (f"macOS has not allowed this terminal to send key presses. Open {SETTINGS} > "
            "Accessibility, enable the app you run posepad from (Terminal, iTerm, VS Code...), "
            "then restart it.")


def camera_help() -> str:
    return (f"If macOS denied camera access, open {SETTINGS} > Camera, enable the app you run "
            "posepad from, then restart it. The first run may only show the permission prompt.")
