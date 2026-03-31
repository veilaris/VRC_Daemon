"""
Main bot coordinator.
Wires together audio capture → STT → LLM → TTS → OSC.
Broadcasts events to connected WebSocket clients for the web UI.
"""

import asyncio
import json
import threading
import time
from typing import Optional, Set

from fastapi import WebSocket

from config import Config
from modules.audio import AudioCapture
from modules.llm import LLMClient
from modules.memory import ConversationMemory, LongTermMemory
from modules.movement import MovementController
from modules.osc import VRChatOSC
from modules.stt import SpeechToText
from modules.tts import TTSClient
from modules.vision import ScreenCapture
from modules.vrchat_log import VRChatLogWatcher
import modules.commands as cmd


class VRChatBot:
    def __init__(self, config: Config):
        self.config = config
        self.running = False
        self.status = "stopped"

        # WebSocket broadcast set
        self._ws_clients: Set[WebSocket] = set()
        self._ws_lock = threading.Lock()

        # Event loop reference (set when start() is called)
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        # Processing lock — one speech segment at a time
        self._processing = threading.Lock()

        # Modules (some lazy-loaded)
        self.memory = ConversationMemory(
            max_messages=config.get("ai_companion", "max_history") or 20
        )
        self.long_term_memory = LongTermMemory()
        self.llm = LLMClient(config)
        self.tts = TTSClient(config)
        self.osc = VRChatOSC(config)
        self.vision = ScreenCapture(config)
        self.log_watcher = VRChatLogWatcher()
        self._stt: Optional[SpeechToText] = None
        self._audio: Optional[AudioCapture] = None
        self._movement_ctrl: Optional[MovementController] = None
        self._grounding = None  # lazy-loaded GroundingTracker for portal detection

    # ------------------------------------------------------------------ #
    #  WebSocket management                                                #
    # ------------------------------------------------------------------ #

    def add_ws_client(self, ws: WebSocket):
        with self._ws_lock:
            self._ws_clients.add(ws)

    def remove_ws_client(self, ws: WebSocket):
        with self._ws_lock:
            self._ws_clients.discard(ws)

    async def _broadcast(self, event: str, data: dict):
        message = json.dumps({"event": event, "data": data})
        dead: Set[WebSocket] = set()
        with self._ws_lock:
            clients = set(self._ws_clients)
        for ws in clients:
            try:
                await ws.send_text(message)
            except Exception:
                dead.add(ws)
        with self._ws_lock:
            self._ws_clients -= dead

    def _emit(self, event: str, data: dict):
        """Thread-safe broadcast from non-async context."""
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._broadcast(event, data), self._loop)

    # ------------------------------------------------------------------ #
    #  Speech processing pipeline                                          #
    # ------------------------------------------------------------------ #

    def _on_speech(self, audio, sample_rate: int):
        """Called from AudioCapture thread when a speech segment is ready."""
        if not self.running:
            return

        # Only one segment processed at a time
        acquired = self._processing.acquire(blocking=False)
        if not acquired:
            return  # drop segment if still processing previous one

        try:
            self._process_speech(audio, sample_rate)
        finally:
            self._processing.release()

    def _process_speech(self, audio, sample_rate: int):
        # 1. Transcribe
        print(f"[STT] Transcribing {len(audio)/sample_rate:.1f}s of audio...", flush=True)
        self._emit("status", {"message": "Распознаю речь..."})
        text: str = self._stt.transcribe(audio, sample_rate)

        if not text or len(text.strip()) < 2:
            print(f"[STT] Empty result, skipping", flush=True)
            self._emit("status", {"message": "Слушаю..."})
            return

        print(f"[STT] Heard: '{text}'", flush=True)

        self._process_text(text)

    def process_text_input(self, text: str):
        """Public entry point for text input (from web UI or other sources)."""
        if not self.running or not text.strip():
            return
        acquired = self._processing.acquire(blocking=False)
        if not acquired:
            return
        try:
            self._process_text(text.strip())
        finally:
            self._processing.release()

    def _process_text(self, text: str):
        self._emit("message", {"role": "user", "content": text})

        print(f"[Bot] _process_text: '{text}'", flush=True)

        tl = text.lower()

        # ── Shortcut commands (bypass LLM entirely) ────────────────────────

        if any(t in tl for t in cmd.PORTAL_ENTER):
            print("[Bot] Portal enter triggered", flush=True)
            self.memory.add("user", text)
            self._enter_portal()
            return

        if any(t in tl for t in cmd.DOOR_OPEN):
            print("[Bot] Door open triggered", flush=True)
            self.memory.add("user", text)
            self._open_door()
            return

        if any(t in tl for t in cmd.TURN_AROUND):
            print("[Bot] Turn-around triggered", flush=True)
            if self._movement_ctrl:
                self._movement_ctrl.paused = True
            self.osc.execute_movement({"direction": "turn_right", "duration": cmd.TURN_AROUND_DURATION})
            time.sleep(cmd.TURN_AROUND_DURATION + 0.3)
            if self._movement_ctrl:
                self._movement_ctrl.paused = False
            self._shortcut_reply(text, cmd.REPLY["turn_around"])
            return

        if any(t in tl for t in cmd.LOOK_AT):
            print("[Bot] Look-at triggered", flush=True)
            self._set_mode("look_at")
            self._shortcut_reply(text, cmd.REPLY["look_at"])
            return

        if any(t in tl for t in cmd.STAY):
            print("[Bot] Stay triggered", flush=True)
            self._set_mode("stay")
            self._shortcut_reply(text, cmd.REPLY["stay"])
            return

        if any(t in tl for t in cmd.FOLLOW):
            print("[Bot] Follow triggered", flush=True)
            self._set_mode("follow")
            self._shortcut_reply(text, cmd.REPLY["follow"])
            return

        if any(t in tl for t in cmd.JUMP):
            print("[Bot] Jump triggered", flush=True)
            self.osc.jump()
            return

        if any(t in tl for t in cmd.LOOK_STRAIGHT):
            print("[Bot] Look-straight triggered", flush=True)
            self._look_straight()
            return

        # ── LLM pipeline ───────────────────────────────────────────────────

        # Screenshot (if enabled)
        screenshot_b64: Optional[str] = None
        if self.config.get("screenshots", "enabled"):
            try:
                screenshot_b64 = self.vision.capture(max_width=512)
            except Exception as e:
                print(f"[Bot] Screenshot error: {e}")

        # 3. Save user message and build history
        self.memory.add("user", text)
        messages = self.memory.get_messages()

        companion_name: str = self.config.get("ai_companion", "companion_name") or "Компаньон"
        target_player: str  = self.config.get("ai_companion", "target_player") or ""
        personality: str    = self.config.get("ai_companion", "personality") or ""
        gender: str         = self.config.get("ai_companion", "gender") or "male"

        player_line = f"\nТы играешь вместе с игроком по имени {target_player}." if target_player else ""
        gender_line = "Ты — мужчина, говори о себе в мужском роде." if gender == "male" else "Ты — женщина, говори о себе в женском роде."
        system_prompt = (
            f"Ты — ИИ-компаньон в виртуальном мире VRChat - ты существуешь в теле аватара. Твоё имя: {companion_name}. {gender_line}{player_line}\n"
            "Твоя задача - функционировать в виртуальном мире так, как это делают живые игроки. Ты должен максимально естественно общаться. "
            "Каждая твоя реплика будет озвучиваться, поэтому отвечай коротко, не более 3 коротких предложений. Без списков и форматирования. "
            "При ответе ориентируйся на контекст диалога, подстраивайся под тон собеседника. Отвечай на том же языке, на котором общается пользователь."
            "Будь прямолинеен, избегай лести и излишней восторженности. Не отчитывайся, что ты соответствуешь характеру. Запрещено объяснять, какой ты (умный, саркастичный и т.д.). Запрещены клише и канцелярит, говори естественно, живо."
            "Будь инициативен - предлагай игроку какие-либо активности, темы для разговоров. Будь любознателен, тянись к новому."
            "С каждой репликой ты видишь историю своего взаимодействия с игроком. Учитывай это и не повторяйся, поддерживай живой диалог. "
            "С каждым запросом ты получаешь скриншот - на нем ты видишь то, что видит твой персонаж в игре. Ты можешь обращать внимание на какие-либо детали на скриншоте, если это уместно - комментировать окружающий мир и внешность/действия игрока."
            "Неукоснительно соблюдай повадки личности, ни при каких условиях не выходи из образа. \n\n"
            f"Твоя личность:\n{personality}"
        ).strip()

        # Inject world context (from VRChat log watcher)
        world_ctx = self.log_watcher.get_context()
        if world_ctx:
            system_prompt += f"\n\nТекущий контекст:\n{world_ctx}"

        # Inject long-term memory (summaries of past sessions)
        lt_memory = self.long_term_memory.load()
        if lt_memory:
            system_prompt += f"\n\nДолговременная память (прошлые сессии):\n{lt_memory}"

        temperature: float = float(self.config.get("ai_companion", "temperature") or 0.7)

        # 4. LLM request
        self._emit("status", {"message": "Думаю..."})
        current_mode: str = self.config.get("movement", "mode") or "stay"
        response_text, mode_switch = self.llm.chat(
            system_prompt=system_prompt,
            messages=messages,
            screenshot_b64=screenshot_b64,
            temperature=temperature,
            current_mode=current_mode,
        )

        # 4a. Apply mode switch if requested
        if mode_switch:
            print(f"[Bot] Mode switch → {mode_switch}", flush=True)
            self.config.update({"movement": {"mode": mode_switch}})
            if self._movement_ctrl:
                self._movement_ctrl.stop()
                self._movement_ctrl = None
            self._start_movement_ctrl()
            self._emit("mode_changed", {"mode": mode_switch})

        # 5. Persist assistant reply
        self.memory.add("assistant", response_text)
        self._emit("message", {"role": "assistant", "content": response_text})

        # 6. Show text in VRChat chatbox
        self.osc.send_chatbox(response_text)

        # 7. TTS playback
        self._emit("status", {"message": "Говорю..."})

        def on_tts_start():
            if self._audio:
                self._audio.is_playing = True

        def on_tts_done():
            if self._audio:
                self._audio.is_playing = False
            self._emit("status", {"message": "Слушаю..."})

        self.tts.speak(response_text, on_start=on_tts_start, on_complete=on_tts_done)

    # ------------------------------------------------------------------ #
    #  Shortcut helpers                                                    #
    # ------------------------------------------------------------------ #

    def _shortcut_reply(self, user_text: str, reply: str):
        """Persist a shortcut command exchange and speak the reply."""
        self.memory.add("assistant", reply)
        self._emit("message", {"role": "assistant", "content": reply})
        self.osc.send_chatbox(reply)
        self.tts.speak(reply)

    def _look_straight(self):
        """Reset vertical camera to horizontal: max-down first, then up to neutral."""
        self.osc.execute_movement({"direction": "look_down", "duration": cmd.LOOK_STRAIGHT_DOWN_DUR})
        time.sleep(cmd.LOOK_STRAIGHT_DOWN_DUR + 0.1)
        self.osc.execute_movement({"direction": "look_up", "duration": cmd.LOOK_STRAIGHT_UP_DUR})
        time.sleep(cmd.LOOK_STRAIGHT_UP_DUR + 0.1)

    def _set_mode(self, mode: str):
        """Switch movement mode, persist to disk, and restart the controller."""
        self.config.update({"movement": {"mode": mode}})
        self.config.save()
        if self._movement_ctrl:
            self._movement_ctrl.stop()
            self._movement_ctrl = None
        self._start_movement_ctrl()
        self._emit("mode_changed", {"mode": mode})

    def _detect_object_llm(self, screenshot_b64: str, query: str) -> Optional[dict]:
        """
        Ask the vision LLM to locate an object in the screenshot.
        Returns {"position": "left|center|right", "pct": int} or None if not found.
        """
        from openai import OpenAI
        api_key = self.config.get("openrouter", "api_key") or ""
        if not api_key:
            return None
        client = OpenAI(
            api_key=api_key,
            base_url=self.config.get("openrouter", "base_url") or "https://openrouter.ai/api/v1",
            default_headers={"HTTP-Referer": "https://github.com/vrchat-bot", "X-Title": "VRChat AI Bot"},
        )
        model = self.config.get("movement", "model") or "google/gemini-2.0-flash-001"
        prompt = (
            f'На скриншоте VRChat найди объект: "{query}".\n'
            'Голубые вертикальные линии делят экран на зоны LEFT / CENTER / RIGHT.\n'
            'Ответ ТОЛЬКО валидным JSON (без markdown):\n'
            '{"found": false}  ИЛИ  {"found": true, "position": "left|center|right", "pct": <0-100>}\n'
            'pct — примерный размер объекта как % высоты экрана.'
        )
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{screenshot_b64}"}},
                ]}],
                max_tokens=60,
                temperature=0,
            )
            text = (response.choices[0].message.content or "").strip().strip("`")
            if text.lower().startswith("json"):
                text = text[4:].strip()
            data = json.loads(text)
            return data if data.get("found") else None
        except Exception as e:
            print(f"[Bot] LLM object detect error: {e}", flush=True)
            return None

    def _enter_portal(self):
        """Walk straight towards the player for 3.5s — player is always between bot and portal."""
        if self._movement_ctrl:
            self._movement_ctrl.paused = True

        try:
            self._shortcut_reply("", cmd.REPLY["portal_searching"])
            duration = 3.5
            self.osc.execute_movement({"direction": "forward", "duration": duration})
            time.sleep(duration + 0.2)
            companion = self.config.get("ai_companion", "companion_name") or "Бот"
            self.log_watcher.session_events.append(
                f"[{time.strftime('%H:%M:%S')}] {companion} вошёл в портал"
            )
        finally:
            if self._movement_ctrl:
                self._movement_ctrl.paused = False

    def _detect_blue_highlight(self, screenshot_b64: str) -> bool:
        """
        Return True if VRChat's interaction blue outline is visible in the
        central area of the screen.  Uses colour thresholding — no ML needed.
        """
        try:
            import base64 as _b64, io as _io
            import numpy as np
            from PIL import Image as _Img

            raw = _b64.b64decode(screenshot_b64)
            img = _Img.open(_io.BytesIO(raw)).convert("RGB")
            arr = np.array(img)
            h, w = arr.shape[:2]

            # Inspect a centred 75 % × 75 % crop — highlight may appear off-center
            y0, y1 = h // 8, 7 * h // 8
            x0, x1 = w // 8, 7 * w // 8
            region = arr[y0:y1, x0:x1]

            r, g, b = region[:, :, 0], region[:, :, 1], region[:, :, 2]
            # VRChat interaction blue: B channel dominant, high saturation
            blue_mask = (b.astype(int) - r.astype(int) > 80) & \
                        (b.astype(int) - g.astype(int) > 40) & \
                        (b > 120)
            count = int(np.sum(blue_mask))
            print(f"[Bot] Blue highlight pixels: {count}", flush=True)
            return count > 80   # tune if too many false positives / misses
        except Exception as e:
            print(f"[Bot] Blue detect error: {e}", flush=True)
            return False

    @staticmethod
    def _raw_left_click():
        """Send a raw left mouse button press/release via Win32 API."""
        import ctypes
        LEFTDOWN, LEFTUP = 0x0002, 0x0004
        ctypes.windll.user32.mouse_event(LEFTDOWN, 0, 0, 0, 0)
        time.sleep(0.08)
        ctypes.windll.user32.mouse_event(LEFTUP, 0, 0, 0, 0)

    def _open_door(self):
        """
        Scan in a 3×3 numpad pattern around the current view to find the
        VRChat interaction highlight, then left-click to open.

        Scan order: 5→1→2→3→6→5→4→7→8→9 (numpad layout)
        Each step is tiny so the bot barely moves its camera.
        If nothing found after a full scan, take a small step forward and retry.
        """
        if self._movement_ctrl:
            self._movement_ctrl.paused = True

        self._shortcut_reply("", cmd.REPLY["door_searching"])

        S = cmd.DOOR_SCAN_STEP

        def _cam(h: int, v: int):
            """Move camera: h>0=right, h<0=left, v>0=up, v<0=down. One step each."""
            if h != 0:
                d = "turn_right" if h > 0 else "turn_left"
                for _ in range(abs(h)):
                    self.osc.execute_movement({"direction": d, "duration": S})
                    time.sleep(S + 0.06)
            if v != 0:
                d = "look_up" if v > 0 else "look_down"
                for _ in range(abs(v)):
                    self.osc.execute_movement({"direction": d, "duration": S})
                    time.sleep(S + 0.06)

        # Numpad scan: sequence of (dh, dv) delta moves between grid positions.
        # After each move we check for the blue highlight.
        # Path: 5→1→2→3→6→5→4→7→8→9  (net offset from start: h=+1, v=-1)
        SCAN = [
            (  0,  0),   # 5 center — check without moving
            ( -1, +1),   # → 1 up-left
            ( +1,  0),   # → 2 up-center
            ( +1,  0),   # → 3 up-right
            (  0, -1),   # → 6 mid-right
            ( -1,  0),   # → 5 center
            ( -1,  0),   # → 4 mid-left
            (  0, -1),   # → 7 bottom-left
            ( +1,  0),   # → 8 bottom-center
            ( +1,  0),   # → 9 bottom-right
        ]
        # Net accumulated offset after full scan: h=+1, v=-1 → reset with h=-1, v=+1
        RESET = (-1, +1)

        try:
            for approach_step in range(8):
                found = False

                for dh, dv in SCAN:
                    _cam(dh, dv)
                    try:
                        screenshot = self.vision.capture(max_width=0)
                    except Exception:
                        break
                    if not screenshot:
                        break
                    if self._detect_blue_highlight(screenshot):
                        print("[Bot] Blue highlight — raw left click", flush=True)
                        self._raw_left_click()
                        found = True
                        break

                # Return camera to original orientation
                _cam(*RESET)

                if found:
                    companion = self.config.get("ai_companion", "companion_name") or "Бот"
                    self.log_watcher.session_events.append(
                        f"[{time.strftime('%H:%M:%S')}] {companion} открыл дверь"
                    )
                    self._shortcut_reply("", cmd.REPLY["door_opened"])
                    self._look_straight()
                    return

                # Not found — small step forward and rescan
                if approach_step < 7:
                    self.osc.execute_movement({"direction": "forward", "duration": 0.2})
                    time.sleep(0.35)

            self._shortcut_reply("", cmd.REPLY["door_failed"])
            self._look_straight()

        finally:
            if self._movement_ctrl:
                self._movement_ctrl.paused = False

    # ------------------------------------------------------------------ #
    #  Lifecycle                                                           #
    # ------------------------------------------------------------------ #

    async def start(self):
        self.running = True
        self.status = "starting"
        self._loop = asyncio.get_running_loop()

        await self._broadcast("status", {"message": "Загрузка Whisper..."})

        # Load STT in executor to avoid blocking the event loop
        loop = asyncio.get_running_loop()
        try:
            self._stt = await loop.run_in_executor(None, self._load_stt)
        except Exception as e:
            await self._broadcast("error", {"message": f"Ошибка загрузки Whisper: {e}"})
            self.running = False
            self.status = "stopped"
            return

        # Start audio capture
        self._audio = AudioCapture(self.config, self._on_speech)
        self._audio.start()

        # Start VRChat log watcher
        self.memory.mark_session_start()
        self.log_watcher.start(
            on_world_join=self._on_world_join,
            on_player_join=self._on_player_join,
            on_player_leave=self._on_player_leave,
        )

        # Start background movement controller if mode requires it
        self._start_movement_ctrl()

        self.status = "listening"
        await self._broadcast("status", {"message": "Бот запущен. Слушаю..."})
        await self._broadcast("bot_state", {"running": True})

        while self.running:
            await asyncio.sleep(0.5)

    def _load_stt(self) -> SpeechToText:
        return SpeechToText(self.config)

    def _start_movement_ctrl(self):
        """Start MovementController if current mode requires background movement."""
        mode = self.config.get("movement", "mode") or "stay"
        if mode in ("look_at", "follow"):
            self._movement_ctrl = MovementController(self.config, self.osc, self.vision)
            self._movement_ctrl.start(mode)

    async def stop(self):
        self.running = False
        if self._audio:
            self._audio.stop()
            self._audio = None
        if self._movement_ctrl:
            self._movement_ctrl.stop()
            self._movement_ctrl = None
        self.osc.stop_movement()
        self.log_watcher.stop()
        self.status = "stopped"
        await self._broadcast("status", {"message": "Бот остановлен."})
        await self._broadcast("bot_state", {"running": False})

        # Summarise session and persist to long-term memory
        await self._save_session_summary()

    async def _save_session_summary(self):
        session_msgs = self.memory.get_session_messages()
        if len(session_msgs) < 2:
            return

        # Advance the session pointer immediately — prevents double-summarisation
        # if stop() is called again (e.g. via lifespan shutdown after manual stop).
        self.memory.mark_session_start()

        companion_name: str = self.config.get("ai_companion", "companion_name") or "Компаньон"

        # Build dialogue text
        lines = []
        for msg in session_msgs:
            speaker = "Игрок" if msg["role"] == "user" else companion_name
            lines.append(f"{speaker}: {msg['content']}")
        dialogue = "\n".join(lines)

        # Prepend session events (world changes, player joins/leaves) as context
        events = self.log_watcher.pop_session_events()
        if events:
            events_block = "События сессии:\n" + "\n".join(events)
            dialogue = events_block + "\n\nДиалог:\n" + dialogue

        await self._broadcast("status", {"message": "Сохраняю память сессии..."})
        loop = asyncio.get_running_loop()
        summary = await loop.run_in_executor(None, self._summarize_dialogue, dialogue, companion_name)

        if summary:
            self.long_term_memory.append(summary)
            self.long_term_memory.compress_if_needed(self.llm)
            print(f"[Bot] Session summary saved ({len(summary)} chars)")

    def _summarize_dialogue(self, dialogue: str, companion_name: str) -> str:
        system = (
            "Ты — помощник для создания кратких саммари диалогов. "
            "Твоя задача - на основе предоставленного диалога между собеседниками в VRChat сделать сжатую, но содержательную сводку, которая позже будет записана в историю. "
            "Саммари должно быть хронологичным - давать понимание, что произошло раньше, что - позже. "
            "Саммари должно рассказывать, что произошло, но не анализировать. Не нужны фразы типа 'в диалоге была напряженная атмосфера'. "
            "Без допущений, предположений и ненужной воды - только честная и четкая хронология. "
            "Пример хорошего саммари: Игрок и '{companion_name}' пошли в мир Хогвартс. Игрок пошутил что в замке очень грязно, потому что убирается один Филч, который не владеет магией. Компаньон с энтузиазмом продолжил шутку и сказал, что у Дамблдора большие проблемы со способностями управленца.После пошли в мир Пятерочка. Игрок предложила украсть из магазина Фанту, компаньон пошутил что виртуальных денег у них все равно нет. "
            "Размер саммари - не более 300 токенов. "
        )
        prompt = (
            f"Саммаризируй диалог между игроком и ИИ-компаньоном '{companion_name}' в VRChat:\n\n "
            + dialogue
        )
        try:
            result, _ = self.llm.chat(
                system_prompt=system,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
            )
            return result
        except Exception as e:
            print(f"[Bot] Session summarize error: {e}")
            return ""

    # ------------------------------------------------------------------ #
    #  VRChat log callbacks                                                #
    # ------------------------------------------------------------------ #

    def _on_world_join(self, world_name: str, world_id: str):
        self._emit("status", {"message": f"Мир: {world_name}"})

    def _on_player_join(self, player_name: str):
        self._emit("status", {"message": f"Вошёл: {player_name}"})

    def _on_player_leave(self, player_name: str):
        self._emit("status", {"message": f"Вышел: {player_name}"})

    # ------------------------------------------------------------------ #

    def reload_config(self):
        """Re-initialise modules that depend on config (after settings save)."""
        self.llm.reload()
        self.osc = VRChatOSC(self.config)
        self.vision = ScreenCapture(self.config)

        # Update VAD threshold live without restarting audio capture
        if self._audio:
            new_threshold = float(self.config.get("audio", "vad_threshold") or 0.015)
            self._audio.vad_threshold = new_threshold
            print(f"[Bot] VAD threshold updated → {new_threshold}", flush=True)

        # Restart movement controller if bot is running (mode may have changed)
        if self.running:
            if self._movement_ctrl:
                self._movement_ctrl.stop()
                self._movement_ctrl = None
            self._start_movement_ctrl()
