"""
Screen capture module.
Takes a screenshot of the specified monitor and returns it as a base64-encoded PNG.
The image is downscaled to reduce LLM token usage.
"""

import base64
import io
from typing import Optional

import mss
import mss.tools
from PIL import Image


class ScreenCapture:
    MAX_WIDTH = 896  # pixels — models internally resize anyway; 896 saves tokens

    def __init__(self, config):
        self.config = config

    def get_monitor_offset(self) -> tuple[int, int]:
        """Return the (left, top) pixel offset of the configured monitor."""
        monitor_num: int = int(self.config.get("screenshots", "monitor") or 1)
        with mss.mss() as sct:
            monitors = sct.monitors
            idx = monitor_num if monitor_num < len(monitors) else 1
            m = monitors[idx]
            return m["left"], m["top"]

    def capture(self, max_width: Optional[int] = None) -> str:
        """
        Capture the configured monitor.
        Returns a base64-encoded JPEG string ready for embedding in LLM requests.

        max_width — override the default MAX_WIDTH.
                    Pass 0 for no downscaling (full native resolution).
                    Useful for OCR which is free and needs every pixel.
        """
        monitor_num: int = int(self.config.get("screenshots", "monitor") or 1)
        target_width = max_width if max_width is not None else self.MAX_WIDTH

        with mss.mss() as sct:
            monitors = sct.monitors
            # monitors[0] is the "all monitors" virtual screen; monitors[1] is first real monitor
            idx = monitor_num if monitor_num < len(monitors) else 1
            screenshot = sct.grab(monitors[idx])

        img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")

        if target_width > 0 and img.width > target_width:
            ratio = target_width / img.width
            img = img.resize((target_width, int(img.height * ratio)), Image.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=75, optimize=True)
        return base64.b64encode(buf.getvalue()).decode("ascii")
