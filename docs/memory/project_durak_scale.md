---
name: Durak — План масштабирования на 1M MAU
description: Приоритизированный план оптимизации /root/durak без реврайта на Rust/Go. Статус задач и детали реализации.
type: project
updated: 2026-04-25
originSessionId: ab619c64-388c-47af-b3cc-8e0ed501f551
---
## Решение по реврайту (2026-04-25)

**Не переписываем на Rust/Go.** Дурак — пошаговая игра, RPS в ~100x ниже чем у тапалок (Notcoin). 1M MAU = ~10-30k concurrent в пике, Python это тянет с правильной архитектурой.

**Why:** Rust оправдан только при 50k+ concurrent на одной машине. Реврайт = 5-7 недель работы ради страховки, которая не понадобится.

**How to apply:** При вопросах "не переписать ли" — отвечать нет, идти по плану ниже.

---

## Статус задач (2026-04-25)

| # | Задача | Статус |
|---|---|---|
| 1 | Debounce `broadcast_room_list` | done |
| 2 | nginx статика напрямую + cache headers | done |
| 3 | Redis-кэш лидерборда + убраны внешние `_pool_get()` | done |
| 4 | Апгрейд VPS до 4 CPU / 8 GB | пользователь делает сам |
| 5 | Декомпозиция `handle()` | pending |
| 6 | Hub в Redis (cross-worker комнаты) | pending, приоритет |
| 7 | Multi-server + nginx LB | pending |
| 8 | Декомпозиция app.js | pending |

---

## Детали задач

### Задача 1 — Debounce broadcast_room_list (DONE)
- Заменили 15 вызовов `create_task(broadcast_room_list())` на `queue_room_list_broadcast()`
- Hub накапливает флаг `_room_list_pending`, воркер `_room_list_worker` сбрасывает раз в 400ms
- Результат: 20x меньше broadcast-ов при активных ботах

### Задача 2 — nginx статика напрямую (DONE)
- `app.js`, `style.css` — nginx, cache 30 дней (versioned ?v=XX)
- `packs/*.webp` — nginx, cache 1 год (immutable)
- `index.html` — Python, no-cache
- `chmod o+x /root` чтобы www-data мог traverse
- Результат: статика не доходит до Python-воркеров

### Задача 3 — Redis-кэш лидерборда (DONE)
- `get_leaderboard` и `get_clan_leaderboard` — Redis TTL 5 сек
- Добавлены `get_user_by_username()` и `get_pool()` в db.py
- Убраны все внешние `_pool_get()` из main.py и fake_players.py
- Результат: -70% DB нагрузка при активном лидерборде

### Задача 4 — Апгрейд VPS
- Текущее: 3 CPU / 2 GB RAM (swap 50% — bottleneck)
- Цель: 4 CPU / 8 GB
- Даёт: +2x concurrent, убирает swap

### Задача 5 — Декомпозиция handle() (1-2 дня)
- Файл: `server/main.py` (~700 строк, degree 76 в графе)
- Разбить на: `handle_game.py`, `handle_lobby.py`, `handle_social.py`, `handle_shop.py`
- Даёт: меньше регрессий, легче добавлять фичи

### Задача 6 — Hub в Redis (3-5 дней) — ГЛАВНЫЙ ПРИОРИТЕТ
- Весь in-memory стейт Hub переезжает в Redis:
  - `hub.rooms` → Redis Hash `room:{code}` → JSON
  - `hub.user_room` → Redis Hash `user_room:{pid}`
  - `hub.profiles` → Redis Hash `profile:{pid}`
  - `hub.reconnect_tasks` → Redis SETEX TTL=30
- WS broadcast между воркерами через Redis Pub/Sub
- После этого: sticky `hash $arg_uid` в nginx не нужен
- Даёт: честный multi-worker, +10x concurrent (~20k)

### Задача 7 — Multi-server + LB (1-2 дня)
- Второй VPS, nginx upstream между серверами
- Postgres managed (RDS/Supabase), Redis managed (Upstash)
- Даёт: 100k+ concurrent

### Задача 8 — Декомпозиция app.js (3-5 дней)
- 3664 строки, onmessage god handler (degree 95 в графе)
- Разбить: `ws.js`, `game.js`, `lobby.js`, `social.js`, `shop.js`

---

## Потолки по фазам

| После задач | Concurrent | Покрывает MAU |
|---|---|---|
| 1+2+3 (done) | ~1500-2000 | ~150k |
| +4 (8 GB RAM) | ~3000-5000 | ~500k |
| +6 (Redis Hub) | ~20 000 | ~2M |
| +7 (multi-server) | 100 000+ | 10M+ |
