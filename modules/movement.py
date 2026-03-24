"""
Background movement controller for Follow / Look-at modes.

Runs independently of the conversation pipeline on a fixed interval.

Mode behaviour:
  look_at — simple LLM detection → rotate to face player, no walking
  follow  — LLM plans a multi-step movement sequence to navigate to player

_plan_movement return values (3 distinct states):
  None          → player not found → rotate to scan
  []  (empty)   → player found, already at target distance → stay put
  [steps]       → player found, need to move → execute steps
"""

import json
import threading
import time
from typing import Optional

from openai import OpenAI

from modules.grounding_tracker import GroundingTracker
class MovementController:
    def __init__(self, config, osc, vision):
        self.config = config
        self.osc = osc
        self.vision = vision
        threshold = float(config.get("movement", "dino_threshold") or 0.40)
        self._grounding = GroundingTracker(threshold=threshold)
        self.running = False
        self.paused  = False
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------ #
    #  Lifecycle                                                           #
    # ------------------------------------------------------------------ #

    def start(self, mode: str):
        if self.running:
            return
        self.running = True
        self._thread = threading.Thread(
            target=self._loop,
            args=(mode,),
            daemon=True,
            name="MovementController",
        )
        self._thread.start()
        print(f"[Movement] Started — mode: {mode}", flush=True)

    def stop(self):
        self.running = False
        self.osc.stop_movement()
        print("[Movement] Stopped.", flush=True)

    # ------------------------------------------------------------------ #
    #  Main loop                                                           #
    # ------------------------------------------------------------------ #

    def _loop(self, mode: str):
        while self.running:
            interval = float(self.config.get("movement", "interval") or 4.0)
            try:
                self._tick(mode)
            except Exception as e:
                print(f"[Movement] Tick error: {e}", flush=True)
            time.sleep(interval)

    def _tick(self, mode: str):
        if mode == "stay" or self.paused:
            return

        target = self.config.get("ai_companion", "target_player") or ""
        if not target:
            return

        try:
            # Full resolution for Grounding DINO; LLM fallback resizes itself via max_width param
            screenshot_full = self.vision.capture(max_width=0)
            screenshot_llm  = self.vision.capture(max_width=512)
        except Exception as e:
            print(f"[Movement] Screenshot error: {e}", flush=True)
            return
        if not screenshot_full:
            return

        scan_dur = float(self.config.get("movement", "scan_turn_duration") or 0.6)

        if mode == "look_at":
            result = self._detect_player(target, screenshot_full, screenshot_llm)
            if result is None:
                self.osc.execute_movement({"direction": "turn_right", "duration": scan_dur})
                print("[Movement] Player not found — scanning...", flush=True)
            else:
                position = result.get("position", "center")
                print(f"[Movement] Look-at: position={position}", flush=True)
                if position == "left":
                    self.osc.execute_movement({"direction": "turn_left", "duration": 0.15})
                elif position == "right":
                    self.osc.execute_movement({"direction": "turn_right", "duration": 0.15})

        elif mode == "follow":
            # _plan_movement returns: None = not found, [] = at target, [steps] = move
            steps = self._plan_movement(target, screenshot_full, screenshot_llm)
            if steps is None:
                self.osc.execute_movement({"direction": "turn_right", "duration": scan_dur})
                print("[Movement] Player not found — scanning...", flush=True)
            elif len(steps) == 0:
                print("[Movement] Already at target distance — waiting.", flush=True)
            else:
                print(f"[Movement] Executing plan: {steps}", flush=True)
                for step in steps:
                    if not self.running:
                        break
                    self.osc.execute_movement(step)
                    dur = max(0.1, float(step.get("duration", 1.0)))
                    time.sleep(dur + 0.15)

    # ------------------------------------------------------------------ #
    #  LLM: simple position detection (for look_at)                       #
    # ------------------------------------------------------------------ #

    def _detect_player(self, target: str, screenshot_full: str, screenshot_llm: str) -> Optional[dict]:
        """
        Returns {"found": True, "position": "left|center|right"}
        or None if player not found / call fails.
        """
        tracker = self.config.get("movement", "tracker") or "llm"

        if tracker == "grounding":
            appearance = self.config.get("movement", "appearance") or ""
            gr = self._grounding.find_player(screenshot_full, appearance) if appearance else None
            return {"found": True, "position": gr["position"]} if gr else None

        # LLM path
        client = self._make_client()
        if not client:
            return None

        appearance = self.config.get("movement", "appearance") or ""
        appearance_hint = f" Внешность игрока: {appearance}." if appearance else ""

        prompt = (
            f'На скриншоте VRChat найди игрока с ником "{target}".{appearance_hint}\n\n'
            'Голубые вертикальные линии делят экран на зоны LEFT / CENTER / RIGHT.\n'
            'Определи, в какой зоне находится центр тела персонажа.\n\n'
            'Ответ ТОЛЬКО валидным JSON (без markdown):\n'
            '{"found": false}  ИЛИ  {"found": true, "position": "left|center|right"}'
        )

        try:
            model = self.config.get("movement", "model_look_at") or self.config.get("movement", "model") or "google/gemini-2.0-flash-001"
            response = self._llm_call(client, prompt, screenshot_llm, max_tokens=50, model=model)
            data = json.loads(response)
            return data if data.get("found") else None
        except Exception as e:
            print(f"[Movement] Detect error: {e}", flush=True)
            return None

    # ------------------------------------------------------------------ #
    #  LLM: multi-step movement planning (for follow)                     #
    # ------------------------------------------------------------------ #

    # LLM reports avatar height as % of screen height (0-100).
    # Python stops when pct >= threshold.
    # "far" pct threshold — stop when full body is visible AND pct >= this value
    _FAR_PCT_THRESHOLD = 35

    @staticmethod
    def _forward_dur(pct: int) -> float:
        """Forward step duration — bigger steps when far, tiny steps near target."""
        if pct >= 55: return 0.25
        if pct >= 35: return 0.7
        if pct >= 20: return 1.5
        return 2.5

    def _plan_movement(self, target: str, screenshot_full: str, screenshot_llm: str) -> Optional[list[dict]]:
        """
        Detect the player's position and size, then generate movement steps.

        Returns:
          None      — player not visible (caller should scan)
          []        — player visible but already at/past target distance (stay)
          [steps]   — movement steps to execute
        """
        tracker = self.config.get("movement", "tracker") or "llm"

        if tracker == "grounding":
            appearance = self.config.get("movement", "appearance") or ""
            gr = self._grounding.find_player(screenshot_full, appearance) if appearance else None
            return self._steps_from_grounding(gr) if gr else None

        # LLM path
        client = self._make_client()
        if not client:
            return None

        appearance = self.config.get("movement", "appearance") or "неизвестной внешностью"

        prompt = (
            "###Роль\n"
            "Твоя задача - внимательно просмотреть предоставленный скриншот и определить рост, "
            f"местоположение и формат тела игрока с именем \"{target}\" и внешностью {appearance}.\n\n"
            "###Алгоритм работы\n"
            "На вход тебе подается скриншот из VRChat. На скриншот добавлена сетка измерений. "
            "Желтые горизонтальные линии (20, 40, 60, 80%) предназначены для определения роста игрока. "
            "Голубые вертикальные линии предназначены для определения местоположения игрока.\n\n"
            f"1) Проверь, виден ли на скриншоте игрок с именем \"{target}\" и внешностью {appearance}. "
            'Если игрок не виден - верни {"found": false} и на этом заверши работу.\n'
            "2) Если игрок виден - тебе необходимо определить его рост, местоположение и полностью ли видно его тело.\n"
            "3) Определение роста. Тебе необходимо определить рост персонажа, он измеряется в \"pct\". "
            "Для определения роста тебе необходимо воспользоваться желтыми горизонтальными линиями. "
            "Определи, к какой линии ближе всего самая верхняя точка головы персонажа - это значение head_pct, "
            "а также к какой линии ближе всего самая нижняя точка ног персонажа - это значение feet_pct. "
            "Если ступни или ноги обрезаны нижним краем скриншота - принимаем feet_pct как 100. "
            "Рост вычисляется по формуле feet_pct - head_pct. Подсчитывай как в Примерах определения роста.\n"
            "4) Определение местоположения. Тебе необходимо определить позицию персонажа относительно "
            "вертикальных голубых линий. Если персонаж левее линии left - возвращается left. "
            "Если персонаж между линиями left и right - возвращается center. "
            "Если персонаж правее линии right - возвращается right.\n"
            "5) Определение формата тела. Тебе необходимо понять, полностью ли виден персонаж игрока, "
            "или виден только частично. Если у персонажа одновременно хорошо видны и голова и ноги, "
            "ноги не обрезаны нижним краем скриншота и виден пол под ступнями, full_body = true. "
            "Иначе full_body = false.\n"
            '6) Верни данные в формате {"found": true, "position": "left|center|right", '
            '"pct": <целое число 0-100>, "full_body": <true|false>}\n\n'
            "###Формат вывода\n"
            "Отвечай ТОЛЬКО в формате JSON (без разметки Markdown). Никаких дополнительных комментариев.\n"
            'Если персонаж не найден на скриншоте: {"found": false}\n'
            'Если персонаж найден на скриншоте: {"found": true, "position": "left|center|right", '
            '"pct": <целое число 0-100>, "full_body": <true|false>}\n\n'
            "###Примеры определения роста\n"
            "голова на 10%, ступни на 70% → pct: 60\n"
            "голова на 20%, ступни на 80% → pct: 60\n"
            "голова на 30%, ступни обрезаны (=100%) → pct: 70\n"
            "голова на 5%, ступни на 40% → pct: 35"
        )

        try:
            model = self.config.get("movement", "model_follow") or self.config.get("movement", "model") or "google/gemini-2.0-flash-001"
            response = self._llm_call(client, prompt, screenshot_llm, max_tokens=80, model=model)
            data = json.loads(response)
        except Exception as e:
            print(f"[Movement] Plan error: {e}", flush=True)
            return None

        if not data.get("found", False):
            return None  # not found → scan

        position  = data.get("position", "center")
        pct       = int(data.get("pct", 10))
        full_body = bool(data.get("full_body", True))
        print(f"[Movement] Detected: position={position}, pct={pct}%, full_body={full_body}", flush=True)

        stop_key = self.config.get("movement", "stop_distance") or "close"

        # Stop condition depends on mode:
        #   close → feet cut off AND already reasonably close (pct >= 45)
        #           the pct guard prevents stopping on false-negatives when far away
        #   far   → full body visible AND large enough on screen
        if stop_key == "close":
            at_target = (not full_body) and (pct >= 45)
        else:  # far
            at_target = full_body and pct >= self._FAR_PCT_THRESHOLD

        if at_target:
            # Even at target distance — centre on the player if needed
            if position == "left":
                return [{"direction": "turn_left",  "duration": 0.15}]
            elif position == "right":
                return [{"direction": "turn_right", "duration": 0.15}]
            return []

        # Build movement steps in Python
        steps: list[dict] = []

        # 1. Rotate to centre the player
        if position == "left":
            steps.append({"direction": "turn_left",  "duration": 0.15})
        elif position == "right":
            steps.append({"direction": "turn_right", "duration": 0.15})

        # 2. Walk forward — duration scales with current distance
        steps.append({"direction": "forward", "duration": self._forward_dur(pct)})

        return steps

    # ------------------------------------------------------------------ #
    #  Grounding DINO helpers                                            #
    # ------------------------------------------------------------------ #

    def _steps_from_grounding(self, gr: dict) -> list[dict]:
        position = gr["position"]
        pct      = gr["pct"]
        stop_key = self.config.get("movement", "stop_distance") or "close"

        # Back up if too close (bounding box almost fills screen)
        if pct >= 70:
            return [{"direction": "backward", "duration": 0.4}]

        at_target = pct >= 45 if stop_key == "close" else pct >= self._FAR_PCT_THRESHOLD

        if at_target:
            if position == "left":  return [{"direction": "turn_left",  "duration": 0.15}]
            if position == "right": return [{"direction": "turn_right", "duration": 0.15}]
            return []

        steps: list[dict] = []
        if position == "left":  steps.append({"direction": "turn_left",  "duration": 0.15})
        if position == "right": steps.append({"direction": "turn_right", "duration": 0.15})
        steps.append({"direction": "forward", "duration": self._forward_dur(pct)})
        return steps

    # ------------------------------------------------------------------ #
    #  Shared LLM helpers                                                 #
    # ------------------------------------------------------------------ #

    def _make_client(self) -> Optional[OpenAI]:
        api_key = self.config.get("openrouter", "api_key") or ""
        if not api_key:
            print("[Movement] No API key.", flush=True)
            return None
        return OpenAI(
            api_key=api_key,
            base_url=self.config.get("openrouter", "base_url") or "https://openrouter.ai/api/v1",
            default_headers={
                "HTTP-Referer": "https://github.com/vrchat-bot",
                "X-Title": "VRChat AI Bot",
            },
        )

    def _llm_call(self, client: OpenAI, prompt: str, screenshot_b64: str, max_tokens: int, model: str = "") -> str:
        if not model:
            model = self.config.get("movement", "model") or "google/gemini-2.0-flash-001"
        response = client.chat.completions.create(
            model=model,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{screenshot_b64}"},
                    },
                ],
            }],
            max_tokens=max_tokens,
            temperature=0,
        )
        text = (response.choices[0].message.content or "").strip()
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
        return text
