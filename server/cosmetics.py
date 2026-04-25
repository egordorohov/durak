"""Cosmetics catalog — card backs, table skins."""
from __future__ import annotations

CARD_SKINS: dict[str, dict] = {
    "classic":  {"name": "Классик",  "price": 0},
    "dots":     {"name": "Горошек",  "price": 500},
    "cross":    {"name": "Решётка",  "price": 500},
    "waves":    {"name": "Волны",    "price": 1000},
    "dark":     {"name": "Ночь",     "price": 1500},
    "red":      {"name": "Красная",  "price": 500},
    "blue":     {"name": "Синяя",    "price": 750},
    "gold":     {"name": "Золото",   "price": 1500},
    "checkers": {"name": "Шашки",    "price": 1000},
    "diamonds": {"name": "Ромбы",    "price": 1000},
}

TABLE_SKINS: dict[str, dict] = {
    "default": {"name": "Стандарт", "price": 0},
}

EMOJI_PACKS: dict[str, dict] = {
    "classic": {"name": "Классик",    "price": 0,    "emojis": ["👍", "😂", "🤡", "🔥", "😤", "🫡"]},
    "villain": {"name": "Злодей",     "price": 500,  "emojis": ["💀", "😈", "🤬", "💣", "😡", "🫠"]},
    "winner":  {"name": "Победитель", "price": 750,  "emojis": ["🏆", "🥇", "💪", "🎉", "😎", "🤩"]},
    "animals": {"name": "Животные",   "price": 1000, "emojis": ["🐻", "🦊", "🐸", "🦁", "🐯", "🐺"]},
    "space":   {"name": "Космос",     "price": 1500, "emojis": ["🚀", "🌙", "⭐", "👽", "🌌", "🛸"]},
}

ALL_COSMETICS: dict[str, dict] = {}
for _k, _v in CARD_SKINS.items():
    ALL_COSMETICS[f"card_{_k}"] = {**_v, "kind": "card", "skin_id": _k}
for _k, _v in TABLE_SKINS.items():
    ALL_COSMETICS[f"table_{_k}"] = {**_v, "kind": "table", "skin_id": _k}
for _k, _v in EMOJI_PACKS.items():
    ALL_COSMETICS[f"emoji_{_k}"] = {**_v, "kind": "emoji", "skin_id": _k}

FREE_IDS = {cid for cid, c in ALL_COSMETICS.items() if c["price"] == 0}

CATALOG = {
    "card_skins": [
        {"id": f"card_{k}", "kind": "card", "skin_id": k, **v}
        for k, v in CARD_SKINS.items()
    ],
    "table_skins": [
        {"id": f"table_{k}", "kind": "table", "skin_id": k, **v}
        for k, v in TABLE_SKINS.items()
    ],
    "emoji_packs": [
        {"id": f"emoji_{k}", "kind": "emoji", "skin_id": k, **v}
        for k, v in EMOJI_PACKS.items()
    ],
}

AVATAR_COLORS = [
    "#e74c3c", "#3498db", "#2ecc71", "#f39c12",
    "#9b59b6", "#1abc9c", "#e67e22", "#e91e63",
]


def make_avatar(pid: int, name: str, url: str | None = None) -> dict:
    if pid == -1:
        return {"color": "#546e7a", "initials": "🤖", "url": None}
    color = AVATAR_COLORS[abs(pid) % len(AVATAR_COLORS)]
    parts = name.strip().split()
    if len(parts) >= 2:
        initials = (parts[0][0] + parts[1][0]).upper()
    elif len(name) >= 2:
        initials = name[:2].upper()
    elif name:
        initials = name[0].upper()
    else:
        initials = "?"
    return {"color": color, "initials": initials, "url": url}
