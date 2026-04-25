"""FastAPI app — static frontend + WebSocket + bot polling task."""
from __future__ import annotations

import asyncio
import base64
import io
import logging
import os
import signal
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import contextlib
import json
import urllib.parse
import urllib.request

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from prometheus_client import Counter, Gauge, Histogram, generate_latest, CONTENT_TYPE_LATEST

from . import game as G
from . import db
from .auth import verify_init_data_cached as verify_init_data
from .bot import run_bot
from .bot_player import BOT_ID, BOT_ID2, BOT_ID3, BOT_IDS
from .cosmetics import ALL_COSMETICS, CATALOG, EMOJI_PACKS, FREE_IDS, make_avatar
from .ranks import get_rank, get_rank_progress
from .rooms import Room, RoomSettings, hub, send_error, send_state

# ── Prometheus metrics ────────────────────────────────────────────────────────
_m_ws_active    = Gauge("durak_ws_active",    "Active WebSocket connections")
_m_rooms_active = Gauge("durak_rooms_active", "Active game rooms")
_m_games_total  = Counter("durak_games_total",  "Games completed", ["result"])  # result: win/draw
_m_ws_errors    = Counter("durak_ws_errors_total", "WebSocket handler exceptions")
_m_db_query     = Histogram("durak_db_seconds", "DB query latency",
                             buckets=[.005, .01, .025, .05, .1, .25, .5, 1.0])
# ──────────────────────────────────────────────────────────────────────────────

# ── DB latency context manager ────────────────────────────────────────────────
@contextlib.asynccontextmanager
async def _db_timer():
    t0 = time.monotonic()
    try:
        yield
    finally:
        _m_db_query.observe(time.monotonic() - t0)

# ── Per-connection rate limiter (in-memory, per-worker) ───────────────────────
# Tracks (count, window_start) per pid; max 20 messages per second.
_rl_state: dict[int, tuple[int, float]] = {}
_RL_MAX = 20
_RL_WINDOW = 1.0

def _rate_limited(pid: int) -> bool:
    """Return True and drop the message if the client is sending too fast."""
    now = time.monotonic()
    count, win_start = _rl_state.get(pid, (0, now))
    if now - win_start >= _RL_WINDOW:
        _rl_state[pid] = (1, now)
        return False
    if count >= _RL_MAX:
        return True
    _rl_state[pid] = (count + 1, win_start)
    return False

# ──────────────────────────────────────────────────────────────────────────────

load_dotenv()
BOT_TOKEN  = os.getenv("BOT_TOKEN", "")
WEBAPP_URL = os.getenv("WEBAPP_URL", "")
HOST       = os.getenv("HOST", "0.0.0.0")
PORT       = int(os.getenv("PORT", "8080"))
_admin_ids_raw = os.getenv("ADMIN_IDS", "")
ADMIN_IDS: set[int] = {int(x.strip()) for x in _admin_ids_raw.split(",") if x.strip().isdigit()}
WEB_DIR    = Path(__file__).resolve().parent.parent / "web"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logging.getLogger("server.fake_players").setLevel(logging.DEBUG)
log = logging.getLogger("durak")

BOT_USERNAME: str | None = None

ACHIEVEMENTS = {
    "first_win":     {"name": "Первая победа",      "desc": "Выиграть первую игру",        "icon": "🏆"},
    "rookie":        {"name": "Новичок",             "desc": "Сыграть 10 игр",              "icon": "🃏"},
    "experienced":   {"name": "Опытный",             "desc": "Сыграть 50 игр",              "icon": "⚔️"},
    "veteran":       {"name": "Ветеран",             "desc": "Сыграть 200 игр",             "icon": "🎖️"},
    "lucky":         {"name": "Везунчик",            "desc": "Выиграть 3 игры подряд",      "icon": "🍀"},
    "rich":          {"name": "Богач",               "desc": "Накопить 50 000 ⬡",           "icon": "💰"},
    "loser_10":      {"name": "Дурак-рекордсмен",   "desc": "Проиграть 10 игр",            "icon": "🤡"},
    "comeback":      {"name": "Возвращение",         "desc": "Победить после 3 поражений",  "icon": "💪"},
    "streak_5":      {"name": "Серия побед",         "desc": "Выиграть 5 игр подряд",       "icon": "🔥"},
    "streak_10":     {"name": "Легенда серии",       "desc": "Выиграть 10 игр подряд",      "icon": "⚡"},
    "centurion":     {"name": "Сотник",              "desc": "Сыграть 100 игр",             "icon": "💯"},
    "thousander":    {"name": "Тысячник",            "desc": "Сыграть 1000 игр",            "icon": "🌟"},
    "sharp":         {"name": "Мастер",              "desc": "50% побед в 30+ играх",       "icon": "🎯"},
    "collector":     {"name": "Коллекционер",        "desc": "Купить 3 скина",              "icon": "🎨"},
    "general_rank":  {"name": "До генерала",         "desc": "Достичь звания Генерал",      "icon": "⭐"},
}


async def _bot_runner() -> None:
    global BOT_USERNAME
    from aiogram import Bot
    from aiogram.client.default import DefaultBotProperties
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    try:
        me = await bot.me()
        BOT_USERNAME = me.username
        log.info("bot @%s ready", BOT_USERNAME)
    finally:
        await bot.session.close()
    await run_bot(BOT_TOKEN, WEBAPP_URL)


async def _room_cleanup_task() -> None:
    while True:
        await asyncio.sleep(60)
        await hub.cleanup_empty_rooms()


async def _pubsub_listener() -> None:
    """Listen for cross-worker match notifications via Redis pub/sub."""
    from .redis_client import get_redis
    import json
    while True:
        try:
            r = await get_redis()
            if not r:
                await asyncio.sleep(5)
                continue
            # Subscribe to a wildcard pattern for all match notifications
            pubsub = r.pubsub()
            await pubsub.psubscribe("durak:match:*")
            async for message in pubsub.listen():
                if message["type"] != "pmessage":
                    continue
                try:
                    channel: str = message["channel"]
                    pid = int(channel.split(":")[-1])
                    data = json.loads(message["data"])
                    room_code = data["room_code"]
                    opp_pid = data["opp_pid"]
                    opp_name = data["opp_name"]

                    # Find the local WebSocket for this pid
                    local_room = hub.room_of(pid)
                    if not local_room:
                        continue
                    p = local_room.get(pid)
                    if not p or not p.ws:
                        continue
                    # Tell the player a match was found — they'll reconnect
                    # and hub.attach() will find them in the new room_code via user_room
                    hub.user_room[pid] = room_code
                    try:
                        await p.ws.send_json({
                            "type": "match_found",
                            "room_code": room_code,
                            "opponent_name": opp_name,
                        })
                    except Exception:
                        pass
                except Exception as e:
                    log.warning("pubsub parse error: %s", e)
        except Exception as e:
            log.warning("pubsub listener error: %s — retrying in 5s", e)
            await asyncio.sleep(5)


async def _is_primary_worker() -> bool:
    """Only one worker should run the bot and fake players. Use Redis lock."""
    from .redis_client import get_redis
    r = await get_redis()
    if not r:
        return PORT == 8090  # fallback: only base port
    try:
        # SET NX with 10s TTL — winner is the primary worker
        acquired = await r.set("durak:primary_worker", PORT, nx=True, ex=10)
        if acquired:
            asyncio.create_task(_renew_primary_lock(r))
            return True
        return False
    except Exception:
        return PORT == 8090


async def _renew_primary_lock(r) -> None:
    """Keep refreshing the primary lock every 5s while this worker is alive."""
    while True:
        await asyncio.sleep(5)
        try:
            await r.set("durak:primary_worker", PORT, ex=10)
        except Exception:
            pass


async def _graceful_shutdown() -> None:
    """Notify all connected players and give them a moment to see it."""
    log.info("graceful shutdown: notifying %d active rooms", len(hub.rooms))
    notify_tasks = []
    for room in list(hub.rooms.values()):
        for p in room.players:
            if p.ws:
                async def _notify(ws=p.ws):
                    try:
                        await ws.send_json({"type": "server_restart", "msg": "Сервер перезагружается, игра продолжится автоматически"})
                    except Exception:
                        pass
                notify_tasks.append(asyncio.create_task(_notify()))
    if notify_tasks:
        await asyncio.gather(*notify_tasks, return_exceptions=True)
        await asyncio.sleep(1.5)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_db()
    log.info("database ready")
    tasks = [
        asyncio.create_task(_room_cleanup_task()),
        asyncio.create_task(_pubsub_listener()),
        asyncio.create_task(hub._room_list_worker()),
    ]
    # Fake players run on ALL workers so every worker's lobby has rooms.
    from .fake_players import start_fake_players
    tasks.append(asyncio.create_task(start_fake_players(hub)))

    # Only the primary worker runs the Telegram bot (one polling instance).
    if await _is_primary_worker():
        log.info("primary worker on port %s — starting bot", PORT)
        if BOT_TOKEN and WEBAPP_URL:
            tasks.append(asyncio.create_task(_bot_runner()))
        else:
            log.warning("BOT_TOKEN or WEBAPP_URL missing — bot disabled")
    else:
        log.info("secondary worker on port %s — fake players running locally", PORT)

    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()

    def _sig_handler():
        if not shutdown_event.is_set():
            shutdown_event.set()
            asyncio.create_task(_graceful_shutdown())

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _sig_handler)
        except NotImplementedError:
            pass

    try:
        yield
    finally:
        await _graceful_shutdown()
        for t in tasks:
            t.cancel()


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(str(WEB_DIR / "index.html"))


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True}


@app.get("/metrics")
async def metrics() -> Response:
    # Update live gauges before scrape
    _m_ws_active.set(sum(
        1 for room in hub.rooms.values()
        for p in room.players if p.ws is not None
    ))
    _m_rooms_active.set(len(hub.rooms))
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


# ────── helpers ──────
async def _fetch_tg_avatar(pid: int, token: str) -> str | None:
    def _sync() -> str | None:
        try:
            params = urllib.parse.urlencode({"user_id": pid, "limit": 1}).encode()
            req = urllib.request.Request(
                f"https://api.telegram.org/bot{token}/getUserProfilePhotos",
                data=params, method="POST",
            )
            with urllib.request.urlopen(req, timeout=8) as r:
                res = json.loads(r.read())
            if not res.get("ok") or not res["result"]["total_count"]:
                return None
            file_id = res["result"]["photos"][0][0]["file_id"]

            params2 = urllib.parse.urlencode({"file_id": file_id}).encode()
            req2 = urllib.request.Request(
                f"https://api.telegram.org/bot{token}/getFile",
                data=params2, method="POST",
            )
            with urllib.request.urlopen(req2, timeout=8) as r2:
                res2 = json.loads(r2.read())
            if not res2.get("ok"):
                return None
            return f"https://api.telegram.org/file/bot{token}/{res2['result']['file_path']}"
        except Exception:
            return None

    return await asyncio.to_thread(_sync)


async def _refresh_avatar(pid: int, ws: "WebSocket | None" = None) -> None:
    if not BOT_TOKEN:
        return
    url = await _fetch_tg_avatar(pid, BOT_TOKEN)
    if not url:
        return
    await db.update_avatar(pid, url)
    if pid in hub.profiles:
        hub.profiles[pid]["avatar_url"] = url
    room = hub.room_of(pid)
    if room:
        p = room.get(pid)
        if p:
            p.avatar_url = url
    if ws:
        try:
            from .cosmetics import make_avatar
            p = hub.profiles.get(pid, {})
            await ws.send_json({"type": "avatar_update", "avatar": make_avatar(pid, p.get("name", ""), url)})
        except Exception:
            pass
    log.info("avatar fetched for %d", pid)


def _resolve_active_emojis(p: dict) -> tuple[list, list]:
    """Returns (text_emojis, img_urls). One of them will be non-empty."""
    user_pack_id = p.get("user_pack")
    if user_pack_id:
        pack_dir = WEB_DIR / "packs" / user_pack_id
        img_urls = [f"/static/packs/{user_pack_id}/{i}.webp"
                    for i in range(6) if (pack_dir / f"{i}.webp").exists()]
        if img_urls:
            return [], img_urls
    pack_id = p.get("emoji_pack", "classic")
    emojis = EMOJI_PACKS.get(pack_id, EMOJI_PACKS["classic"])["emojis"]
    return emojis, []


async def send_lobby(ws: WebSocket, pid: int) -> None:
    p = hub.get_profile(pid)
    emojis, img_urls = _resolve_active_emojis(p)
    await ws.send_json({
        "type": "lobby",
        "id": pid,
        "coins": p["coins"],
        "card_skin": p["card_skin"],
        "table_skin": p["table_skin"],
        "emoji_pack": p.get("emoji_pack", "classic"),
        "user_pack": p.get("user_pack"),
        "emojis": emojis,
        "emoji_imgs": img_urls,
        "name": p.get("name", ""),
        "avatar": make_avatar(pid, p.get("name", ""), p.get("avatar_url")),
        "is_admin": pid in ADMIN_IDS,
    })


async def send_shop(ws: WebSocket, pid: int) -> None:
    p = hub.get_profile(pid)
    owned = list(p.get("owned", []))
    await ws.send_json({
        "type": "shop",
        "coins": p["coins"],
        "card_skin": p["card_skin"],
        "table_skin": p["table_skin"],
        "emoji_pack": p.get("emoji_pack", "classic"),
        "user_pack": p.get("user_pack"),
        "owned": owned,
        "catalog": CATALOG,
    })


async def _check_achievements(ws: WebSocket, pid: int, stats: dict) -> None:
    coins = hub.get_profile(pid).get("coins", 0)
    owned = hub.get_profile(pid).get("owned", [])
    newly_unlocked = []

    async def try_unlock(ach_id: str) -> None:
        if await db.unlock_achievement(pid, ach_id):
            newly_unlocked.append(ach_id)

    if stats["wins"] >= 1:
        await try_unlock("first_win")
    if stats["games"] >= 10:
        await try_unlock("rookie")
    if stats["games"] >= 50:
        await try_unlock("experienced")
    if stats["games"] >= 200:
        await try_unlock("veteran")
    if stats["games"] >= 100:
        await try_unlock("centurion")
    if stats["games"] >= 1000:
        await try_unlock("thousander")
    if stats["streak"] >= 3:
        await try_unlock("lucky")
    if stats["streak"] >= 5:
        await try_unlock("streak_5")
    if stats["streak"] >= 10:
        await try_unlock("streak_10")
    if stats["losses"] >= 10:
        await try_unlock("loser_10")
    if coins >= 50000:
        await try_unlock("rich")
    if stats["games"] >= 30 and stats["wins"] / stats["games"] >= 0.5:
        await try_unlock("sharp")
    owned_count = len([x for x in owned if x not in FREE_IDS])
    if owned_count >= 3:
        await try_unlock("collector")

    rank = get_rank(stats["games"])
    if rank["id"] == "генерал" or rank["id"] == "маршал":
        await try_unlock("general_rank")

    if stats["streak"] <= -3 and stats["wins"] > 0:
        pass

    for ach_id in newly_unlocked:
        ach = ACHIEVEMENTS.get(ach_id, {})
        try:
            await ws.send_json({
                "type": "toast",
                "message": f"Достижение: {ach.get('icon', '')} {ach.get('name', ach_id)}",
            })
        except Exception:
            pass


_PLACE_WEIGHTS = {
    1: [1.0],
    2: [1.0],
    3: [0.70, 0.30],
    4: [0.60, 0.27, 0.13],
}

async def _apply_result(room: Room, ws_map: dict | None = None) -> None:
    state = room.state
    if not state or state.phase != G.Phase.FINISHED:
        return
    if room.result_applied:
        return
    room.result_applied = True
    _m_games_total.labels(result="draw" if state.loser is None else "finished").inc()

    bet = state.bet
    n_players = len(room.players)
    pool = round(bet * 0.9)  # 10% house cut

    # Build placement order: finish_order first, then loser last
    ordered = list(state.finish_order)
    if state.loser is not None and state.loser not in ordered:
        ordered.append(state.loser)
    # Anyone not yet in ordered (edge cases) goes before loser
    for p in room.players:
        if p.pid not in ordered:
            ordered.insert(-1 if state.loser is not None else len(ordered), p.pid)

    n_winners = max(1, len(ordered) - 1) if state.loser is not None else len(ordered)
    weights = _PLACE_WEIGHTS.get(n_players, _PLACE_WEIGHTS[4])

    # payout[pid] = delta coins
    payout: dict[int, int] = {}
    if state.loser is None:
        # Draw — no coins change
        for p in room.players:
            payout[p.pid] = 0
    else:
        payout[state.loser] = -bet
        for rank, pid in enumerate(ordered[:-1]):  # everyone except last
            w = weights[rank] if rank < len(weights) else 0
            payout[pid] = max(1, round(pool * w))

    place_map = {pid: i + 1 for i, pid in enumerate(ordered)}

    for p in room.players:
        if p.pid in BOT_IDS:
            continue
        delta = payout.get(p.pid, 0)
        place = place_map.get(p.pid, n_players)
        result = "draw" if state.loser is None else (
            "win" if place == 1 else ("loss" if p.pid == state.loser else "mid")
        )
        if delta != 0:
            async with _db_timer():
                new_coins = await db.adjust_coins(p.pid, delta)
        else:
            async with _db_timer():
                new_coins = await db.get_coins(p.pid)
        p.coins = new_coins
        if p.pid in hub.profiles:
            hub.profiles[p.pid]["coins"] = new_coins
            asyncio.create_task(hub._redis_set_profile(p.pid, hub.profiles[p.pid]))

        db_result = "win" if result == "win" else ("loss" if result == "loss" else "draw")
        async with _db_timer():
            stats = await db.update_stats(p.pid, db_result)

        if ws_map and p.pid in ws_map:
            await _check_achievements(ws_map[p.pid], p.pid, stats)

    # Store payout in state so frontend can display per-player coins
    state.payouts = payout


async def _ensure_coins(ws: WebSocket, pid: int, name: str, min_bet: int = db.COIN_BET) -> bool:
    profile = hub.get_profile(pid)
    if profile["coins"] < min_bet:
        await send_error(ws, f"Недостаточно средств: нужно {min_bet:,} ⬡, у вас {profile['coins']:,} ⬡")
        return False
    return True


async def _send_invite_tg(to_id: int, from_name: str, code: str, bet: int, deck_size: int, mode: str) -> bool:
    if not BOT_TOKEN or not BOT_USERNAME or not WEBAPP_URL:
        return False
    try:
        from aiogram import Bot
        from aiogram.client.default import DefaultBotProperties
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
        mode_label = "переводной" if mode == "perevodnoy" else "подкидной"
        bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
        try:
            sep = "&" if "?" in WEBAPP_URL else "?"
            app_url = f"{WEBAPP_URL}{sep}tgWebAppStartParam=r_{code}"
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="🃏 Войти в игру", web_app=WebAppInfo(url=app_url))
            ]])
            text = (
                f"🃏 <b>{from_name}</b> приглашает тебя сыграть в <b>Дурак</b>!\n"
                f"Ставка: <b>{bet:,} ⬡</b> · {deck_size} карт · {mode_label}"
            )
            await bot.send_message(to_id, text, reply_markup=kb)
            return True
        finally:
            await bot.session.close()
    except Exception as e:
        log.warning("invite send failed to %d: %s", to_id, e)
        return False


# ────── WebSocket ──────
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    user = None
    try:
        first = await ws.receive_json()
        if first.get("type") != "hello":
            await send_error(ws, "ожидался hello")
            await ws.close()
            return

        init_data = first.get("initData", "")
        if BOT_TOKEN:
            user = await verify_init_data(init_data, BOT_TOKEN)
            if not user:
                await send_error(ws, "невалидный initData")
                await ws.close()
                return
        else:
            user = {
                "id": int(first.get("dev_id", 0)),
                "first_name": first.get("dev_name", "guest"),
                "username": None,
                "start_param": first.get("start_param"),
            }
            if not user["id"]:
                await send_error(ws, "dev_id обязателен в режиме разработки")
                await ws.close()
                return

        pid = user["id"]
        name = user["first_name"] or (user.get("username") or f"#{pid}")
        username = user.get("username")
        start_param = user.get("start_param") or first.get("start_param")

        async with _db_timer():
            profile = await db.upsert_user(pid, name, username)
        async with _db_timer():
            owned_list = await db.get_owned_cosmetics(pid)
        for fid in FREE_IDS:
            if fid not in owned_list:
                owned_list.append(fid)

        hub.store_profile(pid, profile, owned_list)
        # Pull fresh profile from Redis if this worker doesn't have it yet (multi-worker reconnect)
        await hub.refresh_profile_from_redis(pid)
        # Cache rank/games for in-game display
        async with _db_timer():
            _stats = await db.get_stats(pid)
        _rank = get_rank(_stats.get("games", 0))
        hub.profiles[pid]["games"] = _stats.get("games", 0)
        hub.profiles[pid]["pogon"] = _rank["pogon"]
        hub.profiles[pid]["rank_title"] = _rank["title"]
        asyncio.create_task(hub._redis_set_profile(pid, hub.profiles[pid]))

        if BOT_TOKEN:
            asyncio.create_task(_refresh_avatar(pid, ws))

        bonus_awarded, bonus_coins = await db.claim_daily_bonus(pid)
        if bonus_awarded:
            await ws.send_json({"type": "daily_bonus", "coins": bonus_coins})

        room = await hub.attach(pid, name, ws)
        profile_param = None
        if room:
            await send_state(room, BOT_USERNAME)
        elif start_param:
            if start_param == "create":
                room = await hub.create_private(pid, name, ws)
            elif start_param.startswith("r_"):
                # Room invite link (prefixed with r_)
                room = await hub.join_private(start_param[2:], pid, name, ws)
                if not room:
                    await send_error(ws, "комната не найдена или заполнена")
            else:
                # Treat as username → open profile after lobby
                profile_param = start_param
            if room:
                await send_state(room, BOT_USERNAME)

        if not room:
            await send_lobby(ws, pid)
            if profile_param:
                urow = await db.get_user_by_username(profile_param)
                if urow:
                    tid = urow["id"]
                    tstats = await db.get_stats(tid)
                    trank = get_rank(tstats.get("games", 0))
                    tprog = get_rank_progress(tstats.get("games", 0))
                    tavatar = make_avatar(tid, urow["name"], urow["avatar_url"])
                    await ws.send_json({
                        "type": "open_friend_profile",
                        "id": tid,
                        "name": urow["name"],
                        "username": profile_param,
                        "avatar": tavatar,
                        "stats": tstats,
                        "rank": trank,
                        "rank_progress": tprog,
                    })

        _m_ws_active.inc()
        try:
            while True:
                msg = await ws.receive_json()
                if _rate_limited(pid):
                    continue
                await handle(ws, pid, name, msg)
        finally:
            _m_ws_active.dec()

    except WebSocketDisconnect:
        pass
    except Exception as e:
        log.exception("ws error: %s", e)
        _m_ws_errors.inc()
    finally:
        hub.remove_watcher(ws)
        if user:
            await hub.detach(user["id"])


async def handle(ws: WebSocket, pid: int, name: str, msg: dict) -> None:
    t = msg.get("type")
    room: Room | None

    # ── Lobby navigation ──
    if t == "vs_bot":
        if not await _ensure_coins(ws, pid, name):
            return
        num_bots = max(1, min(3, int(msg.get("num_bots", 1))))
        room = await hub.vs_bot(pid, name, ws, num_bots=num_bots)
        hub.start_bot_task(room)
        await send_state(room, BOT_USERNAME)
        return

    if t == "quick":
        if not await _ensure_coins(ws, pid, name):
            return
        # Join existing open room (bet=100) or create one
        room = None
        async with hub._lock:
            for r in hub.rooms.values():
                if r.private or r.state is not None:
                    continue
                max_p = r.settings.max_players if r.settings else 2
                if len(r.players) >= max_p:
                    continue
                if r.settings and r.settings.bet != 100:
                    continue
                if not r.has(pid):
                    hub._evict(pid)
                    me = hub._make_player(pid, name, ws)
                    r.players.append(me)
                    r.last_activity = time.time()
                    hub.user_room[pid] = r.code
                    room = r
                    break
        if room is None:
            room = await hub.create_room_with_settings(
                pid, name, ws,
                RoomSettings(bet=100, max_players=2, deck_size=36, mode="perevodnoy"),
            )
            room.private = False
        hub.queue_room_list_broadcast()
        await send_state(room, BOT_USERNAME)
        return

    if t == "create":
        if not await _ensure_coins(ws, pid, name):
            return
        room = await hub.create_private(pid, name, ws)
        await send_state(room, BOT_USERNAME)
        return

    if t == "create_game":
        bet = int(msg.get("bet", 100))
        if not await _ensure_coins(ws, pid, name, min_bet=bet):
            return
        settings = RoomSettings(
            bet=int(msg.get("bet", 100)),
            max_players=int(msg.get("max_players", 2)),
            deck_size=int(msg.get("deck_size", 36)),
            mode=msg.get("mode", "perevodnoy"),
            password=msg.get("password", ""),
        )
        is_private = bool(msg.get("private", False)) or bool(settings.password)
        room = await hub.create_room_with_settings(pid, name, ws, settings)
        room.private = is_private
        await send_state(room, BOT_USERNAME)
        return

    if t == "join":
        code = (msg.get("code") or "").strip()
        room = await hub.join_private(code, pid, name, ws)
        if not room:
            await send_error(ws, "комната не найдена")
            return
        await send_state(room, BOT_USERNAME)
        return

    if t == "join_open":
        code = (msg.get("code") or "").strip()
        room = await hub.join_open_room(code, pid, name, ws)
        if not room:
            await send_error(ws, "комната не найдена или заполнена")
            return
        await send_state(room, BOT_USERNAME)
        return

    if t == "speed_up":
        room = hub.room_of(pid)
        if room and room.state and room.state.phase == G.Phase.PLAYING:
            room.speed_up = True
            from .rooms import _reset_turn_timer
            _reset_turn_timer(room)  # restart timer — new task will exit after 3s
        return

    if t == "room_list":
        hub.add_watcher(ws)
        open_rooms = await hub.list_open_rooms()
        private_rooms = await hub.list_private_rooms()
        await ws.send_json({
            "type": "room_list",
            "open": open_rooms,
            "private": private_rooms,
        })
        return

    if t == "room_list_unwatch":
        hub.remove_watcher(ws)
        return

    if t == "cancel":
        await hub.cancel_queue(pid)
        await send_lobby(ws, pid)
        return

    if t == "leave":
        room = await hub.leave(pid)
        if room and room.state and room.state.phase == G.Phase.FINISHED:
            ws_map = {p.pid: p.ws for p in room.players if p.ws}
            ws_map[pid] = ws
            await _apply_result(room, ws_map)
        await send_lobby(ws, pid)
        if room:
            await send_state(room, BOT_USERNAME)
        return

    if t == "rematch":
        room = await hub.rematch(pid)
        if room:
            if room.state and room.state.phase == G.Phase.PLAYING:
                hub.start_bot_task(room)
            await send_state(room, BOT_USERNAME)
        else:
            await send_lobby(ws, pid)
        return

    if t == "surrender":
        room = hub.room_of(pid)
        if room and room.state and room.state.phase == G.Phase.PLAYING:
            room.state.phase = G.Phase.FINISHED
            room.state.loser = pid
            from .rooms import BOT_IDS as _BOT_IDS
            surviving = next((p for p in room.players if p.pid != pid and p.pid not in _BOT_IDS), None)
            room.state.winner = surviving.pid if surviving else None
            ws_map = {p.pid: p.ws for p in room.players if p.ws}
            ws_map[pid] = ws
            await _apply_result(room, ws_map)
            await send_state(room, BOT_USERNAME)
        return

    # ── Shop ──
    if t == "shop_open":
        await send_shop(ws, pid)
        return

    if t == "buy":
        cosmetic_id = msg.get("cosmetic_id", "")
        item = ALL_COSMETICS.get(cosmetic_id)
        if not item:
            await send_error(ws, "товар не найден")
            return
        ok, new_coins = await db.buy_cosmetic(pid, cosmetic_id, item["price"])
        if not ok:
            await send_error(ws, "недостаточно монет")
            return
        await db.set_active_skin(pid, item["kind"], item["skin_id"])
        if pid in hub.profiles:
            hub.profiles[pid]["coins"] = new_coins
            if cosmetic_id not in hub.profiles[pid].get("owned", []):
                hub.profiles[pid].setdefault("owned", []).append(cosmetic_id)
            if item["kind"] == "card":
                hub.profiles[pid]["card_skin"] = item["skin_id"]
            elif item["kind"] == "emoji":
                hub.profiles[pid]["emoji_pack"] = item["skin_id"]
            else:
                hub.profiles[pid]["table_skin"] = item["skin_id"]
            asyncio.create_task(hub._redis_set_profile(pid, hub.profiles[pid]))
        room = hub.room_of(pid)
        if room:
            p = room.get(pid)
            if p:
                p.coins = new_coins
                if item["kind"] == "card":
                    p.card_skin = item["skin_id"]
                elif item["kind"] == "emoji":
                    p.emoji_pack = item["skin_id"]
                else:
                    p.table_skin = item["skin_id"]
        stats = await db.get_stats(pid)
        await _check_achievements(ws, pid, stats)
        await send_shop(ws, pid)
        return

    if t == "equip":
        cosmetic_id = msg.get("cosmetic_id", "")
        item = ALL_COSMETICS.get(cosmetic_id)
        profile = hub.get_profile(pid)
        if not item or cosmetic_id not in profile.get("owned", []):
            await send_error(ws, "скин недоступен")
            return
        await db.set_active_skin(pid, item["kind"], item["skin_id"])
        if pid in hub.profiles:
            if item["kind"] == "card":
                hub.profiles[pid]["card_skin"] = item["skin_id"]
            elif item["kind"] == "emoji":
                hub.profiles[pid]["emoji_pack"] = item["skin_id"]
            else:
                hub.profiles[pid]["table_skin"] = item["skin_id"]
            asyncio.create_task(hub._redis_set_profile(pid, hub.profiles[pid]))
        room = hub.room_of(pid)
        if room:
            p = room.get(pid)
            if p:
                if item["kind"] == "card":
                    p.card_skin = item["skin_id"]
                elif item["kind"] == "emoji":
                    p.emoji_pack = item["skin_id"]
                else:
                    p.table_skin = item["skin_id"]
        await send_shop(ws, pid)
        return

    # ── Ready check ──
    if t == "ready":
        room = await hub.mark_ready(pid)
        if not room:
            return
        if room.state:
            if any(p.pid == BOT_ID for p in room.players):
                hub.start_bot_task(room)
        await send_state(room, BOT_USERNAME)
        return

    # ── Emoji reaction ──
    if t == "emoji":
        emoji = msg.get("emoji", "")
        ALLOWED_EMOJI = {"👍", "😂", "🤡", "🔥", "😤", "🫡"}
        profile = hub.get_profile(pid)
        user_pack_id = profile.get("user_pack")
        is_custom = (
            user_pack_id
            and isinstance(emoji, str)
            and emoji.startswith(f"/static/packs/{user_pack_id}/")
            and emoji.endswith(".webp")
        )
        if emoji not in ALLOWED_EMOJI and not is_custom:
            return
        room = hub.room_of(pid)
        if not room:
            return
        for p in room.players:
            if p.pid != pid and p.ws:
                try:
                    await p.ws.send_json({"type": "emoji", "emoji": emoji, "from": pid})
                except Exception:
                    pass
        return

    # ── User Packs ──
    if t == "pack_submit":
        # Limit: 1 pending pack per user
        my_packs = await db.get_my_packs(pid)
        if any(p["status"] == "pending" for p in my_packs):
            await send_error(ws, "у тебя уже есть пак на модерации — дождись решения")
            return
        name = (msg.get("name") or "").strip()[:32]
        if not name:
            await send_error(ws, "укажи название пака")
            return
        price = int(msg.get("price", 500))
        if price not in (500, 1000, 2500, 5000):
            price = 500
        supply = int(msg.get("supply", 0))
        if supply not in (0, 100, 500):
            supply = 0
        images_b64: list = msg.get("images", [])
        if not (3 <= len(images_b64) <= 6):
            await send_error(ws, "нужно от 3 до 6 изображений")
            return
        pack_id = str(uuid.uuid4())
        pack_dir = WEB_DIR / "packs" / pack_id
        pack_dir.mkdir(parents=True, exist_ok=True)
        try:
            from PIL import Image as PilImage
            for i, data_url in enumerate(images_b64):
                if "," in data_url:
                    data_url = data_url.split(",", 1)[1]
                raw = base64.b64decode(data_url)
                img = PilImage.open(io.BytesIO(raw)).convert("RGBA")
                img.thumbnail((128, 128), PilImage.LANCZOS)
                img.save(pack_dir / f"{i}.webp", "WEBP", quality=85)
        except Exception as e:
            import shutil; shutil.rmtree(pack_dir, ignore_errors=True)
            await send_error(ws, f"ошибка обработки изображений: {e}")
            return
        await db.create_user_pack(pack_id, pid, name, price, supply)
        await ws.send_json({"type": "pack_submitted", "pack_id": pack_id,
                            "message": "Пак отправлен на модерацию ✓"})
        return

    if t == "pack_market":
        rows = await db.get_user_packs_market()
        owned = await db.get_owned_user_packs(pid)
        await ws.send_json({"type": "pack_market_data", "packs": rows, "owned": owned,
                            "your_id": pid})
        return

    if t == "pack_buy":
        pack_id = msg.get("pack_id", "")
        if not pack_id:
            return
        ok, err = await db.buy_user_pack(pack_id, pid, 0)
        if not ok:
            await send_error(ws, err)
            return
        # Update in-memory coins
        new_coins = await db.get_coins(pid)
        if pid in hub.profiles:
            hub.profiles[pid]["coins"] = new_coins
        await ws.send_json({"type": "pack_bought", "pack_id": pack_id, "coins": new_coins})
        return

    if t == "pack_equip":
        pack_id = msg.get("pack_id", "")
        owned = await db.get_owned_user_packs(pid)
        my_packs = await db.get_my_packs(pid)
        is_creator = any(p["id"] == pack_id for p in my_packs)
        if pack_id not in owned and not is_creator:
            await send_error(ws, "пак не куплен")
            return
        await db.set_active_skin(pid, "user_pack", pack_id)
        if pid in hub.profiles:
            hub.profiles[pid]["user_pack"] = pack_id
            hub.profiles[pid]["emoji_pack"] = ""  # clear built-in pack
            asyncio.create_task(hub._redis_set_profile(pid, hub.profiles[pid]))
        room = hub.room_of(pid)
        if room:
            p_obj = room.get(pid)
            if p_obj:
                p_obj.user_pack = pack_id
                p_obj.emoji_pack = ""
        pack_dir = WEB_DIR / "packs" / pack_id
        img_urls = [f"/static/packs/{pack_id}/{i}.webp"
                    for i in range(6) if (pack_dir / f"{i}.webp").exists()]
        await ws.send_json({"type": "pack_equipped", "pack_id": pack_id, "img_urls": img_urls})
        return

    if t == "my_packs":
        packs = await db.get_my_packs(pid)
        owned = await db.get_owned_user_packs(pid)
        await ws.send_json({"type": "my_packs_data", "packs": packs, "owned": owned})
        return

    if t == "pack_approve" and pid in ADMIN_IDS:
        await db.set_pack_status(msg.get("pack_id", ""), "approved")
        rows = await db.get_user_packs_pending()
        await ws.send_json({"type": "packs_pending", "packs": rows})
        return

    if t == "pack_reject" and pid in ADMIN_IDS:
        await db.set_pack_status(msg.get("pack_id", ""), "rejected")
        rows = await db.get_user_packs_pending()
        await ws.send_json({"type": "packs_pending", "packs": rows})
        return

    if t == "packs_pending_get" and pid in ADMIN_IDS:
        rows = await db.get_user_packs_pending()
        await ws.send_json({"type": "packs_pending", "packs": rows})
        return

    # ── Profile ──
    if t == "profile_get":
        target_id = msg.get("target_id", pid)
        BOT_STATS = {
            BOT_ID:  {"games": 7,  "wins": 3,  "losses": 4,  "draws": 0, "streak": -1, "best_streak": 2},
            BOT_ID2: {"games": 15, "wins": 8,  "losses": 7,  "draws": 0, "streak": 2,  "best_streak": 5},
            BOT_ID3: {"games": 30, "wins": 18, "losses": 12, "draws": 0, "streak": 3,  "best_streak": 7},
        }
        if target_id in BOT_IDS:
            stats = BOT_STATS[target_id]
            rank_data = get_rank_progress(stats["games"])
            unlocked = []
        else:
            stats = await db.get_stats(target_id)
            rank_data = get_rank_progress(stats["games"])
            unlocked = await db.get_achievements(target_id)
        await ws.send_json({
            "type": "profile_data",
            "stats": stats,
            "rank": rank_data["current"],
            "rank_progress": rank_data,
            "achievements": unlocked,
            "target_id": target_id,
        })
        return

    # ── Leaderboard ──
    if t == "leaderboard_get":
        sort = msg.get("sort", "games")
        async with _db_timer():
            rows = await db.get_leaderboard(50, sort=sort)
        for r in rows:
            rank = get_rank(r["games"])
            r["rank_title"] = rank["title"]
            r["pogon"] = rank["pogon"]
        await ws.send_json({"type": "leaderboard_data", "rows": rows, "your_id": pid, "sort": sort})
        return

    # ── Clan leaderboard ──
    if t == "clan_leaderboard_get":
        sort = msg.get("sort", "games")
        async with _db_timer():
            rows = await db.get_clan_leaderboard(sort=sort)
        await ws.send_json({"type": "clan_leaderboard_data", "rows": rows, "sort": sort})
        return

    # ── Clan ──
    if t == "clan_get":
        async with _db_timer():
            clan = await db.get_my_clan(pid)
        await ws.send_json({"type": "clan_data", "clan": clan})
        return

    if t == "clan_create":
        name = (msg.get("name") or "").strip()
        username = (msg.get("username") or "").strip()
        description = (msg.get("description") or "").strip()
        if not name:
            await send_error(ws, "Укажите название клана")
            return
        if not username:
            await send_error(ws, "Укажите юзернейм клана")
            return
        if len(name) > 32:
            await send_error(ws, "Название клана не длиннее 32 символов")
            return
        ok, err, clan_row = await db.create_clan(pid, name, username or None, description)
        if not ok:
            await send_error(ws, err)
            return
        clan = await db.get_my_clan(pid)
        await ws.send_json({"type": "clan_data", "clan": clan})
        return

    if t == "clan_join":
        username = (msg.get("username") or "").strip()
        if not username:
            await send_error(ws, "Укажите username клана")
            return
        ok, err, _ = await db.join_clan(pid, username)
        if not ok:
            await send_error(ws, err)
            return
        clan = await db.get_my_clan(pid)
        await ws.send_json({"type": "clan_data", "clan": clan})
        return

    if t == "clan_leave":
        await db.leave_clan(pid)
        await ws.send_json({"type": "clan_data", "clan": None})
        return

    # ── Friends ──
    if t == "friend_list":
        friends = await db.get_friends(pid)
        incoming = await db.get_incoming_requests(pid)
        await ws.send_json({"type": "friend_list", "friends": friends, "incoming": incoming})
        return

    if t == "friend_add":
        username = (msg.get("username") or "").strip().lstrip("@")
        if not username:
            await send_error(ws, "укажите username")
            return
        row = await db.get_user_by_username(username)
        if not row:
            await send_error(ws, "пользователь не найден")
            return
        friend_id = row["id"]
        if friend_id == pid:
            await send_error(ws, "нельзя добавить себя")
            return
        result = await db.add_friend_request(pid, friend_id)
        await ws.send_json({"type": "toast", "message": "Запрос отправлен" if result == "sent" else "Теперь вы друзья!"})
        friends = await db.get_friends(pid)
        incoming = await db.get_incoming_requests(pid)
        await ws.send_json({"type": "friend_list", "friends": friends, "incoming": incoming})
        return

    if t == "friend_accept":
        from_id = int(msg.get("from_id", 0))
        if from_id:
            await db.accept_friend(pid, from_id)
        friends = await db.get_friends(pid)
        incoming = await db.get_incoming_requests(pid)
        await ws.send_json({"type": "friend_list", "friends": friends, "incoming": incoming})
        await ws.send_json({"type": "toast", "message": "Теперь вы друзья! 🤝"})
        return

    if t == "friend_decline":
        from_id = int(msg.get("from_id", 0))
        if from_id:
            await db.remove_friend(pid, from_id)
        friends = await db.get_friends(pid)
        incoming = await db.get_incoming_requests(pid)
        await ws.send_json({"type": "friend_list", "friends": friends, "incoming": incoming})
        return

    if t == "friend_remove":
        friend_id = int(msg.get("friend_id", 0))
        if friend_id:
            await db.remove_friend(pid, friend_id)
        friends = await db.get_friends(pid)
        incoming = await db.get_incoming_requests(pid)
        await ws.send_json({"type": "friend_list", "friends": friends, "incoming": incoming})
        return

    if t == "user_search":
        query = (msg.get("query") or "").strip().lstrip("@")
        if len(query) < 1:
            await ws.send_json({"type": "user_search_result", "users": []})
            return
        results = await db.search_users(query, limit=8)
        # Exclude self
        results = [r for r in results if r["id"] != pid]
        await ws.send_json({"type": "user_search_result", "users": results})
        return

    if t == "profile_by_username":
        target_username = (msg.get("username") or "").strip().lstrip("@")
        urow = await db.get_user_by_username(target_username)
        if not urow:
            await send_error(ws, "пользователь не найден")
            return
        tid = urow["id"]
        tstats = await db.get_stats(tid)
        trank = get_rank(tstats.get("games", 0))
        tprog = get_rank_progress(tstats.get("games", 0))
        tavatar = make_avatar(tid, urow["name"], urow["avatar_url"])
        await ws.send_json({
            "type": "profile_by_username",
            "id": tid,
            "name": urow["name"],
            "username": target_username,
            "avatar": tavatar,
            "stats": tstats,
            "rank": trank,
            "rank_progress": tprog,
        })
        return

    # ── Achievements ──
    if t == "achievements_get":
        unlocked = await db.get_achievements(pid)
        await ws.send_json({
            "type": "achievements_data",
            "unlocked": unlocked,
            "all": list(ACHIEVEMENTS.keys()),
        })
        return

    # ── Friend invite ──
    if t == "get_friends_for_invite":
        room = hub.room_of(pid)
        if not room:
            await send_error(ws, "вы не в комнате")
            return
        friends = await db.get_friends(pid)
        accepted = [f for f in friends if f["status"] == "accepted"]
        s = room.settings or __import__("server.rooms", fromlist=["RoomSettings"]).RoomSettings()
        await ws.send_json({
            "type": "invite_friends_list",
            "friends": accepted,
            "code": room.code,
            "bet": s.bet,
        })
        return

    if t == "invite_friend":
        friend_id = int(msg.get("friend_id", 0))
        room = hub.room_of(pid)
        if not room:
            await send_error(ws, "вы не в комнате")
            return
        friends = await db.get_friends(pid)
        if not any(f["friend_id"] == friend_id and f["status"] == "accepted" for f in friends):
            await send_error(ws, "пользователь не в списке друзей")
            return
        s = room.settings or __import__("server.rooms", fromlist=["RoomSettings"]).RoomSettings()
        ok = await _send_invite_tg(friend_id, name, room.code, s.bet, s.deck_size, s.mode)
        if ok:
            await ws.send_json({"type": "toast", "message": "Приглашение отправлено! 📨"})
        else:
            await send_error(ws, "Не удалось отправить — друг ещё не запускал бота")
        return

    # ── Admin ──
    if t == "admin_get" and pid in ADMIN_IDS:
        stats = await db.get_stats(pid)
        rank = get_rank(stats.get("games", 0))
        rank_prog = get_rank_progress(stats.get("games", 0))
        coins = hub.get_profile(pid).get("coins", 0)
        await ws.send_json({
            "type": "admin_data",
            "stats": stats,
            "rank": rank,
            "rank_progress": rank_prog,
            "coins": coins,
            "is_admin": True,
        })
        return

    if t == "admin_set" and pid in ADMIN_IDS:
        field_name = msg.get("field")
        value = msg.get("value")
        if field_name == "games":
            new_games = max(0, int(value))
            # Overwrite stats with new game count keeping wins/losses ratio
            stats = await db.get_stats(pid)
            delta = new_games - stats.get("games", 0)
            await db.admin_set_games(pid, new_games)
            rank = get_rank(new_games)
            hub.profiles[pid]["games"] = new_games
            hub.profiles[pid]["pogon"] = rank["pogon"]
            hub.profiles[pid]["rank_title"] = rank["title"]
        elif field_name == "coins":
            new_coins = max(0, int(value))
            await db.admin_set_coins(pid, new_coins)
            hub.profiles[pid]["coins"] = new_coins
            p = hub.room_of(pid)
            if p:
                pl = p.get(pid)
                if pl:
                    pl.coins = new_coins
        elif field_name == "wins":
            await db.admin_set_stat(pid, "wins", max(0, int(value)))
        # Refresh and send updated data
        stats = await db.get_stats(pid)
        rank = get_rank(stats.get("games", 0))
        rank_prog = get_rank_progress(stats.get("games", 0))
        coins = hub.get_profile(pid).get("coins", 0)
        await ws.send_json({
            "type": "admin_data",
            "stats": stats,
            "rank": rank,
            "rank_progress": rank_prog,
            "coins": coins,
            "is_admin": True,
        })
        await ws.send_json({"type": "toast", "message": "✅ Обновлено"})
        return

    # ── Game actions ──
    room = hub.room_of(pid)
    if not room or not room.state:
        await send_error(ws, "вы не в игре")
        return

    state = room.state
    prev_phase = state.phase

    ws_map = {}
    for p in room.players:
        if p.ws:
            ws_map[p.pid] = p.ws
    ws_map[pid] = ws

    try:
        if t == "attack":
            G.attack(state, pid, msg["card"])
        elif t == "defend":
            G.defend(state, pid, msg["attack"], msg["card"])
        elif t == "transfer":
            G.transfer(state, pid, msg["card"])
        elif t == "take":
            G.take(state, pid)
        elif t == "done":
            G.done(state, pid)
        elif t == "pass":
            G.pass_turn(state, pid)
        elif t == "recall":
            profile = hub.get_profile(pid)
            if profile.get("coins", 0) < 1000:
                await send_error(ws, "Недостаточно монет: нужно 1000 ⬡")
                return
            G.recall(state, pid)
            new_coins = await db.adjust_coins(pid, -1000)
            p_obj = room.get(pid)
            if p_obj:
                p_obj.coins = new_coins
            if pid in hub.profiles:
                hub.profiles[pid]["coins"] = new_coins
        else:
            await send_error(ws, f"неизвестный тип: {t}")
            return
    except G.GameError as e:
        await send_error(ws, str(e))
        return

    if prev_phase == G.Phase.PLAYING and state.phase == G.Phase.FINISHED:
        await _apply_result(room, ws_map)

    await send_state(room, BOT_USERNAME)


def main() -> None:
    import uvicorn
    uvicorn.run("server.main:app", host=HOST, port=PORT, reload=False)


if __name__ == "__main__":
    main()
