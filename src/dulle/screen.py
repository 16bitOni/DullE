"""Shim — ScreenCapture has moved to dulle.execution.screen."""

from dulle.execution.screen import ScreenCapture, enable_dpi_awareness

__all__ = ["ScreenCapture", "enable_dpi_awareness"]
