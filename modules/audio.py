"""
Audio capture module with energy-based Voice Activity Detection.
Captures loopback audio (all PC sound) via sounddevice.
"""

import queue
import threading
import time
from typing import Callable, Optional

import numpy as np
import sounddevice as sd


def list_audio_devices() -> dict:
    """Return WASAPI-only devices — matches what Windows Sound Panel shows."""
    devices = sd.query_devices()
    hostapis = sd.query_hostapis()
    result = {"inputs": [], "outputs": []}
    for i, d in enumerate(devices):
        raw_api = hostapis[d["hostapi"]]["name"] if d["hostapi"] < len(hostapis) else ""
        if "WASAPI" not in raw_api:
            continue
        info = {
            "index": i,
            "name": d["name"],
            "api": "WASAPI",
            "label": f"[{i}] {d['name']}",
        }
        if d["max_input_channels"] > 0:
            result["inputs"].append(info)
        if d["max_output_channels"] > 0:
            result["outputs"].append(info)
    return result


def find_wdm_fallback(failed_index: int) -> Optional[int]:
    """
    If a device fails to open, find an alternative with the same base name.
    Tries WDM-KS first (lower latency), then MME (most compatible with
    virtual devices like VoiceMeeter which don't register WDM-KS endpoints).
    """
    devices = sd.query_devices()
    hostapis = sd.query_hostapis()
    base = devices[failed_index]["name"].split("(")[0].strip().lower()

    wdm_candidate: Optional[int] = None
    mme_candidate: Optional[int] = None

    for i, d in enumerate(devices):
        if i == failed_index:
            continue
        raw_api = hostapis[d["hostapi"]]["name"] if d["hostapi"] < len(hostapis) else ""
        if "WASAPI" in raw_api:
            continue
        if d["max_input_channels"] > 0 and d["name"].lower().startswith(base):
            if "WDM" in raw_api and wdm_candidate is None:
                wdm_candidate = i
            elif "MME" in raw_api and mme_candidate is None:
                mme_candidate = i

    return wdm_candidate if wdm_candidate is not None else mme_candidate


class AudioCapture:
    """
    Continuously captures audio from the selected input device.
    Uses simple RMS-based VAD to detect speech segments.
    Calls on_speech(audio_np_float32, sample_rate) when a segment ends.

    To prevent the bot from hearing its own TTS, set is_playing = True
    while TTS is playing — capture is paused during that time.
    """

    CHUNK_DURATION = 0.1  # seconds per chunk

    def __init__(self, config, on_speech: Callable):
        self.config = config
        self.on_speech = on_speech
        self.running = False
        self.is_playing = False  # mute flag during TTS playback

        self.sample_rate: int = config.get("audio", "sample_rate") or 16000
        self.vad_threshold: float = config.get("audio", "vad_threshold") or 0.015
        self.silence_duration: float = config.get("audio", "silence_duration") or 1.8
        self.pre_buffer_duration: float = config.get("audio", "pre_speech_buffer") or 0.5
        self.input_device = config.get("audio", "input_device")  # None = default

        self._chunk_size = int(self.sample_rate * self.CHUNK_DURATION)
        self._silence_chunks = int(self.silence_duration / self.CHUNK_DURATION)
        self._pre_buffer_size = int(self.pre_buffer_duration / self.CHUNK_DURATION)

        self._audio_queue: queue.Queue = queue.Queue()
        self._thread: Optional[threading.Thread] = None

    def start(self):
        self.running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True, name="AudioCapture")
        self._thread.start()

    def stop(self):
        self.running = False
        if self._thread:
            self._thread.join(timeout=3.0)

    @staticmethod
    def _rms(chunk: np.ndarray) -> float:
        return float(np.sqrt(np.mean(chunk ** 2)))

    @staticmethod
    def _to_mono_16k(audio: np.ndarray, native_sr: int, target_sr: int) -> np.ndarray:
        """Convert stereo → mono, then resample to target_sr if needed."""
        if audio.ndim > 1:
            audio = audio.mean(axis=1)  # stereo → mono
        if native_sr != target_sr:
            from math import gcd
            from scipy.signal import resample_poly
            g = gcd(native_sr, target_sr)
            audio = resample_poly(audio, target_sr // g, native_sr // g).astype(np.float32)
        return audio

    def _query_device_params(self, device) -> tuple[int, int]:
        """Return (native_sample_rate, native_channels) for the given device."""
        try:
            if device is not None:
                info = sd.query_devices(device)
            else:
                info = sd.query_devices(sd.default.device[0])
            native_sr = int(info["default_samplerate"])
            native_ch = max(1, min(int(info["max_input_channels"]), 2))
            print(f"[AudioCapture] Device: '{info['name']}' — {native_sr}Hz, {native_ch}ch")
            return native_sr, native_ch
        except Exception as e:
            print(f"[AudioCapture] Could not query device, using defaults: {e}")
            return self.sample_rate, 1

    def _capture_loop(self):
        pre_buffer = []
        speech_buffer = []
        silence_count = 0
        in_speech = False

        device = self.input_device if self.input_device is not None else None
        native_sr, native_ch = self._query_device_params(device)

        # Chunk size in frames at the native sample rate
        native_chunk = int(native_sr * self.CHUNK_DURATION)

        # VAD timing based on native rate
        silence_chunks = int(self.silence_duration / self.CHUNK_DURATION)
        pre_buffer_size = int(self.pre_buffer_duration / self.CHUNK_DURATION)

        def audio_callback(indata: np.ndarray, frames: int, time_info, status):
            if not self.is_playing:
                self._audio_queue.put(indata.copy())

        def _make_stream(dev, sr, ch):
            return sd.InputStream(
                device=dev, channels=ch, samplerate=sr,
                blocksize=int(sr * self.CHUNK_DURATION),
                dtype=np.float32, callback=audio_callback,
            )

        # Try opening; if it fails for a virtual device (e.g. VoiceMeeter WASAPI),
        # find a fallback (WDM-KS or MME) with the same device name.
        stream = None
        first_error: Optional[Exception] = None
        try:
            stream = _make_stream(device, native_sr, native_ch)
            stream.__enter__()
        except Exception as e:
            first_error = e
            stream = None

        if stream is None and device is not None:
            fallback = find_wdm_fallback(device)
            if fallback is not None:
                fallback_info = sd.query_devices(fallback)
                api_name = sd.query_hostapis(fallback_info["hostapi"])["name"]
                print(f"[AudioCapture] Primary device failed ({first_error}), "
                      f"retrying with {api_name} [{fallback}]")
                try:
                    device = fallback
                    native_sr, native_ch = self._query_device_params(device)
                    native_chunk = int(native_sr * self.CHUNK_DURATION)
                    stream = _make_stream(device, native_sr, native_ch)
                    stream.__enter__()
                except Exception as e2:
                    stream = None
                    print(f"[AudioCapture] Fallback also failed: {e2}")

        if stream is None:
            raise first_error

        try:
            print(f"[AudioCapture] Stream opened — {native_sr}Hz {native_ch}ch")
            while self.running:
                try:
                    chunk_raw = self._audio_queue.get(timeout=0.5)
                except queue.Empty:
                    continue

                # Convert to mono float32 (keep at native_sr for VAD)
                chunk_mono = chunk_raw.mean(axis=1) if chunk_raw.ndim > 1 else chunk_raw

                rms = self._rms(chunk_mono)


                if rms > self.vad_threshold:
                    if not in_speech:
                        in_speech = True
                        speech_buffer = list(pre_buffer)
                    speech_buffer.append(chunk_mono)
                    silence_count = 0
                else:
                    if in_speech:
                        silence_count += 1
                        speech_buffer.append(chunk_mono)
                        if silence_count >= silence_chunks:
                            audio_native = np.concatenate(speech_buffer)
                            # Resample to 16kHz for Whisper
                            audio_16k = self._to_mono_16k(audio_native, native_sr, self.sample_rate)
                            threading.Thread(
                                target=self.on_speech,
                                args=(audio_16k, self.sample_rate),
                                daemon=True,
                            ).start()
                            speech_buffer = []
                            in_speech = False
                            silence_count = 0
                    else:
                        pre_buffer.append(chunk_mono)
                        if len(pre_buffer) > pre_buffer_size:
                            pre_buffer.pop(0)

        except Exception as e:
            print(f"[AudioCapture] Error: {e}")
        finally:
            stream.__exit__(None, None, None)
