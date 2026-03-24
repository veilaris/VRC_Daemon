"""
Speech-to-text module using faster-whisper (local inference).
"""

import numpy as np


class SpeechToText:
    MIN_AUDIO_SECONDS = 0.5  # ignore clips shorter than this

    def __init__(self, config):
        model_name: str = config.get("whisper", "model") or "base"
        device: str = config.get("whisper", "device") or "cpu"
        self.language: str = config.get("whisper", "language") or "ru"

        compute_type = "float32" if device == "cpu" else "float16"

        print(f"[STT] Loading Whisper model '{model_name}' on {device}...")
        from faster_whisper import WhisperModel
        self.model = WhisperModel(model_name, device=device, compute_type=compute_type)
        print("[STT] Whisper ready.")

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000) -> str:
        """
        Transcribe a float32 numpy audio array.
        Returns empty string if audio is too short or transcription failed.
        """
        if len(audio) < int(sample_rate * self.MIN_AUDIO_SECONDS):
            return ""

        # faster-whisper expects float32 mono at 16kHz
        if sample_rate != 16000:
            audio = self._resample(audio, sample_rate, 16000)

        try:
            segments, _info = self.model.transcribe(
                audio,
                language=self.language,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 300},
            )
            text = " ".join(seg.text for seg in segments).strip()
            return text
        except Exception as e:
            print(f"[STT] Transcription error: {e}")
            return ""

    @staticmethod
    def _resample(audio: np.ndarray, orig_rate: int, target_rate: int) -> np.ndarray:
        from scipy.signal import resample_poly
        from math import gcd
        g = gcd(orig_rate, target_rate)
        return resample_poly(audio, target_rate // g, orig_rate // g).astype(np.float32)
