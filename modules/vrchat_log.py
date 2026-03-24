"""
VRChat log file watcher.
Tails the latest output_log_*.txt and fires callbacks on world/player events.
"""

import os
import re
import threading
import time
from pathlib import Path
from typing import Callable, Optional

_RE_WORLD_NAME = re.compile(r"\[RoomManager\] Joining or Creating Room:\s*(.+)")
_RE_WORLD_ID   = re.compile(r"\[Behaviour\] Joining (wrld_[a-zA-Z0-9\-]+)")
_RE_PLAYER_JOIN  = re.compile(r"\[NetworkManager\] OnPlayerJoined\s+(.+)")
_RE_PLAYER_LEAVE = re.compile(r"\[NetworkManager\] OnPlayerLeft\s+(.+)")


class VRChatLogWatcher:
    """
    Watches the VRChat log file in a background thread.
    Tracks current world and players in the instance.
    """

    def __init__(self):
        self.current_world_name: str = ""
        self.current_world_id: str = ""
        self.players: list[str] = []
        self.session_events: list[str] = []  # timestamped log for the summariser

        self._running = False
        self._thread: Optional[threading.Thread] = None

        self._on_world_join:   Optional[Callable[[str, str], None]] = None
        self._on_player_join:  Optional[Callable[[str], None]] = None
        self._on_player_leave: Optional[Callable[[str], None]] = None

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def start(
        self,
        on_world_join:   Optional[Callable[[str, str], None]] = None,
        on_player_join:  Optional[Callable[[str], None]] = None,
        on_player_leave: Optional[Callable[[str], None]] = None,
    ):
        self._on_world_join   = on_world_join
        self._on_player_join  = on_player_join
        self._on_player_leave = on_player_leave
        self._running = True
        self._thread = threading.Thread(
            target=self._watch, daemon=True, name="VRChatLogWatcher"
        )
        self._thread.start()

    def stop(self):
        self._running = False

    def get_context(self) -> str:
        """One-liner injected into the system prompt — world name only."""
        if self.current_world_name:
            return f"Текущий мир: {self.current_world_name}"
        return ""

    def pop_session_events(self) -> list[str]:
        """Return and clear accumulated session events (for the summariser)."""
        events = list(self.session_events)
        self.session_events.clear()
        return events

    # ------------------------------------------------------------------ #
    #  Internal                                                            #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _find_log_file() -> Optional[Path]:
        appdata = os.environ.get("APPDATA", "")
        log_dir = Path(appdata).parent / "LocalLow" / "VRChat" / "VRChat"
        if not log_dir.exists():
            return None
        logs = sorted(
            log_dir.glob("output_log_*.txt"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return logs[0] if logs else None

    def _watch(self):
        log_path = self._find_log_file()
        if not log_path:
            print("[VRChatLog] Log file not found — world context unavailable")
            return
        print(f"[VRChatLog] Watching {log_path.name}")

        try:
            with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                f.seek(0, 2)  # jump to end — only watch new lines
                while self._running:
                    line = f.readline()
                    if not line:
                        time.sleep(0.2)
                        continue
                    self._parse_line(line)
        except Exception as e:
            print(f"[VRChatLog] Error: {e}")

    def _ts(self) -> str:
        return time.strftime("%H:%M:%S")

    def _parse_line(self, line: str):
        if m := _RE_WORLD_NAME.search(line):
            self.current_world_name = m.group(1).strip()
            self.players.clear()
            self.session_events.append(f"[{self._ts()}] Вошли в мир: {self.current_world_name}")
            print(f"[VRChatLog] World: {self.current_world_name}")
            if self._on_world_join:
                self._on_world_join(self.current_world_name, self.current_world_id)

        if m := _RE_WORLD_ID.search(line):
            self.current_world_id = m.group(1)

        if m := _RE_PLAYER_JOIN.search(line):
            name = m.group(1).strip()
            if name and name not in self.players:
                self.players.append(name)
            print(f"[VRChatLog] Joined: {name}")
            if self._on_player_join:
                self._on_player_join(name)

        if m := _RE_PLAYER_LEAVE.search(line):
            name = m.group(1).strip()
            self.players = [p for p in self.players if p != name]
            print(f"[VRChatLog] Left: {name}")
            if self._on_player_leave:
                self._on_player_leave(name)
