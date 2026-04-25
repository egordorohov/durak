"""Rooms, matchmaking queue, WS broadcasting."""
from __future__ import annotations

import asyncio
import json
import secrets
import time
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

from fastapi import WebSocket

from . import game as G
from . import db as db_mod
from .bot_player import BOT_ID, BOT_ID2, BOT_ID3, BOT_IDS, BOT_NAMES, run_bot
from .fake_players import FAKE_IDS
from .cosmetics import EMOJI_PACKS, make_avatar
from .ranks import get_rank
from .redis_client import get_redis

PROFILE_TTL = 3600   # Redis profile cache TTL — 1 hour
QUEUE_TTL   = 60     # How long a queue entry lives before expiring (stale player)

RECONNECT_TIMEOUT = 30
TURN_TIMEOUT = 30  # seconds before server forces an action


@dataclass
class RoomSettings:
    bet: int = 100
    max_players: int = 2
    deck_size: int = 36
    mode: str = "perevodnoy"
    password: str = ""


@dataclass
class Player:
    pid: int
    name: str
    ws: Optional[WebSocket] = None
    coins: int = 5000
    card_skin: str = "classic"
    table_skin: str = "default"
    emoji_pack: str = "classic"
    user_pack: str = ""
    avatar_url: str | None = None
    owned: list[str] = field(default_factory=list)


EMPTY_ROOM_TTL = 300  # seconds before empty room is deleted

@dataclass
class Room:
    code: str
    players: list[Player] = field(default_factory=list)
    state: Optional[G.GameState] = None
    private: bool = False
    bot_task: Optional[asyncio.Task] = None
    ready_players: set = field(default_factory=set)
    settings: RoomSettings = field(default_factory=RoomSettings)
    result_applied: bool = False
    last_activity: float = field(default_factory=time.time)
    turn_started_at: float = 0.0
    speed_up: bool = False

    def has(self, pid: int) -> bool:
        return any(p.pid == pid for p in self.players)

    def get(self, pid: int) -> Optional[Player]:
        return next((p for p in self.players if p.pid == pid), None)


class Hub:
    def __init__(self) -> None:
        self.rooms: dict[str, Room] = {}
        self.user_room: dict[int, str] = {}
        self.queue: list[Player] = []
        self.profiles: dict[int, dict] = {}
        self._lock = asyncio.Lock()
        self.reconnect_tasks: dict[int, asyncio.Task] = {}
        self.turn_timers: dict[str, asyncio.Task] = {}
        self.room_watchers: set[WebSocket] = set()
        self._room_list_pending: bool = False

    def add_watcher(self, ws: WebSocket) -> None:
        self.room_watchers.add(ws)

    def remove_watcher(self, ws: WebSocket) -> None:
        self.room_watchers.discard(ws)

    def queue_room_list_broadcast(self) -> None:
        """Schedule a room list broadcast; coalesces rapid updates into one send per 400ms."""
        self._room_list_pending = True

    async def _room_list_worker(self) -> None:
        while True:
            await asyncio.sleep(0.4)
            if self._room_list_pending:
                self._room_list_pending = False
                await self.broadcast_room_list()

    async def broadcast_room_list(self) -> None:
        if not self.room_watchers:
            return
        open_rooms = await self.list_open_rooms()
        private_rooms = await self.list_private_rooms()
        dead = set()
        for ws in self.room_watchers:
            try:
                await ws.send_json({"type": "room_list", "open": open_rooms, "private": private_rooms})
            except Exception:
                dead.add(ws)
        self.room_watchers -= dead

    async def cleanup_empty_rooms(self) -> None:
        now = time.time()
        to_delete = []
        async with self._lock:
            for code, room in self.rooms.items():
                real_players = [p for p in room.players if p.pid not in BOT_IDS and p.pid not in FAKE_IDS]
                if not real_players and now - room.last_activity > EMPTY_ROOM_TTL:
                    to_delete.append(code)
            for code in to_delete:
                room = self.rooms.pop(code, None)
                if room and room.bot_task:
                    room.bot_task.cancel()
                t = self.turn_timers.pop(code, None)
                if t:
                    t.cancel()
        if to_delete:
            self.queue_room_list_broadcast()

    def store_profile(self, pid: int, profile: dict, owned: list[str]) -> None:
        data = {**profile, "owned": list(owned)}
        self.profiles[pid] = data
        asyncio.create_task(self._redis_set_profile(pid, data))

    async def _redis_set_profile(self, pid: int, data: dict) -> None:
        r = await get_redis()
        if r:
            try:
                await r.setex(f"durak:profile:{pid}", PROFILE_TTL, json.dumps(data, default=str))
            except Exception:
                pass

    async def refresh_profile_from_redis(self, pid: int) -> None:
        """On reconnect to a different worker, pull fresh profile from Redis."""
        if pid in self.profiles:
            return
        r = await get_redis()
        if not r:
            return
        try:
            raw = await r.get(f"durak:profile:{pid}")
            if raw:
                self.profiles[pid] = json.loads(raw)
        except Exception:
            pass

    def sync_profile_field(self, pid: int, field: str, value) -> None:
        """Update one field in local cache and schedule Redis write."""
        if pid in self.profiles:
            self.profiles[pid][field] = value
            asyncio.create_task(self._redis_set_profile(pid, self.profiles[pid]))

    def get_profile(self, pid: int) -> dict:
        return self.profiles.get(pid, {
            "coins": 5000, "card_skin": "classic",
            "table_skin": "default", "owned": [],
        })

    def room_of(self, pid: int) -> Optional[Room]:
        code = self.user_room.get(pid)
        return self.rooms.get(code) if code else None

    def _make_player(self, pid: int, name: str, ws: Optional[WebSocket]) -> Player:
        p = self.profiles.get(pid, {})
        return Player(
            pid=pid, name=name, ws=ws,
            coins=p.get("coins", 5000),
            card_skin=p.get("card_skin", "classic"),
            table_skin=p.get("table_skin", "default"),
            emoji_pack=p.get("emoji_pack", "classic"),
            user_pack=p.get("user_pack", ""),
            avatar_url=p.get("avatar_url"),
            owned=list(p.get("owned", [])),
        )

    # ────── attach / detach ──────
    async def attach(self, pid: int, name: str, ws: WebSocket) -> Optional[Room]:
        # Cancel pending reconnect timer
        task = self.reconnect_tasks.pop(pid, None)
        if task:
            task.cancel()

        room = self.room_of(pid)
        if room:
            p = room.get(pid)
            if p:
                was_disconnected = p.ws is None
                p.ws = ws
                p.name = name or p.name
                pr = self.profiles.get(pid, {})
                p.coins = pr.get("coins", p.coins)
                p.card_skin = pr.get("card_skin", p.card_skin)
                p.table_skin = pr.get("table_skin", p.table_skin)
                p.emoji_pack = pr.get("emoji_pack", p.emoji_pack)
                p.user_pack = pr.get("user_pack", p.user_pack)
                p.owned = list(pr.get("owned", p.owned))
                if was_disconnected and room.state and room.state.phase == G.Phase.PLAYING:
                    asyncio.create_task(self._broadcast_reconnect(room, pid))
        return room

    async def detach(self, pid: int) -> None:
        room = self.room_of(pid)
        if not room:
            return
        p = room.get(pid)
        if p:
            p.ws = None
        # Start reconnect timer if game is active
        if room.state and room.state.phase == G.Phase.PLAYING:
            asyncio.create_task(self._broadcast_disconnect(room, pid, p))
            task = asyncio.create_task(self._reconnect_timer(room, pid, p.name if p else str(pid)))
            self.reconnect_tasks[pid] = task

    async def _broadcast_disconnect(self, room: Room, pid: int, p: Optional[Player]) -> None:
        avatar = make_avatar(pid, p.name if p else str(pid), p.avatar_url if p else None)
        msg = {
            "type": "player_disconnected",
            "pid": pid,
            "name": p.name if p else str(pid),
            "avatar": avatar,
            "timeout": RECONNECT_TIMEOUT,
        }
        for player in room.players:
            if player.pid != pid and player.ws:
                try:
                    await player.ws.send_json(msg)
                except Exception:
                    pass

    async def _broadcast_reconnect(self, room: Room, pid: int) -> None:
        p = room.get(pid)
        msg = {"type": "player_reconnected", "pid": pid, "name": p.name if p else str(pid)}
        for player in room.players:
            if player.pid != pid and player.ws:
                try:
                    await player.ws.send_json(msg)
                except Exception:
                    pass

    async def _reconnect_timer(self, room: Room, pid: int, name: str) -> None:
        await asyncio.sleep(RECONNECT_TIMEOUT)
        self.reconnect_tasks.pop(pid, None)

        async with self._lock:
            p = room.get(pid)
            if p and p.ws:
                return  # Reconnected before timer fired

            bet = room.state.bet if room.state else 100
            remaining = [x for x in room.players if x.pid != pid and x.pid != BOT_ID]
            n = len(remaining)
            win_per = max(1, round(bet * 0.9 / n)) if n > 0 else 0

            for r in remaining:
                new_coins = await db_mod.adjust_coins(r.pid, win_per)
                r.coins = new_coins
                if r.pid in self.profiles:
                    self.profiles[r.pid]["coins"] = new_coins

            # Deduct from disconnected player (ignore errors if account wiped)
            try:
                await db_mod.adjust_coins(pid, -bet)
            except Exception:
                pass
            if pid in self.profiles:
                self.profiles[pid]["coins"] = max(0, self.profiles[pid].get("coins", 0) - bet)

            # Notify remaining players
            for r in remaining:
                if r.ws:
                    try:
                        await r.ws.send_json({
                            "type": "player_forfeited",
                            "pid": pid,
                            "name": name,
                            "split_coins": win_per,
                        })
                    except Exception:
                        pass

            # Clean up room
            self.user_room.pop(pid, None)
            room.players = [x for x in room.players if x.pid != pid]
            if not room.players or all(x.pid == BOT_ID for x in room.players):
                self.rooms.pop(room.code, None)

    # ────── matchmaking ──────
    async def quick_play(self, pid: int, name: str, ws: WebSocket) -> Room:
        async with self._lock:
            existing = self.room_of(pid)
            if existing:
                p = existing.get(pid)
                if p:
                    p.ws = ws
                return existing

            # Remove stale entry for this player from in-memory queue
            self.queue = [q for q in self.queue if q.pid != pid]

            # Try Redis queue first (cross-worker match)
            r = await get_redis()
            opp_data = None
            if r:
                try:
                    await r.lrem("durak:queue", 0, "")  # clean empty entries
                    raw = await r.lpop("durak:queue")
                    if raw:
                        opp_data = json.loads(raw)
                        if opp_data.get("pid") == pid:
                            # Same player re-queued, ignore and re-queue below
                            opp_data = None
                except Exception:
                    pass

            if opp_data:
                opp_pid = opp_data["pid"]
                # Check if opponent is already in a room (stale queue entry)
                if self.room_of(opp_pid):
                    opp_data = None

            if opp_data:
                opp_pid = opp_data["pid"]
                me = self._make_player(pid, name, ws)
                room = self._make_room(private=False)

                # Opponent may be local (in-memory) or on another worker
                opp_local = next((q for q in self.queue if q.pid == opp_pid), None)
                if opp_local:
                    self.queue = [q for q in self.queue if q.pid != opp_pid]
                    room.players = [opp_local, me]
                    self.user_room[opp_pid] = room.code
                else:
                    # Opponent is on another worker — create a placeholder
                    opp_player = self._make_player(opp_pid, opp_data["name"], None)
                    room.players = [opp_player, me]
                    self.user_room[opp_pid] = room.code
                    # Notify opponent's worker via pub/sub
                    if r:
                        try:
                            await r.publish(
                                f"durak:match:{opp_pid}",
                                json.dumps({"room_code": room.code, "opp_pid": pid, "opp_name": name}),
                            )
                        except Exception:
                            pass

                self.user_room[me.pid] = room.code
                return room

            # No opponent found — add self to Redis queue and create waiting room
            me = self._make_player(pid, name, ws)
            self.queue.append(me)
            if r:
                try:
                    entry = json.dumps({"pid": pid, "name": name})
                    await r.rpush("durak:queue", entry)
                    await r.expire("durak:queue", QUEUE_TTL)
                except Exception:
                    pass
            room = self._make_room(private=False)
            room.players = [me]
            self.user_room[me.pid] = room.code
            return room

    async def handle_match_notification(self, pid: int, room_code: str, opp_pid: int, opp_name: str) -> Optional[Room]:
        """Called when this worker receives a pub/sub match notification for a local player."""
        async with self._lock:
            room = self.rooms.get(room_code)
            if room:
                # Room was created on this worker — just attach
                return room

            # Room lives on another worker; build a local mirror so send_state works
            # In practice this means the player's ws will receive state from the other worker
            # via pub/sub. For now: remove from local queue, attach to the remote room code.
            self.queue = [q for q in self.queue if q.pid != pid]
            p = next((q for q in self.queue if q.pid == pid), None)
            if not p:
                # Reconstruct player from profile cache
                p = self._make_player(pid, self.profiles.get(pid, {}).get("name", str(pid)), None)

            # Store the mapping so room_of() works for this worker
            self.user_room[pid] = room_code
            return None  # Caller must tell the client to reconnect

    async def cancel_queue(self, pid: int) -> None:
        async with self._lock:
            self.queue = [q for q in self.queue if q.pid != pid]
            # Remove from Redis queue
            r = await get_redis()
            if r:
                try:
                    # Scan and remove entry with this pid
                    entries = await r.lrange("durak:queue", 0, -1)
                    for entry in entries:
                        try:
                            data = json.loads(entry)
                            if data.get("pid") == pid:
                                await r.lrem("durak:queue", 1, entry)
                        except Exception:
                            pass
                except Exception:
                    pass
            room = self.room_of(pid)
            if room and room.state is None and len(room.players) == 1:
                self.user_room.pop(pid, None)
                self.rooms.pop(room.code, None)

    # ────── vs bot ──────
    async def vs_bot(self, pid: int, name: str, ws: WebSocket, num_bots: int = 1) -> Room:
        async with self._lock:
            self._evict(pid)
            room = self._make_room(private=False)
            me = self._make_player(pid, name, ws)
            bot_ids = [BOT_ID, BOT_ID2, BOT_ID3][:num_bots]
            bots = [Player(pid=bid, name=BOT_NAMES[bid], ws=None) for bid in bot_ids]
            room.players = [me] + bots
            room.settings.max_players = 1 + num_bots
            self.user_room[pid] = room.code
            for bid in bot_ids:
                room.ready_players.add(bid)
            return room

    def start_bot_task(self, room: Room) -> None:
        if room.bot_task and not room.bot_task.done():
            return
        stop = asyncio.Event()

        bot_pids = [p.pid for p in room.players if p.pid in BOT_IDS]

        def make_action(bot_pid: int):
            def action(type_: str, **kwargs) -> None:
                if room.state is None or room.state.phase != G.Phase.PLAYING:
                    return
                try:
                    if type_ == "attack":
                        G.attack(room.state, bot_pid, kwargs["card"])
                    elif type_ == "defend":
                        G.defend(room.state, bot_pid, kwargs["attack"], kwargs["card"])
                    elif type_ == "transfer":
                        G.transfer(room.state, bot_pid, kwargs["card"])
                    elif type_ == "take":
                        G.take(room.state, bot_pid)
                    elif type_ == "done":
                        G.done(room.state, bot_pid)
                    elif type_ == "pass":
                        G.pass_turn(room.state, bot_pid)
                except G.GameError:
                    return
                asyncio.create_task(_broadcast(room))
            return action

        def make_react(bot_pid: int):
            def react(emoji: str) -> None:
                async def _send():
                    for p in room.players:
                        if p.pid != bot_pid and p.ws:
                            try:
                                await p.ws.send_json({"type": "emoji", "emoji": emoji, "from": bot_pid})
                            except Exception:
                                pass
                asyncio.create_task(_send())
            return react

        async def runner():
            def get_state():
                return room.state
            def get_speed_up():
                return room.speed_up
            tasks = [
                asyncio.create_task(run_bot(get_state, make_action(bid), stop, bot_pid=bid,
                                            react_cb=make_react(bid), speed_up_getter=get_speed_up))
                for bid in bot_pids
            ]
            await asyncio.gather(*tasks, return_exceptions=True)

        room.bot_task = asyncio.create_task(runner())

    # ────── private rooms ──────
    async def create_private(self, pid: int, name: str, ws: WebSocket) -> Room:
        async with self._lock:
            self._evict(pid)
            room = self._make_room(private=True)
            me = self._make_player(pid, name, ws)
            room.players = [me]
            self.user_room[pid] = room.code
        self.queue_room_list_broadcast()
        return room

    async def create_room_with_settings(
        self, pid: int, name: str, ws: WebSocket, settings: RoomSettings
    ) -> Room:
        async with self._lock:
            self._evict(pid)
            is_private = bool(settings.password) or settings.max_players > 2
            room = self._make_room(private=is_private)
            room.settings = settings
            me = self._make_player(pid, name, ws)
            room.players = [me]
            self.user_room[pid] = room.code
        self.queue_room_list_broadcast()
        return room

    async def join_private(self, code: str, pid: int, name: str, ws: WebSocket) -> Optional[Room]:
        async with self._lock:
            room = self.rooms.get(code)
            if not room:
                return None
            if room.has(pid):
                p = room.get(pid)
                if p:
                    p.ws = ws
                return room
            max_p = room.settings.max_players if room.settings else 2
            if len(room.players) >= max_p:
                return None
            self._evict(pid)
            me = self._make_player(pid, name, ws)
            room.players.append(me)
            room.last_activity = time.time()
            self.user_room[pid] = room.code
            self.queue_room_list_broadcast()
            return room

    async def join_open_room(self, code: str, pid: int, name: str, ws: WebSocket) -> Optional[Room]:
        async with self._lock:
            room = self.rooms.get(code)
            if not room or room.private:
                return None
            if room.has(pid):
                p = room.get(pid)
                if p:
                    p.ws = ws
                return room
            max_p = room.settings.max_players if room.settings else 2
            if len(room.players) >= max_p:
                return None
            if room.state and room.state.phase == G.Phase.PLAYING:
                return None
            self._evict(pid)
            me = self._make_player(pid, name, ws)
            room.players.append(me)
            room.last_activity = time.time()
            self.user_room[pid] = room.code
            self.queue_room_list_broadcast()
            return room

    async def list_open_rooms(self) -> list[dict]:
        result = []
        for code, room in self.rooms.items():
            if room.private:
                continue
            max_p = room.settings.max_players if room.settings else 2
            if len(room.players) >= max_p:
                continue
            if room.state and room.state.phase == G.Phase.PLAYING:
                continue
            host = room.players[0] if room.players else None
            result.append({
                "code": code,
                "host_name": host.name if host else "—",
                "bet": room.settings.bet if room.settings else 100,
                "max_players": max_p,
                "current_players": len(room.players),
                "mode": room.settings.mode if room.settings else "perevodnoy",
                "deck_size": room.settings.deck_size if room.settings else 36,
            })
        return result

    async def list_private_rooms(self) -> list[dict]:
        result = []
        for code, room in self.rooms.items():
            if not room.private:
                continue
            max_p = room.settings.max_players if room.settings else 2
            if len(room.players) >= max_p:
                continue
            if room.state and room.state.phase == G.Phase.PLAYING:
                continue
            host = room.players[0] if room.players else None
            result.append({
                "code": code,
                "host_name": host.name if host else "—",
                "bet": room.settings.bet if room.settings else 100,
                "max_players": max_p,
                "current_players": len(room.players),
                "mode": room.settings.mode if room.settings else "perevodnoy",
                "deck_size": room.settings.deck_size if room.settings else 36,
            })
        return result

    # ────── ready check ──────
    async def mark_ready(self, pid: int) -> Optional[Room]:
        async with self._lock:
            room = self.room_of(pid)
            if not room or room.state:
                return room
            room.ready_players.add(pid)
            human_pids = [p.pid for p in room.players if p.pid not in BOT_IDS and p.pid not in FAKE_IDS]
            max_p = room.settings.max_players if room.settings else 2
            if (
                all(hp in room.ready_players for hp in human_pids) and
                len(room.players) >= max_p
            ):
                pids = [p.pid for p in room.players]
                s = room.settings if room.settings else RoomSettings()
                room.state = G.new_game(
                    *pids,
                    mode=s.mode,
                    bet=s.bet,
                    deck_size=s.deck_size,
                )
            return room

    # ────── rematch ──────
    async def rematch(self, pid: int) -> Optional[Room]:
        async with self._lock:
            room = self.room_of(pid)
            if not room:
                return None
            room.rematch_votes = getattr(room, 'rematch_votes', set())
            room.rematch_votes.add(pid)
            human_pids = [p.pid for p in room.players if p.pid not in BOT_IDS]
            if all(hp in room.rematch_votes for hp in human_pids):
                room.rematch_votes = set()
                room.result_applied = False
                s = room.settings if room.settings else RoomSettings()
                pids = [p.pid for p in room.players]
                room.state = G.new_game(*pids, mode=s.mode, bet=s.bet, deck_size=s.deck_size)
                room.ready_players = set(p.pid for p in room.players if p.pid in BOT_IDS)
            return room

    # ────── leave ──────
    async def leave(self, pid: int) -> Optional[Room]:
        async with self._lock:
            room = self.room_of(pid)
            if not room:
                return None
            if room.bot_task:
                room.bot_task.cancel()
            t = self.turn_timers.pop(room.code, None)
            if t:
                t.cancel()
            self.user_room.pop(pid, None)
            self.queue = [q for q in self.queue if q.pid != pid]
            room.players = [p for p in room.players if p.pid != pid]
            if not room.players or all(p.pid in BOT_IDS or p.pid in FAKE_IDS for p in room.players):
                self.rooms.pop(room.code, None)
                self.queue_room_list_broadcast()
                return None
            room.last_activity = time.time()
            if room.state and room.state.phase == G.Phase.PLAYING:
                room.state.phase = G.Phase.FINISHED
                surviving = next((p for p in room.players if p.pid not in BOT_IDS), None)
                room.state.winner = surviving.pid if surviving else None
                room.state.loser = pid
        self.queue_room_list_broadcast()
        return room

    # ────── internals ──────
    def _make_room(self, private: bool) -> Room:
        code = secrets.token_urlsafe(6)[:8]
        while code in self.rooms:
            code = secrets.token_urlsafe(6)[:8]
        room = Room(code=code, private=private)
        self.rooms[code] = room
        return room

    def _evict(self, pid: int) -> None:
        old = self.user_room.pop(pid, None)
        self.queue = [q for q in self.queue if q.pid != pid]
        if old:
            r = self.rooms.get(old)
            if r:
                if r.bot_task:
                    r.bot_task.cancel()
                r.players = [p for p in r.players if p.pid != pid]
                if not r.players or all(p.pid == BOT_ID for p in r.players):
                    self.rooms.pop(old, None)


hub = Hub()


def _reset_turn_timer(room: Room) -> None:
    """Cancel any existing turn timer and start a fresh one for this room."""
    old = hub.turn_timers.pop(room.code, None)
    if old:
        old.cancel()
    if room.state and room.state.phase == G.Phase.PLAYING:
        room.turn_started_at = time.time()
        task = asyncio.create_task(_turn_timeout(room))
        hub.turn_timers[room.code] = task


async def _turn_timeout(room: Room) -> None:
    """After TURN_TIMEOUT seconds, force the appropriate action for idle players."""
    elapsed = 0.0
    interval = 0.5
    while elapsed < TURN_TIMEOUT:
        await asyncio.sleep(interval)
        elapsed += interval
        if room.speed_up and elapsed >= 3.0:
            break
    hub.turn_timers.pop(room.code, None)

    async with hub._lock:
        state = room.state
        if not state or state.phase != G.Phase.PLAYING:
            return

        acted = False
        # Force non-defenders who haven't passed
        non_defenders = [p for p in state.players if p != state.defender]
        for pid in non_defenders:
            if pid in state.passed:
                continue
            if not state.table:
                continue
            try:
                if (pid == state.attacker
                        and G._undefended_count(state) == 0
                        and not state.defending_takes):
                    G.done(state, pid)
                else:
                    G.pass_turn(state, pid)
                acted = True
            except G.GameError:
                pass

        # Force defender to take if they haven't responded
        if state.table and G._undefended_count(state) > 0 and not state.defending_takes:
            try:
                G.take(state, state.defender)
                acted = True
            except G.GameError:
                pass

        # Table is empty and no non-defender can attack → dead round, advance
        if not acted and not state.table:
            can_attack = any(state.hands.get(p) for p in state.players if p != state.defender)
            if not can_attack:
                G._finalize_done(state)
                acted = True

        if acted:
            if room.state and room.state.phase == G.Phase.FINISHED:
                from .main import _apply_result  # lazy import — avoids circular at module level
                ws_map = {p.pid: p.ws for p in room.players if p.ws}
                await _apply_result(room, ws_map)
            await send_state(room)
        else:
            _reset_turn_timer(room)


async def _broadcast(room: Room, bot_username: str | None = None) -> None:
    if room.state and room.state.phase == G.Phase.FINISHED and not room.result_applied:
        from .main import _apply_result
        ws_map = {p.pid: p.ws for p in room.players if p.ws}
        await _apply_result(room, ws_map)
    await send_state(room, bot_username)


async def send_state(room: Room, bot_username: str | None = None) -> None:
    if not room.state:
        max_p = room.settings.max_players if room.settings else 2
        if len(room.players) >= max_p:
            for p in room.players:
                if not p.ws:
                    continue
                opp = next((x for x in room.players if x.pid != p.pid), None)
                s = room.settings or RoomSettings()
                try:
                    await p.ws.send_json({
                        "type": "ready_check",
                        "you_ready": p.pid in room.ready_players,
                        "current_players": len(room.players),
                        "max_players": max_p,
                        "bet": s.bet,
                        "mode": s.mode,
                        "deck_size": s.deck_size,
                        "players": [
                            {
                                "name": x.name,
                                "avatar": make_avatar(x.pid, x.name, x.avatar_url),
                                "ready": x.pid in room.ready_players,
                                "is_me": x.pid == p.pid,
                            }
                            for x in room.players
                        ],
                    })
                except Exception:
                    pass
        else:
            for p in room.players:
                if p.ws:
                    try:
                        s = room.settings or RoomSettings()
                        await p.ws.send_json({
                            "type": "waiting",
                            "code": room.code,
                            "private": room.private,
                            "bot_username": bot_username,
                            "bet": s.bet,
                            "mode": s.mode,
                            "deck_size": s.deck_size,
                            "max_players": room.settings.max_players if room.settings else 2,
                            "current_players": len(room.players),
                            "you": {
                                "id": p.pid, "name": p.name,
                                "coins": p.coins,
                                "avatar": make_avatar(p.pid, p.name, p.avatar_url),
                            },
                        })
                    except Exception:
                        pass
        return

    for p in room.players:
        if not p.ws:
            continue
        opp = next((x for x in room.players if x.pid != p.pid), None)
        view = G.view_for(room.state, p.pid)
        view["you_name"] = p.name
        view["you_rank"] = get_rank(hub.profiles.get(p.pid, {}).get("games", 0))
        view["opponent_name"] = opp.name if opp else "—"
        # Resolve winner/loser names for end screen
        def _pname(pid: int) -> str:
            rp = room.get(pid)
            return rp.name if rp else BOT_NAMES.get(pid, str(pid))
        if room.state.winner is not None:
            view["winner_name"] = _pname(room.state.winner)
        if room.state.loser is not None:
            view["loser_name"] = _pname(room.state.loser)
        view["vs_bot"] = any(pl.pid == BOT_ID for pl in room.players)
        view["you_coins"] = p.coins
        view["you_card_skin"] = p.card_skin
        view["you_table_skin"] = p.table_skin
        view["you_emoji_pack"] = p.emoji_pack
        if room.turn_started_at:
            view["timer_remaining"] = max(0, TURN_TIMEOUT - (time.time() - room.turn_started_at))
        # Resolve active emojis so client restores them on reconnect
        if p.user_pack:
            _web = Path(__file__).resolve().parent.parent / "web"
            _img_urls = [f"/static/packs/{p.user_pack}/{i}.webp"
                         for i in range(6) if (_web / "packs" / p.user_pack / f"{i}.webp").exists()]
            if _img_urls:
                view["you_emoji_imgs"] = _img_urls
        if "you_emoji_imgs" not in view:
            view["you_emojis"] = EMOJI_PACKS.get(p.emoji_pack, EMOJI_PACKS["classic"])["emojis"]
        view["opp_card_skin"] = opp.card_skin if opp else "classic"
        view["you_avatar"] = make_avatar(p.pid, p.name, p.avatar_url)
        view["opp_avatar"] = make_avatar(opp.pid, opp.name, opp.avatar_url) if opp else None
        # Full opponents list for multiplayer (3-4 players)
        opponents = [x for x in room.players if x.pid != p.pid]
        view["opponents"] = [
            {
                "id": x.pid,
                "name": x.name,
                "avatar": make_avatar(x.pid, x.name, x.avatar_url),
                "card_skin": x.card_skin,
                "card_count": len(room.state.hands.get(x.pid, [])),
                "is_attacker": x.pid == room.state.attacker,
                "is_defender": x.pid == room.state.defender,
                "eliminated": x.pid not in room.state.players,
                "finish_pos": (room.state.finish_order.index(x.pid) + 1) if x.pid in room.state.finish_order else None,
                "games": hub.profiles.get(x.pid, {}).get("games", 0) if x.pid not in BOT_IDS else {BOT_ID: 7, BOT_ID2: 15, BOT_ID3: 30}.get(x.pid, 7),
                "pogon": hub.profiles.get(x.pid, {}).get("pogon", {"type": "blank"}) if x.pid not in BOT_IDS else {BOT_ID: {"type": "stripes", "n": 1}, BOT_ID2: {"type": "stripes", "n": 2}, BOT_ID3: {"type": "stars", "n": 1, "size": "sm"}}.get(x.pid, {"type": "blank"}),
            }
            for x in opponents
        ]
        try:
            await p.ws.send_json({"type": "state", "state": view})
        except Exception:
            pass

    _reset_turn_timer(room)


async def send_error(ws: WebSocket, msg: str) -> None:
    try:
        await ws.send_json({"type": "error", "message": msg})
    except Exception:
        pass
