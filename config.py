import json
from pathlib import Path
from typing import Any

DEFAULT_CONFIG = {
    "ai_companion": {
        "companion_name": "",
        "personality": "",
        "target_player": "",
        "temperature": 0.7,
        "max_history": 50,
    },
    "openrouter": {
        "api_key": "",
        "model": "openai/gpt-4.1",
        "base_url": "https://openrouter.ai/api/v1",
    },
    "xtts": {
        "provider": "xtts",  # "xtts" | "elevenlabs"
        "server_url": "http://localhost:8020",
        "endpoint": "/tts_to_audio/",
        "speaker_wav": "",
        "language": "ru",
        "temperature": 0.7,
    },
    "elevenlabs": {
        "api_key": "",
        "voice_id": "",
        "model": "eleven_flash_v2_5",
    },
    "whisper": {
        "model": "base",
        "language": "ru",
        "device": "cpu",
    },
    "audio": {
        "input_device": None,
        "output_device": None,
        "sample_rate": 16000,
        "vad_threshold": 0.015,
        "silence_duration": 1.8,
        "pre_speech_buffer": 0.5,
    },
    "screenshots": {
        "enabled": True,
        "monitor": 1,
    },
    "osc": {
        "host": "127.0.0.1",
        "port": 9000,
    },
    "movement": {
        "mode": "stay",              # stay | look_at | follow
        "tracker": "llm",            # "llm" | "grounding"
        "model": "google/gemini-2.0-flash-001",
        "model_look_at": "",     # cheap model — only needs left/center/right
        "model_follow":  "",     # strong model — needs height measurement
        "interval": 1.0,             # seconds between scan ticks
        "scan_turn_duration": 0.6,   # seconds per 45° scan rotation
        "stop_distance": "close",    # close | far
        "appearance": "",            # optional avatar appearance description for LLM
    },
}


class Config:
    def __init__(self, path: str = "config.json"):
        self.path = Path(path)
        self.data: dict = {}
        self._deep_copy(DEFAULT_CONFIG, self.data)
        self.load()

    def _deep_copy(self, src: dict, dst: dict):
        for key, value in src.items():
            if isinstance(value, dict):
                dst[key] = {}
                self._deep_copy(value, dst[key])
            else:
                dst[key] = value

    def _merge(self, base: dict, update: dict):
        for key, value in update.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._merge(base[key], value)
            else:
                base[key] = value

    def load(self):
        if self.path.exists():
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                self._merge(self.data, saved)
            except Exception as e:
                print(f"Config load error: {e}")

    def save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def update(self, data: dict):
        self._merge(self.data, data)

    def to_dict(self) -> dict:
        return self.data

    def get(self, *keys, default=None) -> Any:
        current = self.data
        for key in keys:
            if isinstance(current, dict):
                current = current.get(key, default)
                if current is default:
                    return default
            else:
                return default
        return current
