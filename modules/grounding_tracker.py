"""
Grounding DINO — zero-shot object detection by text description.
Finds the player's avatar by appearance without OCR or LLM API.

Install:
  pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
  pip install transformers>=4.38.0

Model (~700 MB) is downloaded automatically on first run.
"""

import base64
import io
from typing import Optional

import numpy as np
from PIL import Image

try:
    import torch
    from transformers import AutoProcessor, AutoModelForZeroShotObjectDetection
    _GDINO_OK = True
except ImportError:
    _GDINO_OK = False


class GroundingTracker:
    MODEL_ID  = "IDEA-Research/grounding-dino-base"
    BOX_THRESHOLD  = 0.40
    TEXT_THRESHOLD = 0.25

    def __init__(self, threshold: float = 0.40):
        self.BOX_THRESHOLD = threshold
        self._model     = None
        self._processor = None
        self._device    = None

        if not _GDINO_OK:
            print("[GDino] transformers or torch not installed.", flush=True)
            return

        try:
            self._device = "cuda" if torch.cuda.is_available() else "cpu"
            print(f"[GDino] Loading {self.MODEL_ID} on {self._device}...", flush=True)
            self._processor = AutoProcessor.from_pretrained(self.MODEL_ID)
            self._model = (
                AutoModelForZeroShotObjectDetection
                .from_pretrained(self.MODEL_ID)
                .to(self._device)
            )
            self._model.eval()
            print(f"[GDino] Ready on {self._device}.", flush=True)
        except Exception as e:
            print(f"[GDino] Init failed: {e}", flush=True)

    @property
    def available(self) -> bool:
        return self._model is not None

    def find_player(self, screenshot_b64: str, appearance: str) -> Optional[dict]:
        """
        Find avatar by appearance description.

        Returns:
            {"position": "left"|"center"|"right", "pct": int,
             "x_center": float, "y_center": float, "img_width": int}
            or None if not found.
        """
        if not self.available or not appearance.strip():
            return None

        try:
            raw = base64.b64decode(screenshot_b64)
            img = Image.open(io.BytesIO(raw)).convert("RGB")
            img_w, img_h = img.size

            text = appearance.strip().rstrip(".") + "."

            inputs = self._processor(
                images=img, text=text, return_tensors="pt"
            ).to(self._device)

            with torch.no_grad():
                outputs = self._model(**inputs)

            # post_process API changed across transformers versions —
            # call without threshold params and filter manually
            results = self._processor.post_process_grounded_object_detection(
                outputs,
                inputs.input_ids,
                target_sizes=[img.size[::-1]],  # (height, width)
            )[0]

            boxes  = results["boxes"]
            scores = results["scores"]

            # Apply thresholds manually
            mask   = scores >= self.BOX_THRESHOLD
            boxes  = boxes[mask]
            scores = scores[mask]

            if not len(boxes):
                return None

            best  = int(scores.argmax())
            score = float(scores[best])
            x1, y1, x2, y2 = boxes[best].tolist()

            box_w = x2 - x1
            box_h = y2 - y1
            x_c   = x1 + box_w / 2
            y_c   = y1 + box_h / 2
            pct   = int(round(box_h / img_h * 100))

            third = img_w / 3
            if x_c < third:       pos = "left"
            elif x_c > 2 * third: pos = "right"
            else:                  pos = "center"

            print(f"[GDino] Found — score={score:.2f} pos={pos} pct={pct}%", flush=True)
            return {"position": pos, "pct": pct,
                    "x_center": x_c, "y_center": y_c, "img_width": img_w}

        except Exception as e:
            print(f"[GDino] find_player error: {e}", flush=True)
            return None
