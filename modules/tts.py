"""
TTS client — supports XTTS (local) and ElevenLabs (cloud).
Provider is selected via config: xtts.provider = "xtts" | "elevenlabs".
Plays audio through the configured output device.
"""

import hashlib
import io
import os
import re
import threading
from pathlib import Path
from typing import Callable, Optional, Tuple

import numpy as np
import requests
import sounddevice as sd
import soundfile as sf


class TTSClient:
    def __init__(self, config):
        self.config = config
        self._playing = False
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ #
    #  Cache helpers                                                       #
    # ------------------------------------------------------------------ #

    def _cache_dir(self) -> Path:
        """Return (and create) the cache directory for the current voice."""
        provider: str = self.config.get("xtts", "provider") or "xtts"
        if provider == "elevenlabs":
            voice_id: str = self.config.get("elevenlabs", "voice_id") or "default"
            speaker_id = f"elevenlabs_{voice_id[:24]}"
        else:
            speaker_wav: str = self.config.get("xtts", "speaker_wav") or ""
            if speaker_wav:
                speaker_id = "xtts_" + Path(speaker_wav).stem
            else:
                speaker_id = "xtts_default"
        d = Path("data/tts_cache") / speaker_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _cache_path(self, text: str) -> Path:
        """Return the WAV file path for a given text."""
        h = hashlib.md5(text.encode("utf-8")).hexdigest()[:8]
        slug = re.sub(r"[^\w]", "_", text.lower())[:28].strip("_")
        return self._cache_dir() / f"{h}_{slug}.wav"

    def _load_cache(self, text: str) -> Tuple[Optional[np.ndarray], int]:
        p = self._cache_path(text)
        if p.exists():
            try:
                audio, sr = sf.read(str(p), dtype="float32")
                if audio.ndim > 1:
                    audio = audio[:, 0]
                print(f"[TTS] Cache hit: {p.name}", flush=True)
                return audio, sr
            except Exception as e:
                print(f"[TTS] Cache read error: {e}", flush=True)
                p.unlink(missing_ok=True)
        return None, 0

    def _save_cache(self, text: str, audio: np.ndarray, sr: int):
        p = self._cache_path(text)
        try:
            sf.write(str(p), audio, sr)
            print(f"[TTS] Cached: {p.name}", flush=True)
        except Exception as e:
            print(f"[TTS] Cache write error: {e}", flush=True)

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    @property
    def is_playing(self) -> bool:
        return self._playing

    def speak(
        self,
        text: str,
        on_start: Optional[Callable] = None,
        on_complete: Optional[Callable] = None,
        _label: str = "",
    ) -> threading.Thread:
        """Synthesize text and play it asynchronously."""
        t = threading.Thread(
            target=self._synthesize_and_play,
            args=(text, on_start, on_complete),
            daemon=True,
        )
        t.start()
        return t

    def test_tts(self, text: str = "Привет! Это тест голоса.") -> bool:
        """Blocking test — returns True if audio was received and played."""
        audio, sr = self._synthesize(text)
        if audio is None:
            return False
        self._play_blocking(audio, sr)
        return True

    def list_speakers(self) -> list[str]:
        """Query the XTTS server for available speaker names."""
        server_url: str = self.config.get("xtts", "server_url") or "http://localhost:8020"
        try:
            r = requests.get(f"{server_url.rstrip('/')}/speakers_list", timeout=5)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            print(f"[TTS] Could not fetch speakers: {e}")
            return []

    # ------------------------------------------------------------------ #
    #  Synthesis routing                                                   #
    # ------------------------------------------------------------------ #

    def _synthesize(self, text: str) -> Tuple[Optional[np.ndarray], int]:
        from modules.commands import CACHED_PHRASES
        use_cache = text in CACHED_PHRASES

        if use_cache:
            audio, sr = self._load_cache(text)
            if audio is not None:
                return audio, sr

        provider: str = self.config.get("xtts", "provider") or "xtts"
        if provider == "elevenlabs":
            audio, sr = self._synthesize_elevenlabs(text)
        else:
            audio, sr = self._synthesize_xtts(text)

        if use_cache and audio is not None:
            self._save_cache(text, audio, sr)
        return audio, sr

    def _synthesize_xtts(self, text: str) -> Tuple[Optional[np.ndarray], int]:
        """Call local XTTS server. Returns (audio_float32, sample_rate) or (None, 0)."""
        server_url: str = self.config.get("xtts", "server_url") or "http://localhost:8020"
        endpoint: str = self.config.get("xtts", "endpoint") or "/tts_to_audio"
        url = server_url.rstrip("/") + endpoint

        payload = {
            "text": text,
            "language": self.config.get("xtts", "language") or "ru",
            "temperature": float(self.config.get("xtts", "temperature") or 0.7),
        }
        speaker_wav: str = self.config.get("xtts", "speaker_wav") or ""
        if speaker_wav:
            payload["speaker_wav"] = speaker_wav

        try:
            r = requests.post(url, json=payload, timeout=60)
            r.raise_for_status()
            audio, sr = sf.read(io.BytesIO(r.content), dtype="float32")
            if audio.ndim > 1:
                audio = audio[:, 0]
            return audio, sr
        except Exception as e:
            print(f"[TTS] XTTS error: {e}")
            return None, 0

    def _stream_elevenlabs(
        self,
        text: str,
        on_start: Optional[Callable],
        on_complete: Optional[Callable],
    ):
        """Stream ElevenLabs TTS — starts playback on first chunk."""
        import ctypes
        api_key: str = self.config.get("elevenlabs", "api_key") or ""
        voice_id: str = self.config.get("elevenlabs", "voice_id") or ""
        model: str    = self.config.get("elevenlabs", "model") or "eleven_flash_v2_5"
        output_device = self.config.get("audio", "output_device")

        if not api_key or not voice_id:
            print("[TTS] ElevenLabs: api_key or voice_id not configured", flush=True)
            if on_complete: on_complete()
            return

        # Pick PCM format closest to device native rate
        try:
            native_sr = int(sd.query_devices(output_device)["default_samplerate"])
        except Exception:
            native_sr = 24000
        src_sr = 24000
        output_format = "pcm_24000"

        print(f"[TTS] Synthesizing (stream): '{text[:60]}{'...' if len(text)>60 else ''}'", flush=True)

        try:
            resp = requests.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream",
                headers={"xi-api-key": api_key, "Content-Type": "application/json"},
                params={"output_format": output_format},
                json={"text": text, "model_id": model},
                stream=True,
                timeout=30,
            )
            resp.raise_for_status()
        except Exception as e:
            print(f"[TTS] ElevenLabs stream error: {e}", flush=True)
            if on_complete: on_complete()
            return

        # Resolve output device (prefer MME over WASAPI for compatibility)
        dev = output_device
        try:
            if sd.query_devices(dev)["hostapi"] == 2:  # WASAPI
                devices  = sd.query_devices()
                hostapis = sd.query_hostapis()
                base = devices[dev]["name"].split("(")[0].strip().lower()
                for i, d in enumerate(devices):
                    if i != dev and d["max_output_channels"] > 0:
                        api = hostapis[d["hostapi"]]["name"] if d["hostapi"] < len(hostapis) else ""
                        if "WASAPI" not in api and d["name"].lower().startswith(base):
                            dev = i
                            break
        except Exception:
            pass

        try:
            dev_sr = int(sd.query_devices(dev)["default_samplerate"])
        except Exception:
            dev_sr = src_sr

        started  = False
        leftover = b""
        ctypes.windll.ole32.CoInitialize(None)
        try:
            with sd.OutputStream(device=dev, samplerate=dev_sr, channels=1, dtype="float32") as stream:
                for chunk in resp.iter_content(chunk_size=4096):
                    if not chunk:
                        continue
                    data = leftover + chunk
                    trim = len(data) - (len(data) % 2)
                    leftover, data = data[trim:], data[:trim]
                    if not data:
                        continue
                    samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
                    if dev_sr != src_sr:
                        from math import gcd
                        from scipy.signal import resample_poly
                        g = gcd(src_sr, dev_sr)
                        samples = resample_poly(samples, dev_sr // g, src_sr // g).astype(np.float32)
                    if not started:
                        started = True
                        self._playing = True
                        print(f"[TTS] Streaming @ {dev_sr}Hz → device {dev!r}", flush=True)
                        if on_start: on_start()
                    stream.write(samples)
            print("[TTS] Stream done.", flush=True)
        except Exception as e:
            print(f"[TTS] Stream ERROR: {e}", flush=True)
        finally:
            self._playing = False
            if on_complete: on_complete()
            ctypes.windll.ole32.CoUninitialize()

    def _synthesize_elevenlabs(self, text: str) -> Tuple[Optional[np.ndarray], int]:
        """Call ElevenLabs API. Returns PCM float32 at 24000 Hz or (None, 0)."""
        api_key: str = self.config.get("elevenlabs", "api_key") or ""
        voice_id: str = self.config.get("elevenlabs", "voice_id") or ""
        model: str = self.config.get("elevenlabs", "model") or "eleven_flash_v2_5"

        if not api_key or not voice_id:
            print("[TTS] ElevenLabs: api_key or voice_id not configured")
            return None, 0

        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        try:
            r = requests.post(
                url,
                headers={"xi-api-key": api_key, "Content-Type": "application/json"},
                params={"output_format": "pcm_24000"},
                json={"text": text, "model_id": model},
                timeout=30,
            )
            r.raise_for_status()
            # Response is raw PCM: 16-bit signed mono at 24000 Hz
            audio = np.frombuffer(r.content, dtype=np.int16).astype(np.float32) / 32768.0
            return audio, 24000
        except Exception as e:
            print(f"[TTS] ElevenLabs error: {e}")
            return None, 0

    # ------------------------------------------------------------------ #
    #  Playback                                                            #
    # ------------------------------------------------------------------ #

    def _play_blocking(self, audio: np.ndarray, sr: int):
        output_device = self.config.get("audio", "output_device")
        # Resample to device native rate if needed (e.g. VoiceMeeter requires 48000 Hz)
        try:
            dev_info = sd.query_devices(output_device)
            native_sr = int(dev_info["default_samplerate"])
            if native_sr != sr:
                from math import gcd
                from scipy.signal import resample_poly
                g = gcd(sr, native_sr)
                audio = resample_poly(audio, native_sr // g, sr // g).astype(np.float32)
                sr = native_sr
        except Exception:
            pass
        print(f"[TTS] Playing {len(audio)/sr:.1f}s @ {sr}Hz → device {output_device!r}", flush=True)
        try:
            import ctypes, threading

            def _find_output_fallback(failed_index: int) -> Optional[int]:
                devices = sd.query_devices()
                hostapis = sd.query_hostapis()
                base = devices[failed_index]["name"].split("(")[0].strip().lower()
                for i, d in enumerate(devices):
                    if i == failed_index or d["max_output_channels"] == 0:
                        continue
                    api = hostapis[d["hostapi"]]["name"] if d["hostapi"] < len(hostapis) else ""
                    if "WASAPI" not in api and d["name"].lower().startswith(base):
                        return i
                return None

            def _try_play(device):
                try:
                    is_wasapi = sd.query_devices(device)["hostapi"] == 2
                except Exception:
                    is_wasapi = False
                extra = (sd.WasapiSettings(exclusive=False) if (is_wasapi and hasattr(sd, "WasapiSettings")) else None)
                err: list = []
                def _run():
                    ctypes.windll.ole32.CoInitialize(None)
                    try:
                        sd.play(audio, sr, device=device, extra_settings=extra)
                        sd.wait()
                    except Exception as e:
                        err.append(e)
                    finally:
                        ctypes.windll.ole32.CoUninitialize()
                t = threading.Thread(target=_run, daemon=True)
                t.start()
                t.join()
                if err:
                    raise err[0]

            try:
                _try_play(output_device)
            except Exception as e:
                fallback = _find_output_fallback(output_device) if isinstance(output_device, int) else None
                if fallback is not None:
                    fallback_name = sd.query_devices(fallback)["name"]
                    print(f"[TTS] Output fallback → [{fallback}] {fallback_name}", flush=True)
                    _try_play(fallback)
                else:
                    raise
            print("[TTS] Playback done.", flush=True)
        except Exception as e:
            print(f"[TTS] Playback ERROR: {e}", flush=True)

    def _synthesize_and_play(
        self,
        text: str,
        on_start: Optional[Callable],
        on_complete: Optional[Callable],
    ):
        provider: str = self.config.get("xtts", "provider") or "xtts"

        # ElevenLabs: use streaming path (lower latency)
        if provider == "elevenlabs":
            from modules.commands import CACHED_PHRASES
            if text in CACHED_PHRASES:
                audio, sr = self._load_cache(text)
                if audio is not None:
                    with self._lock:
                        self._playing = True
                        if on_start: on_start()
                        try:
                            self._play_blocking(audio, sr)
                        finally:
                            self._playing = False
                            if on_complete: on_complete()
                    return
            with self._lock:
                self._stream_elevenlabs(text, on_start, on_complete)
            return

        # XTTS: buffer full audio then play
        print(f"[TTS] Synthesizing: '{text[:60]}{'...' if len(text)>60 else ''}'", flush=True)
        audio, sr = self._synthesize(text)
        if audio is None:
            print("[TTS] Synthesis failed — no audio received", flush=True)
            if on_complete:
                on_complete()
            return

        with self._lock:
            self._playing = True
            if on_start:
                on_start()
            try:
                self._play_blocking(audio, sr)
            finally:
                self._playing = False
                if on_complete:
                    on_complete()
