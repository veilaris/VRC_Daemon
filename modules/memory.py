"""
Conversation memory stored in a JSON file.
Keeps a rolling window of the last N messages so context doesn't grow unbounded.

Also provides LongTermMemory: accumulates per-session summaries in a plain-text
file and auto-compresses when the file grows too large.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from modules.llm import LLMClient


class ConversationMemory:
    def __init__(self, path: str = "data/memory.json", max_messages: int = 20):
        self.path = Path(path)
        self.max_messages = max_messages
        self._messages: list[dict] = []  # each: {role, content, timestamp}
        self._session_start: int = 0     # index where current session begins

        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._load()

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def add(self, role: str, content: str):
        """Append a message and persist."""
        self._messages.append({
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        })
        self._trim()
        self._save()

    def get_messages(self) -> list[dict]:
        """Return messages in LLM-compatible format (role + content only)."""
        return [{"role": m["role"], "content": m["content"]} for m in self._messages]

    def get_all(self) -> list[dict]:
        """Return full records including timestamps (for the UI log)."""
        return list(self._messages)

    def mark_session_start(self):
        """Call at bot start to mark where the current session begins."""
        self._session_start = len(self._messages)

    def get_session_messages(self) -> list[dict]:
        """Return messages added since mark_session_start()."""
        return [
            {"role": m["role"], "content": m["content"]}
            for m in self._messages[self._session_start:]
        ]

    def delete_message(self, index: int):
        """Remove a single message by index. Adjusts session_start accordingly."""
        if 0 <= index < len(self._messages):
            self._messages.pop(index)
            if index < self._session_start:
                self._session_start = max(0, self._session_start - 1)
            self._save()

    def clear(self):
        self._messages = []
        self._session_start = 0
        self._save()

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                    #
    # ------------------------------------------------------------------ #

    def _trim(self):
        limit = self.max_messages * 2  # user + assistant pairs
        if len(self._messages) > limit:
            # Adjust session_start so it stays valid after trim
            removed = len(self._messages) - limit
            self._session_start = max(0, self._session_start - removed)
            self._messages = self._messages[-limit:]

    def _save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(
                    {"messages": self._messages, "updated": datetime.now().isoformat()},
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
        except Exception as e:
            print(f"[Memory] Save error: {e}")

    def _load(self):
        if self.path.exists():
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._messages = data.get("messages", [])
                # Previous session messages are already history — start fresh
                self._session_start = len(self._messages)
            except Exception as e:
                print(f"[Memory] Load error: {e}")
                self._messages = []


# --------------------------------------------------------------------------- #


class LongTermMemory:
    """
    Persists per-session summaries in data/long_term_memory.txt.
    Auto-compresses when file exceeds MAX_CHARS by re-summarising with the LLM.
    """

    MAX_CHARS = 3000

    def __init__(self, path: str = "data/long_term_memory.txt"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> str:
        if not self.path.exists():
            return ""
        try:
            return self.path.read_text(encoding="utf-8").strip()
        except Exception:
            return ""

    def append(self, summary: str):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        entry = f"\n[{ts}]\n{summary.strip()}\n"
        try:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(entry)
        except Exception as e:
            print(f"[LongTermMemory] Write error: {e}")

    def compress_if_needed(self, llm: "LLMClient") -> bool:
        """If file > MAX_CHARS, summarise the whole file and overwrite."""
        content = self.load()
        if len(content) <= self.MAX_CHARS:
            return False

        print(f"[LongTermMemory] File too large ({len(content)} chars), compressing...")
        compressed = self._summarize(content, llm)
        if not compressed:
            return False

        try:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M")
            self.path.write_text(
                f"[Сжатая память до {ts}]\n{compressed}\n",
                encoding="utf-8",
            )
            print(f"[LongTermMemory] Compressed to {len(compressed)} chars")
            return True
        except Exception as e:
            print(f"[LongTermMemory] Compress write error: {e}")
            return False

    @staticmethod
    def _summarize(text: str, llm: "LLMClient") -> str:
        system = (
            "Ты — помощник для создания сжатых саммари. "
            "Отвечай только саммари на русском языке, без лишних слов."
        )
        prompt = (
            "Сожми следующие записи о разговорах в краткое саммари. "
            "Сохрани важные факты, события, темы разговоров:\n\n" + text
        )
        try:
            result, _ = llm.chat(
                system_prompt=system,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
            )
            return result
        except Exception as e:
            print(f"[LongTermMemory] Summarize error: {e}")
            return ""
