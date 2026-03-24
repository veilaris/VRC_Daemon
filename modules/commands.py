"""
Voice command trigger phrases, constants, and bot replies.
Edit here — no code changes needed elsewhere.
"""

# ── 180° turn ──────────────────────────────────────────────────────────────
TURN_AROUND = [
    "развернись", "разворачивайся", "повернись", "поворачивайся",
    "не туда", "не туда смотришь", "смотришь не туда",
    "разворот", "назад повернись",
]
# How long (seconds) to hold turn_right for ~180°.
# Increase if bot turns less than 180°, decrease if more.
TURN_AROUND_DURATION = 0.7

# ── Portal entry ────────────────────────────────────────────────────────────
PORTAL_ENTER = [
    "портал", "зайди в портал", "иди в портал", "входи в портал",
    "заходи в портал", "в портал", "пойдём в портал", "пойди в портал",
    "прыгай в портал", "зайдём в портал",
]
# Text query sent to Grounding DINO when searching for a portal.
# Try: "portal", "glowing portal", "round glowing ring", "world portal"
PORTAL_DINO_QUERY = "oval glowing portal"

# ── Open door / interact ────────────────────────────────────────────────────
DOOR_OPEN = [
    "открой дверь", "открой", "открывай", "открывай дверь",
    "войди", "зайди в дверь", "иди в дверь",
]
# DINO query for locating the door to interact with.
DOOR_DINO_QUERY = "door"
# Camera step size for the 3×3 door scan (seconds per angular step).
# Increase if steps feel too small, decrease if too large.
DOOR_SCAN_STEP = 0.10

# ── Follow player ───────────────────────────────────────────────────────────
FOLLOW = [
    "иди за мной", "следуй за мной", "следуй", "иди ко мне",
    "топай за мной", "давай за мной",
]

# ── Stop / stay ─────────────────────────────────────────────────────────────
STAY = [
    "стой", "стоп", "остановись", "не двигайся", "замри", "стоять",
]

# ── Look at me ──────────────────────────────────────────────────────────────
LOOK_AT = [
    "смотри на меня", "повернись ко мне", "смотри сюда", "посмотри на меня",
]

# ── Jump ────────────────────────────────────────────────────────────────────
JUMP = [
    "прыгни", "прыгай", "прыжок", "прыгнуть",
]
# Forward movements longer than this (seconds) may trigger an automatic mid-jump
JUMP_AUTO_THRESHOLD = 2.5
# Probability (0.0–1.0) of jumping during a long forward movement
JUMP_AUTO_CHANCE = 0.20

# ── Look straight ahead ─────────────────────────────────────────────────────
LOOK_STRAIGHT = [
    "смотри прямо", "посмотри прямо", "прямо смотри", "голову прямо",
    "смотри вперёд", "посмотри вперёд",
]
# Step 1: hold look_down long enough to guarantee hitting the floor angle.
LOOK_STRAIGHT_DOWN_DUR = 2.0
# Step 2: hold look_up to reach horizontal from the floor.
# Tune this until the bot ends up looking straight ahead.
LOOK_STRAIGHT_UP_DUR   = 0.4

# ── Bot replies for shortcut commands ──────────────────────────────────────
REPLY = {
    "turn_around":      "Разворачиваюсь!",
    "portal_searching": "Ищу портал...",
    "portal_not_found": "Не вижу портал.",
    "door_searching":   "Ищу дверь...",
    "door_opened":      "Открываю!",
    "door_failed":      "Не могу открыть дверь.",
    "dino_unavailable": "DINO трекер недоступен.",
    "error":            "Что-то пошло не так. Проверь настройки.",
    "look_at":          "Буду смотреть на тебя.",
    "stay":             "Буду стоять здесь.",
    "follow":           "Буду идти за тобой.",
}

# ── Phrases to pre-cache as TTS audio ──────────────────────────────────────
# Automatically derived from REPLY — no need to edit separately.
CACHED_PHRASES = set(REPLY.values())
