"""Same physical-pixel coordinate context for capture and cursor placement."""
import ctypes
import math
from contextlib import contextmanager
from functools import wraps


@contextmanager
def physical_pixels(api):
    setter = api.SetThreadDpiAwarenessContext
    setter.argtypes = [ctypes.c_void_p]
    setter.restype = ctypes.c_void_p
    previous = setter(ctypes.c_void_p(-4))  # PER_MONITOR_AWARE_V2
    if not previous:
        raise RuntimeError("A fizikai pixel/DPI környezet nem állítható be; művelet tiltva")
    try:
        yield
    finally:
        if not setter(previous):
            raise RuntimeError("A szál DPI környezetének visszaállítása sikertelen")


def pixel_context(api_attribute):
    def decorate(fn):
        @wraps(fn)
        def call(self, *args, **kwargs):
            with physical_pixels(getattr(self, api_attribute)):
                return fn(self, *args, **kwargs)
        return call
    return decorate


def client_to_screen(x, y, width, height, left, top):
    if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in (x, y)) or not (0 <= x <= 1 and 0 <= y <= 1):
        raise ValueError("Érvénytelen normalizált klienskoordináta")
    if width <= 0 or height <= 0:
        raise ValueError("Üres kliensablak")
    # CV normalizes by width/height, not width-1/height-1. Clamp only endpoints.
    return left+min(width-1, round(x*width)), top+min(height-1, round((1-y)*height))
