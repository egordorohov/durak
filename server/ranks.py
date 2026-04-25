"""Rank definitions based on total games played."""
from __future__ import annotations

RANKS = [
    {"id": "рядовой",      "title": "Рядовой",         "min_games": 0,    "pogon": {"type": "blank"}},
    {"id": "ефрейтор",     "title": "Ефрейтор",        "min_games": 5,    "pogon": {"type": "stripes", "n": 1}},
    {"id": "мл_сержант",   "title": "Мл. сержант",     "min_games": 15,   "pogon": {"type": "stripes", "n": 2}},
    {"id": "сержант",      "title": "Сержант",         "min_games": 30,   "pogon": {"type": "stripes", "n": 3}},
    {"id": "старшина",     "title": "Старшина",        "min_games": 75,   "pogon": {"type": "bar"}},
    {"id": "прапорщик",    "title": "Прапорщик",       "min_games": 150,  "pogon": {"type": "stars", "n": 2, "size": "sm"}},
    {"id": "лейтенант",    "title": "Лейтенант",       "min_games": 300,  "pogon": {"type": "stars", "n": 2, "size": "md"}},
    {"id": "ст_лейтенант", "title": "Ст. лейтенант",   "min_games": 500,  "pogon": {"type": "stars", "n": 3, "size": "md"}},
    {"id": "капитан",      "title": "Капитан",         "min_games": 750,  "pogon": {"type": "stars", "n": 4, "size": "md"}},
    {"id": "майор",        "title": "Майор",           "min_games": 1000, "pogon": {"type": "stars", "n": 1, "size": "lg"}},
    {"id": "подполковник", "title": "Подполковник",    "min_games": 1500, "pogon": {"type": "stars", "n": 2, "size": "lg"}},
    {"id": "полковник",    "title": "Полковник",       "min_games": 2000, "pogon": {"type": "stars", "n": 3, "size": "lg"}},
    {"id": "генерал",      "title": "Генерал",         "min_games": 3500, "pogon": {"type": "general"}},
    {"id": "маршал",       "title": "Маршал",          "min_games": 6000, "pogon": {"type": "marshal"}},
]


def get_rank(games: int) -> dict:
    """Returns the highest rank the player has achieved."""
    rank = RANKS[0]
    for r in RANKS:
        if games >= r["min_games"]:
            rank = r
    return rank


def get_rank_progress(games: int) -> dict:
    """Returns current rank, next rank, and progress."""
    current = get_rank(games)
    idx = RANKS.index(current)
    if idx + 1 < len(RANKS):
        nxt = RANKS[idx + 1]
        progress = (games - current["min_games"]) / (nxt["min_games"] - current["min_games"])
    else:
        nxt = None
        progress = 1.0
    return {"current": current, "next": nxt, "progress": round(progress, 3), "games": games}
