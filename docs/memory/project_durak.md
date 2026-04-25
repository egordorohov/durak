---
name: Durak Card Game — Current State
description: /root/durak — Telegram Mini App дурак 2-4 игрока, текущий стек, фичи и архитектура
type: project
updated: 2026-04-25
originSessionId: ab619c64-388c-47af-b3cc-8e0ed501f551
---
## Проект

`/root/durak/` — Telegram Mini App, подкидной/переводной дурак, 2-4 игрока, 36/52 карт.
Деплой: `bash restart.sh` → 4 uvicorn воркера на портах 8090-8093, nginx раздаёт на gatgames.fun.

- **Frontend**: `web/index.html`, `web/style.css`, `web/app.js?v=52`
- **Backend**: `server/` — FastAPI, WebSocket, PostgreSQL, Redis
- **Граф**: `docs/graph/graph.html` (438 nodes, 1107 edges)

---

## Стек

- FastAPI + uvicorn (4 воркера), nginx `hash $arg_uid consistent` sticky routing
- PostgreSQL (asyncpg, pool max_size=30), Redis (auth cache + pub/sub + matchmaking)
- Prometheus метрики на `/metrics`, Grafana на grafana.gatgames.fun (admin/admin123)
- Фейк-боты: 1000 профилей в DB, 80 активных на воркер, 3 sentinel-бота держат открытые комнаты

---

## Реализованные фичи

- Мобильный layout, тёмная/светлая тема
- Козырь, таймер хода 30с, авто-действие
- Лобби: быстрая игра, против бота, создать игру (2-4 игрока, 36/52 карт, режим, пароль)
- Ready check, переводной дурак, пас для 3-4 игроков
- Профиль с рангами (14 рангов, погоны), статистика, достижения (15 видов)
- Друзья, клан система, лидерборд (игроки/кланы × игры/монеты)
- Магазин: скины карт/стола, emoji packs, marketplace пользовательских стикер-паков
- Внутренняя валюта, анимации карт, звуки
- Admin Panel (ADMIN_IDS)
- Graceful shutdown (SIGTERM → broadcast server_restart → reconnect на клиенте)
- Rate limiting 20 msg/s per player

---

## Архитектура файлов

- `game.py` — игровая логика (attack/defend/transfer/take/done/pass_turn)
- `rooms.py` — Hub, matchmaking, Room, ready check, send_state, broadcast
- `main.py` — FastAPI WS handler, handle() god function (~700 строк, degree 76)
- `db.py` — PostgreSQL: users, stats, cosmetics, achievements, friends, clans
- `fake_players.py` — 1000 фейк-профилей, sentinel боты, bot loops
- `bot_player.py` — AI бот (run_bot async loop)
- `auth.py` — Telegram initData verify + Redis session cache
- `ranks.py` — 14 военных рангов, get_rank(), get_rank_progress()
- `redis_client.py` — get_redis() singleton
