"""Screenshot capture and coordinate scaling for Windows.

Handles DPI awareness, scaling to fit model image limits,
and coordinate conversion between screenshot space and real screen space.
"""

from __future__ import annotations

import base64
import ctypes
import math
from io import BytesIO

import mss
from PIL import Image

from dulle.config import Settings


def enable_dpi_awareness():
    """Make this process DPI-aware on Windows.

    MUST be called once at startup, before any screen capture.
    Without this, screenshots on scaled displays (125%, 150%) are
    blurry and coordinates are wrong.
    """
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # Per-monitor DPI aware
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()  # Fallback
        except (AttributeError, OSError):
            pass  # Not on Windows or not available


class ScreenCapture:
    """Captures the Windows screen and scales for LLM consumption."""

    def __init__(self, settings: Settings | None = None):
        s = settings or Settings()
        self.max_long_edge = s.max_long_edge
        self.max_total_pixels = s.max_total_pixels
        self.fmt = s.screenshot_format
        self.jpeg_quality = s.jpeg_quality

        self.sct = mss.mss()
        monitor = self.sct.monitors[1]  # Primary monitor
        self.screen_width: int = monitor["width"]
        self.screen_height: int = monitor["height"]
        self.scale: float = self._compute_scale()

        # The dimensions Claude sees (what it bases coordinates on)
        self.scaled_width = int(self.screen_width * self.scale)
        self.scaled_height = int(self.screen_height * self.scale)

    # ── Public API ───────────────────────────────────────────────

    def capture(self) -> str:
        """Capture full screen, scale, return base64-encoded image."""
        raw = self.sct.grab(self.sct.monitors[1])
        img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
        img = img.resize((self.scaled_width, self.scaled_height), Image.LANCZOS)
        return self._encode(img)

    def capture_region(self, x0: int, y0: int, x1: int, y1: int) -> str:
        """Capture a screen region (coordinates in Claude's scaled space)."""
        rx0, ry0 = self.to_screen(x0, y0)
        rx1, ry1 = self.to_screen(x1, y1)

        # Clamp to screen bounds
        rx0 = max(0, min(rx0, self.screen_width))
        ry0 = max(0, min(ry0, self.screen_height))
        rx1 = max(0, min(rx1, self.screen_width))
        ry1 = max(0, min(ry1, self.screen_height))

        region = {
            "left": rx0, "top": ry0,
            "width": max(1, rx1 - rx0),
            "height": max(1, ry1 - ry0),
        }
        raw = self.sct.grab(region)
        img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
        # Scale region to fit within the same image limits
        img.thumbnail((self.scaled_width, self.scaled_height), Image.LANCZOS)
        return self._encode(img)

    def to_screen(self, x: int, y: int) -> tuple[int, int]:
        """Convert coordinates from Claude's space → real screen pixels."""
        return (int(x / self.scale), int(y / self.scale))

    def to_scaled(self, x: int, y: int) -> tuple[int, int]:
        """Convert coordinates from real screen → Claude's space."""
        return (int(x * self.scale), int(y * self.scale))

    def make_image_block(self, b64_data: str) -> dict:
        """Build an image content block for the API."""
        media = "image/png" if self.fmt == "png" else "image/jpeg"
        return {
            "type": "image",
            "source": {"type": "base64", "media_type": media, "data": b64_data},
        }

    @property
    def info(self) -> dict:
        """Screen info for system prompts."""
        return {
            "screen_width": self.screen_width,
            "screen_height": self.screen_height,
            "scaled_width": self.scaled_width,
            "scaled_height": self.scaled_height,
            "scale_factor": round(self.scale, 4),
        }

    # ── Internal ─────────────────────────────────────────────────

    def _compute_scale(self) -> float:
        w, h = self.screen_width, self.screen_height
        long_edge = max(w, h)
        total_pixels = w * h
        long_edge_scale = self.max_long_edge / long_edge
        total_pixels_scale = math.sqrt(self.max_total_pixels / total_pixels)
        return min(1.0, long_edge_scale, total_pixels_scale)

    def _encode(self, img: Image.Image) -> str:
        buf = BytesIO()
        if self.fmt == "jpeg":
            img.save(buf, format="JPEG", quality=self.jpeg_quality)
        else:
            img.save(buf, format="PNG", optimize=True)
        return base64.standard_b64encode(buf.getvalue()).decode("ascii")
