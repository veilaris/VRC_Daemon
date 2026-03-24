"""
LLM client using OpenRouter API (OpenAI-compatible).
Supports vision (screenshots) and mode switching via response tags.
"""

import re
from typing import Optional

from openai import OpenAI

# Tag embedded in LLM response (stripped before TTS/display)
MODE_TAG_RE = re.compile(r"<mode>(.*?)</mode>", re.DOTALL)

_MODE_SWITCH_TEMPLATE = """

Текущий режим движения: {current_mode}.
ВАЖНО: Добавляй тег <mode> ТОЛЬКО если игрок ЯВНО просит сменить режим (например: "следуй за мной", "стой", "смотри на меня"). Если режим уже установлен и игрок не просит его менять — НЕ добавляй никаких тегов.
При смене режима добавь тег в самом КОНЦЕ ответа (игрок его не увидит), и начни ответ с фразы-подтверждения:
<mode>stay</mode>     — стоять на месте. Начни ответ с: "Хорошо, буду стоять здесь."
<mode>look_at</mode>  — смотреть на игрока, не ходить. Начни ответ с: "Хорошо, буду смотреть на тебя."
<mode>follow</mode>   — постоянно следовать за игроком. Начни ответ с: "Хорошо, иду за тобой."
"""


class LLMClient:
    def __init__(self, config):
        self.config = config
        self._client: Optional[OpenAI] = None
        self._init_client()

    def _init_client(self):
        api_key: str = self.config.get("openrouter", "api_key") or ""
        base_url: str = self.config.get("openrouter", "base_url") or "https://openrouter.ai/api/v1"
        if api_key:
            self._client = OpenAI(
                api_key=api_key,
                base_url=base_url,
                default_headers={
                    "HTTP-Referer": "https://github.com/vrchat-bot",
                    "X-Title": "VRChat AI Bot",
                },
            )
        else:
            self._client = None

    def reload(self):
        """Re-initialise client after config change."""
        self._init_client()

    def chat(
        self,
        system_prompt: str,
        messages: list[dict],
        screenshot_b64: Optional[str] = None,
        temperature: float = 0.7,
        current_mode: str = "stay",
    ) -> tuple[str, Optional[str]]:
        """
        Send a chat request to the LLM.

        Returns:
            (text_response, mode_switch_or_None)
            mode_switch example: "follow"
        """
        if not self._client:
            self._init_client()
        if not self._client:
            return "Ошибка: API ключ не задан.", None

        model: str = self.config.get("openrouter", "model") or "google/gemini-2.0-flash-001"

        # Build full system prompt
        full_system = system_prompt + _MODE_SWITCH_TEMPLATE.format(current_mode=current_mode)

        # Assemble messages list
        api_messages: list[dict] = [{"role": "system", "content": full_system}]

        # History (all but the very last message which we handle below)
        for msg in messages[:-1]:
            api_messages.append({"role": msg["role"], "content": msg["content"]})

        # Last message — optionally attach screenshot
        if messages:
            last = messages[-1]
            if screenshot_b64 and last["role"] == "user":
                api_messages.append({
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{screenshot_b64}"},
                        },
                        {"type": "text", "text": last["content"]},
                    ],
                })
            else:
                api_messages.append({"role": last["role"], "content": last["content"]})

        try:
            response = self._client.chat.completions.create(
                model=model,
                messages=api_messages,
                temperature=temperature,
                max_tokens=800,
            )
            full_text: str = response.choices[0].message.content or ""

            # Extract mode switch
            mode_switch: Optional[str] = None
            mode_match = MODE_TAG_RE.search(full_text)
            if mode_match:
                candidate = mode_match.group(1).strip()
                if candidate in ("stay", "look_at", "follow"):
                    mode_switch = candidate
                full_text = MODE_TAG_RE.sub("", full_text).strip()

            return full_text, mode_switch

        except Exception as e:
            print(f"[LLM] Error: {e}")
            return f"Ошибка ИИ: {e}", None
