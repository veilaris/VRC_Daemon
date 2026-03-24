"""
VRChat OSC controller.
Sends movement and chatbox commands to VRChat via OSC (default port 9000).

VRChat OSC movement endpoints:
  /input/Vertical    float  -1..1  (forward/backward)
  /input/Horizontal  float  -1..1  (strafe left/right)
  /input/LookHorizontal  float  (camera yaw — used for turning)
  /input/Jump        int    0/1
  /input/Run         int    0/1

Chatbox:
  /chatbox/input  [string text, bool send_immediately]
"""

import threading
import time
from typing import Optional

from pythonosc import udp_client


DIRECTION_MAP: dict[str, tuple[float, float]] = {
    "forward":    (0.0,  1.0),
    "backward":   (0.0, -1.0),
    "left":       (-1.0, 0.0),
    "right":      (1.0,  0.0),
    "stop":       (0.0,  0.0),
}
TURN_DIRECTIONS  = {"turn_left", "turn_right"}
LOOK_V_DIRECTIONS = {"look_up", "look_down"}


class VRChatOSC:
    def __init__(self, config):
        host: str = config.get("osc", "host") or "127.0.0.1"
        port: int = int(config.get("osc", "port") or 9000)
        self._client = udp_client.SimpleUDPClient(host, port)
        self._move_thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def execute_movement(self, cmd: dict):
        """
        Execute a movement command dict.
        Example: {"direction": "forward", "duration": 2.5}
        Runs in a background thread so it doesn't block the main loop.
        """
        if not cmd:
            return
        direction: str = cmd.get("direction", "stop")
        duration: float = max(0.1, min(float(cmd.get("duration", 1.0)), 10.0))

        t = threading.Thread(
            target=self._move,
            args=(direction, duration),
            daemon=True,
        )
        t.start()
        self._move_thread = t

    def stop_movement(self):
        """Immediately stop all movement."""
        self._client.send_message("/input/Horizontal", 0.0)
        self._client.send_message("/input/Vertical", 0.0)
        self._client.send_message("/input/LookHorizontal", 0.0)

    def send_chatbox(self, text: str, send_immediately: bool = True):
        """Display text in VRChat chatbox bubble."""
        if not text:
            return
        # Trim to VRChat chatbox limit (144 chars)
        text = text[:144]
        self._client.send_message("/chatbox/input", [text, send_immediately])

    def jump(self):
        self._client.send_message("/input/Jump", 1)
        time.sleep(0.1)
        self._client.send_message("/input/Jump", 0)

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                    #
    # ------------------------------------------------------------------ #

    def _move(self, direction: str, duration: float):
        if direction in TURN_DIRECTIONS:
            value = -1.0 if direction == "turn_left" else 1.0
            self._client.send_message("/input/LookHorizontal", value)
            time.sleep(duration)
            self._client.send_message("/input/LookHorizontal", 0.0)
        elif direction in LOOK_V_DIRECTIONS:
            value = 1.0 if direction == "look_up" else -1.0
            self._client.send_message("/input/LookVertical", value)
            time.sleep(duration)
            self._client.send_message("/input/LookVertical", 0.0)
        elif direction in DIRECTION_MAP:
            from modules.commands import JUMP_AUTO_THRESHOLD
            h, v = DIRECTION_MAP[direction]
            self._client.send_message("/input/Horizontal", h)
            self._client.send_message("/input/Vertical", v)
            if direction != "stop":
                if direction == "forward" and duration >= JUMP_AUTO_THRESHOLD:
                    import random
                    from modules.commands import JUMP_AUTO_CHANCE
                    if random.random() < JUMP_AUTO_CHANCE:
                        half = duration / 2
                        time.sleep(half)
                        self._client.send_message("/input/Jump", 1)
                        time.sleep(0.1)
                        self._client.send_message("/input/Jump", 0)
                        time.sleep(duration - half - 0.1)
                    else:
                        time.sleep(duration)
                else:
                    time.sleep(duration)
            self._client.send_message("/input/Horizontal", 0.0)
            self._client.send_message("/input/Vertical", 0.0)
        else:
            print(f"[OSC] Unknown direction: {direction!r}")
