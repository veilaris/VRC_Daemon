"""
VRChat AI Bot — FastAPI server.
Run with:  python main.py
Web UI at: http://localhost:8080
"""

import asyncio
import logging
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)-32s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)

import uvicorn
from fastapi import Body, FastAPI, File, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from config import Config
from modules.audio import list_audio_devices
from modules.bot import VRChatBot

config = Config()
bot = VRChatBot(config)
_bot_task: asyncio.Task | None = None
_overlay_proc: subprocess.Popen | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await bot.stop()


app = FastAPI(title="VRChat AI Bot", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")


# ------------------------------------------------------------------ #
#  Pages                                                              #
# ------------------------------------------------------------------ #

@app.get("/", response_class=HTMLResponse)
async def root():
    return Path("static/index.html").read_text(encoding="utf-8")


# ------------------------------------------------------------------ #
#  Settings                                                           #
# ------------------------------------------------------------------ #

@app.get("/api/settings")
async def get_settings():
    return JSONResponse(config.to_dict())


@app.post("/api/settings")
async def save_settings(data: dict = Body(...)):
    config.update(data)
    config.save()
    bot.reload_config()
    return {"status": "ok"}


# ------------------------------------------------------------------ #
#  Bot control                                                        #
# ------------------------------------------------------------------ #

@app.post("/api/bot/start")
async def start_bot():
    global _bot_task
    if bot.running:
        return {"status": "already_running"}
    _bot_task = asyncio.create_task(bot.start())
    return {"status": "starting"}


@app.post("/api/bot/stop")
async def stop_bot():
    await bot.stop()
    if _bot_task and not _bot_task.done():
        _bot_task.cancel()
    return {"status": "stopped"}


@app.get("/api/bot/status")
async def bot_status():
    return {"running": bot.running, "status": bot.status}


# ------------------------------------------------------------------ #
#  Memory                                                             #
# ------------------------------------------------------------------ #

@app.post("/api/chat")
async def chat_text(data: dict = Body(...)):
    """Send a text message to the bot directly (bypasses STT)."""
    import threading
    text: str = (data.get("text") or "").strip()
    if not text:
        return {"status": "empty"}
    if not bot.running:
        return {"status": "bot_not_running"}
    threading.Thread(target=bot.process_text_input, args=(text,), daemon=True).start()
    return {"status": "ok"}


@app.post("/api/memory/clear")
async def clear_memory():
    bot.memory.clear()
    return {"status": "ok"}


@app.get("/api/memory")
async def get_memory():
    return {"messages": bot.memory.get_all()}


@app.delete("/api/memory/message/{index}")
async def delete_memory_message(index: int):
    bot.memory.delete_message(index)
    return {"status": "ok"}


@app.get("/api/longterm")
async def get_longterm():
    return {"content": bot.long_term_memory.load()}


@app.post("/api/longterm")
async def save_longterm(data: dict = Body(...)):
    content: str = data.get("content", "")
    try:
        bot.long_term_memory.path.write_text(content, encoding="utf-8")
        return {"status": "ok"}
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------------------ #
#  Audio devices                                                      #
# ------------------------------------------------------------------ #

@app.get("/api/audio/devices")
async def get_audio_devices():
    return list_audio_devices()


# ------------------------------------------------------------------ #
#  TTS test                                                           #
# ------------------------------------------------------------------ #

@app.post("/api/tts/test")
async def test_tts(data: dict = Body(...)):
    """Test TTS with parameters from UI (no need to save settings first)."""
    import io
    import numpy as np
    import requests as req_lib
    import sounddevice as sd
    import soundfile as sf

    text: str = data.get("text", "Привет! Это тест голоса.")
    provider: str = data.get("provider") or config.get("xtts", "provider") or "xtts"
    output_device = data.get("output_device") or config.get("audio", "output_device")

    def _play(audio, sr):
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
        import ctypes, threading
        dev = output_device if output_device != "" else None
        err: list = []
        def _do():
            ctypes.windll.ole32.CoInitialize(None)
            try:
                sd.play(audio, sr, device=dev)
                sd.wait()
            except Exception as e:
                err.append(e)
            finally:
                ctypes.windll.ole32.CoUninitialize()
        t = threading.Thread(target=_do, daemon=True)
        t.start()
        t.join()
        if err:
            raise err[0]

    def _do_xtts():
        server_url: str = data.get("server_url") or config.get("xtts", "server_url") or "http://localhost:8020"
        endpoint: str   = data.get("endpoint")   or config.get("xtts", "endpoint")    or "/tts_to_audio"
        speaker_wav: str = data.get("speaker_wav") or config.get("xtts", "speaker_wav") or ""
        language: str   = data.get("language")   or config.get("xtts", "language")    or "ru"
        temperature: float = float(data.get("temperature") or config.get("xtts", "temperature") or 0.7)
        payload: dict = {"text": text, "language": language, "temperature": temperature}
        if speaker_wav:
            payload["speaker_wav"] = speaker_wav
        r = req_lib.post(server_url.rstrip("/") + endpoint, json=payload, timeout=60)
        r.raise_for_status()
        audio, sr = sf.read(io.BytesIO(r.content), dtype="float32")
        if audio.ndim > 1:
            audio = audio[:, 0]
        _play(audio, sr)

    def _do_elevenlabs():
        api_key: str  = data.get("el_api_key")  or config.get("elevenlabs", "api_key")  or ""
        voice_id: str = data.get("el_voice_id") or config.get("elevenlabs", "voice_id") or ""
        model: str    = data.get("el_model")    or config.get("elevenlabs", "model")    or "eleven_flash_v2_5"
        if not api_key or not voice_id:
            raise ValueError("ElevenLabs api_key и voice_id обязательны")
        r = req_lib.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
            headers={"xi-api-key": api_key, "Content-Type": "application/json"},
            params={"output_format": "pcm_24000"},
            json={"text": text, "model_id": model},
            timeout=30,
        )
        r.raise_for_status()
        audio = np.frombuffer(r.content, dtype=np.int16).astype(np.float32) / 32768.0
        _play(audio, 24000)

    loop = asyncio.get_running_loop()
    try:
        if provider == "elevenlabs":
            await loop.run_in_executor(None, _do_elevenlabs)
        else:
            await loop.run_in_executor(None, _do_xtts)
        return {"status": "ok"}
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=str(e))



@app.get("/api/tts/speakers")
async def get_speakers():
    speakers = bot.tts.list_speakers()
    return {"speakers": speakers}


# ------------------------------------------------------------------ #
#  Overlay                                                            #
# ------------------------------------------------------------------ #

@app.post("/api/overlay/start")
async def overlay_start():
    global _overlay_proc
    if _overlay_proc and _overlay_proc.poll() is None:
        return {"status": "already_running"}
    _overlay_proc = subprocess.Popen([sys.executable, "overlay.py"])
    return {"status": "started"}


@app.post("/api/overlay/stop")
async def overlay_stop():
    global _overlay_proc
    if _overlay_proc and _overlay_proc.poll() is None:
        _overlay_proc.terminate()
        _overlay_proc = None
        return {"status": "stopped"}
    _overlay_proc = None
    return {"status": "not_running"}


@app.get("/api/overlay/status")
async def overlay_status():
    running = _overlay_proc is not None and _overlay_proc.poll() is None
    return {"running": running}


# ------------------------------------------------------------------ #
#  WebSocket for real-time UI updates                                 #
# ------------------------------------------------------------------ #

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    bot.add_ws_client(ws)
    # Send current state immediately
    await ws.send_text(
        '{"event":"bot_state","data":{"running":' + str(bot.running).lower() + "}}"
    )
    try:
        while True:
            await ws.receive_text()  # keep connection alive; we only push from server
    except WebSocketDisconnect:
        bot.remove_ws_client(ws)


# ------------------------------------------------------------------ #
#  Entry point                                                        #
# ------------------------------------------------------------------ #

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8080, log_level="info")
