# Durak

Multiplayer Russian card game (podkidnoy / perevodnoy) that runs as a **Telegram Mini App**
and in any browser. Real-time rooms over WebSocket, bot opponents, ranks and cosmetics.

## What's inside

- **Game engine** (`server/game.py`) — full rules: attack, defend, throwing in, transferring,
  trump handling, end-of-round resolution.
- **Rooms over WebSocket** (`server/rooms.py`) — the server is the only source of truth;
  clients never decide the outcome of a move.
- **Bot players** (`server/bot_player.py`) — take empty seats so a game starts even with one
  human at the table.
- **Telegram bot** (`server/bot.py`, aiogram) — entry point, Mini App launch, notifications.
- **Progress** — ranks (`server/ranks.py`) and cosmetics (`server/cosmetics.py`).
- **Web client** (`web/`) — plain HTML, CSS and JavaScript, no framework.

## Stack

FastAPI · WebSocket · PostgreSQL (asyncpg) · Redis · aiogram · Prometheus metrics ·
vanilla JS front-end. Deployed behind nginx on a VPS, several uvicorn workers sharing
state through Redis.

## Running locally

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # database, Redis and bot token go here
uvicorn server.main:app --reload --port 8090
```

The web client is served from `web/`; open the app through the Telegram bot or hit the
port directly in a browser.

## Notes

The project grew as a working game for friends, not as a tutorial: the server keeps the
authoritative state, workers coordinate through Redis, and the bots exist because a table
with one player is not a game.
