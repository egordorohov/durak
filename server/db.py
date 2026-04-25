"""PostgreSQL persistence via asyncpg — users, coins, cosmetics, stats, achievements, friends."""
from __future__ import annotations

import json
import os
from datetime import datetime, date
from decimal import Decimal
from typing import Optional

import asyncpg

from .redis_client import get_redis


def _clean(value):
    """Convert Postgres-specific types to JSON-safe Python primitives."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _clean_row(row: dict) -> dict:
    return {k: _clean(v) for k, v in row.items()}


def _clean_rows(rows: list[dict]) -> list[dict]:
    return [_clean_row(r) for r in rows]

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://tools:password@localhost:5432/durak")

_pool: asyncpg.Pool | None = None

COIN_START = 5000
COIN_BET   = 100
COIN_WIN   = 90


def _pool_get() -> asyncpg.Pool:
    assert _pool is not None, "db not initialised — call init_db() first"
    return _pool


def get_pool() -> asyncpg.Pool:
    return _pool_get()


async def init_db() -> None:
    global _pool
    _pool = await asyncpg.create_pool(DATABASE_URL, min_size=4, max_size=30)
    async with _pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id          BIGINT      PRIMARY KEY,
                name        TEXT        NOT NULL,
                username    TEXT,
                coins       INTEGER     NOT NULL DEFAULT 5000,
                card_skin   TEXT        NOT NULL DEFAULT 'classic',
                table_skin  TEXT        NOT NULL DEFAULT 'default',
                avatar_url  TEXT,
                last_online TIMESTAMPTZ,
                last_bonus_date TEXT,
                emoji_pack  TEXT        DEFAULT 'classic',
                user_pack   TEXT,
                created_at  TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE TABLE IF NOT EXISTS owned_cosmetics (
                user_id     BIGINT  NOT NULL REFERENCES users(id),
                cosmetic_id TEXT    NOT NULL,
                PRIMARY KEY (user_id, cosmetic_id)
            );
            CREATE TABLE IF NOT EXISTS stats (
                user_id     BIGINT  PRIMARY KEY REFERENCES users(id),
                games       INTEGER DEFAULT 0,
                wins        INTEGER DEFAULT 0,
                losses      INTEGER DEFAULT 0,
                draws       INTEGER DEFAULT 0,
                streak      INTEGER DEFAULT 0,
                best_streak INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS achievements (
                user_id        BIGINT  NOT NULL REFERENCES users(id),
                achievement_id TEXT    NOT NULL,
                unlocked_at    TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (user_id, achievement_id)
            );
            CREATE TABLE IF NOT EXISTS friends (
                user_id    BIGINT  NOT NULL REFERENCES users(id),
                friend_id  BIGINT  NOT NULL,
                status     TEXT    DEFAULT 'pending',
                created_at TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (user_id, friend_id)
            );
            CREATE TABLE IF NOT EXISTS user_packs (
                id          TEXT    PRIMARY KEY,
                creator_id  BIGINT  NOT NULL REFERENCES users(id),
                name        TEXT    NOT NULL,
                price       INTEGER NOT NULL DEFAULT 500,
                supply      INTEGER NOT NULL DEFAULT 0,
                sold        INTEGER NOT NULL DEFAULT 0,
                status      TEXT    NOT NULL DEFAULT 'pending',
                created_at  TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE TABLE IF NOT EXISTS user_pack_purchases (
                pack_id     TEXT    NOT NULL,
                buyer_id    BIGINT  NOT NULL,
                bought_at   TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (pack_id, buyer_id)
            );
            CREATE TABLE IF NOT EXISTS clans (
                id          BIGSERIAL   PRIMARY KEY,
                name        TEXT        NOT NULL,
                username    TEXT        UNIQUE,
                creator_id  BIGINT      NOT NULL REFERENCES users(id),
                description TEXT        DEFAULT '',
                created_at  TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE TABLE IF NOT EXISTS clan_members (
                clan_id   BIGINT  NOT NULL REFERENCES clans(id),
                user_id   BIGINT  NOT NULL REFERENCES users(id),
                role      TEXT    DEFAULT 'member',
                joined_at TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (clan_id, user_id)
            );

            CREATE INDEX IF NOT EXISTS idx_friends_user_id    ON friends(user_id);
            CREATE INDEX IF NOT EXISTS idx_friends_friend_id  ON friends(friend_id);
            CREATE INDEX IF NOT EXISTS idx_stats_user_id      ON stats(user_id);
            CREATE INDEX IF NOT EXISTS idx_achievements_uid   ON achievements(user_id);
            CREATE INDEX IF NOT EXISTS idx_owned_cos_uid      ON owned_cosmetics(user_id);
            CREATE INDEX IF NOT EXISTS idx_clan_members_uid   ON clan_members(user_id);
            CREATE INDEX IF NOT EXISTS idx_clan_members_cid   ON clan_members(clan_id);
            CREATE INDEX IF NOT EXISTS idx_users_username     ON users(username);
        """)


# ── Daily bonus ────────────────────────────────────────────────────────────────

DAILY_BONUS = 50


async def claim_daily_bonus(pid: int) -> tuple[bool, int]:
    from datetime import date
    today = date.today().isoformat()
    pool = _pool_get()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT coins, last_bonus_date FROM users WHERE id=$1", pid
        )
        if not row or row["last_bonus_date"] == today:
            return False, (row["coins"] if row else COIN_START)
        new_coins = row["coins"] + DAILY_BONUS
        await conn.execute(
            "UPDATE users SET coins=$1, last_bonus_date=$2 WHERE id=$3",
            new_coins, today, pid,
        )
        return True, new_coins


# ── Users ──────────────────────────────────────────────────────────────────────

async def touch_online(pid: int) -> None:
    await _pool_get().execute(
        "UPDATE users SET last_online=NOW() WHERE id=$1", pid
    )


async def upsert_user(pid: int, name: str, username: Optional[str]) -> dict:
    pool = _pool_get()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM users WHERE id=$1", pid)
        if row:
            await conn.execute(
                "UPDATE users SET name=$1, username=$2, last_online=NOW() WHERE id=$3",
                name, username, pid,
            )
            return _clean_row(dict(row))
        await conn.execute(
            "INSERT INTO users (id, name, username) VALUES ($1, $2, $3)",
            pid, name, username,
        )
        return {
            "id": pid, "name": name, "username": username,
            "coins": COIN_START, "card_skin": "classic", "table_skin": "default",
            "emoji_pack": "classic", "user_pack": None, "avatar_url": None,
        }


async def adjust_coins(pid: int, delta: int) -> int:
    pool = _pool_get()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET coins = GREATEST(0, coins + $1) WHERE id=$2",
            delta, pid,
        )
        row = await conn.fetchrow("SELECT coins FROM users WHERE id=$1", pid)
        return row["coins"] if row else 0


async def set_coins(pid: int, amount: int) -> None:
    await _pool_get().execute("UPDATE users SET coins=$1 WHERE id=$2", amount, pid)


async def update_avatar(pid: int, url: str) -> None:
    await _pool_get().execute("UPDATE users SET avatar_url=$1 WHERE id=$2", url, pid)


async def get_coins(pid: int) -> int:
    row = await _pool_get().fetchrow("SELECT coins FROM users WHERE id=$1", pid)
    return row["coins"] if row else COIN_START


# ── Cosmetics ──────────────────────────────────────────────────────────────────

async def get_owned_cosmetics(pid: int) -> list[str]:
    rows = await _pool_get().fetch(
        "SELECT cosmetic_id FROM owned_cosmetics WHERE user_id=$1", pid
    )
    return [r["cosmetic_id"] for r in rows]


async def buy_cosmetic(pid: int, cosmetic_id: str, price: int) -> tuple[bool, int]:
    pool = _pool_get()
    async with pool.acquire() as conn:
        async with conn.transaction():
            already = await conn.fetchrow(
                "SELECT 1 FROM owned_cosmetics WHERE user_id=$1 AND cosmetic_id=$2",
                pid, cosmetic_id,
            )
            row = await conn.fetchrow("SELECT coins FROM users WHERE id=$1", pid)
            current = row["coins"] if row else 0
            if already:
                return True, current
            if current < price:
                return False, current
            new_coins = current - price
            await conn.execute("UPDATE users SET coins=$1 WHERE id=$2", new_coins, pid)
            await conn.execute(
                "INSERT INTO owned_cosmetics (user_id, cosmetic_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                pid, cosmetic_id,
            )
            return True, new_coins


async def set_active_skin(pid: int, kind: str, skin_id: str) -> None:
    col_map = {"card": "card_skin", "emoji": "emoji_pack", "user_pack": "user_pack"}
    col = col_map.get(kind, "table_skin")
    await _pool_get().execute(
        f"UPDATE users SET {col}=$1 WHERE id=$2", skin_id, pid  # noqa: S608 — col from whitelist
    )


# ── Stats ──────────────────────────────────────────────────────────────────────

async def get_stats(pid: int) -> dict:
    row = await _pool_get().fetchrow("SELECT * FROM stats WHERE user_id=$1", pid)
    if row:
        return _clean_row(dict(row))
    return {"user_id": pid, "games": 0, "wins": 0, "losses": 0,
            "draws": 0, "streak": 0, "best_streak": 0}


async def get_user_by_username(username: str) -> dict | None:
    row = await _pool_get().fetchrow(
        "SELECT id, name, avatar_url FROM users WHERE username=$1", username
    )
    return _clean_row(dict(row)) if row else None


async def update_stats(pid: int, result: str) -> dict:
    pool = _pool_get()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM stats WHERE user_id=$1", pid)
        s = dict(row) if row else {
            "user_id": pid, "games": 0, "wins": 0, "losses": 0,
            "draws": 0, "streak": 0, "best_streak": 0,
        }
        s["games"] += 1
        if result == "win":
            s["wins"] += 1
            s["streak"] = max(0, s["streak"]) + 1
            if s["streak"] < 0:
                s["streak"] = 1
        elif result == "loss":
            s["losses"] += 1
            s["streak"] = min(0, s["streak"]) - 1
            if s["streak"] > 0:
                s["streak"] = -1
        else:
            s["draws"] += 1
            s["streak"] = 0
        if s["streak"] > s["best_streak"]:
            s["best_streak"] = s["streak"]

        await conn.execute("""
            INSERT INTO stats (user_id, games, wins, losses, draws, streak, best_streak)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (user_id) DO UPDATE SET
                games=$2, wins=$3, losses=$4, draws=$5, streak=$6, best_streak=$7
        """, pid, s["games"], s["wins"], s["losses"], s["draws"], s["streak"], s["best_streak"])
        return s


# ── Achievements ───────────────────────────────────────────────────────────────

async def get_achievements(pid: int) -> list[str]:
    rows = await _pool_get().fetch(
        "SELECT achievement_id FROM achievements WHERE user_id=$1", pid
    )
    return [r["achievement_id"] for r in rows]


async def unlock_achievement(pid: int, achievement_id: str) -> bool:
    pool = _pool_get()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT 1 FROM achievements WHERE user_id=$1 AND achievement_id=$2",
            pid, achievement_id,
        )
        if existing:
            return False
        await conn.execute(
            "INSERT INTO achievements (user_id, achievement_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
            pid, achievement_id,
        )
        return True


# ── Friends ────────────────────────────────────────────────────────────────────

async def get_friends(pid: int) -> list[dict]:
    rows = await _pool_get().fetch("""
        SELECT f.friend_id, f.status, u.name, u.username, u.avatar_url, u.last_online
        FROM friends f
        LEFT JOIN users u ON u.id = f.friend_id
        WHERE f.user_id = $1
    """, pid)
    return [{"friend_id": r["friend_id"], "status": r["status"],
             "name": r["name"], "username": r["username"],
             "avatar_url": r["avatar_url"],
             "last_online": _clean(r["last_online"])}
            for r in rows]


async def get_incoming_requests(pid: int) -> list[dict]:
    rows = await _pool_get().fetch("""
        SELECT f.user_id as from_id, u.name, u.username, u.avatar_url
        FROM friends f
        LEFT JOIN users u ON u.id = f.user_id
        WHERE f.friend_id = $1 AND f.status = 'pending'
          AND NOT EXISTS (
              SELECT 1 FROM friends f2
              WHERE f2.user_id = $1 AND f2.friend_id = f.user_id
          )
    """, pid)
    return [{"from_id": r["from_id"], "name": r["name"],
             "username": r["username"], "avatar_url": r["avatar_url"]} for r in rows]


async def accept_friend(pid: int, from_id: int) -> None:
    pool = _pool_get()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("""
                INSERT INTO friends (user_id, friend_id, status) VALUES ($1, $2, 'accepted')
                ON CONFLICT (user_id, friend_id) DO UPDATE SET status='accepted'
            """, pid, from_id)
            await conn.execute("""
                INSERT INTO friends (user_id, friend_id, status) VALUES ($1, $2, 'accepted')
                ON CONFLICT (user_id, friend_id) DO UPDATE SET status='accepted'
            """, from_id, pid)


async def search_users(query: str, limit: int = 10) -> list[dict]:
    q = f"%{query}%"
    rows = await _pool_get().fetch("""
        SELECT id, name, username, avatar_url
        FROM users
        WHERE (username ILIKE $1 OR name ILIKE $1)
        ORDER BY CASE WHEN username ILIKE $2 THEN 0 ELSE 1 END, name
        LIMIT $3
    """, q, f"{query}%", limit)
    return [{"id": r["id"], "name": r["name"],
             "username": r["username"], "avatar_url": r["avatar_url"]} for r in rows]


async def get_leaderboard(limit: int = 50, sort: str = "games") -> list[dict]:
    cache_key = f"durak:lb:{sort}:{limit}"
    r = await get_redis()
    if r:
        cached = await r.get(cache_key)
        if cached:
            return json.loads(cached)

    if sort == "games":
        order = "COALESCE(s.games, 0) DESC"
        where = "COALESCE(s.games, 0) > 0"
    else:
        order = "u.coins DESC"
        where = "TRUE"
    rows = await _pool_get().fetch(f"""
        SELECT u.id, u.name, u.avatar_url, u.coins,
               COALESCE(s.games, 0) AS games,
               COALESCE(s.wins, 0)  AS wins
        FROM users u
        LEFT JOIN stats s ON s.user_id = u.id
        WHERE {where}
        ORDER BY {order}
        LIMIT $1
    """, limit)
    result = _clean_rows([dict(r) for r in rows])
    if r:
        await r.setex(cache_key, 5, json.dumps(result))
    return result


async def add_friend_request(pid: int, friend_id: int) -> str:
    pool = _pool_get()
    async with pool.acquire() as conn:
        async with conn.transaction():
            reverse = await conn.fetchrow(
                "SELECT status FROM friends WHERE user_id=$1 AND friend_id=$2",
                friend_id, pid,
            )
            if reverse:
                await conn.execute("""
                    INSERT INTO friends (user_id, friend_id, status) VALUES ($1, $2, 'accepted')
                    ON CONFLICT (user_id, friend_id) DO UPDATE SET status='accepted'
                """, pid, friend_id)
                await conn.execute("""
                    UPDATE friends SET status='accepted' WHERE user_id=$1 AND friend_id=$2
                """, friend_id, pid)
                return "accepted"
            await conn.execute("""
                INSERT INTO friends (user_id, friend_id, status) VALUES ($1, $2, 'pending')
                ON CONFLICT DO NOTHING
            """, pid, friend_id)
            return "sent"


async def remove_friend(pid: int, friend_id: int) -> None:
    pool = _pool_get()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "DELETE FROM friends WHERE (user_id=$1 AND friend_id=$2) OR (user_id=$2 AND friend_id=$1)",
                pid, friend_id,
            )


# ── Clans ──────────────────────────────────────────────────────────────────────

async def create_clan(creator_id: int, name: str, username: str | None, description: str) -> tuple[bool, str, dict | None]:
    username = username.strip().lstrip("@").lower() if username else None
    pool = _pool_get()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT clan_id FROM clan_members WHERE user_id=$1", creator_id
        )
        if existing:
            return False, "Вы уже состоите в клане", None
        try:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "INSERT INTO clans (name, username, creator_id, description) VALUES ($1,$2,$3,$4) RETURNING *",
                    name, username, creator_id, description,
                )
                clan_id = row["id"]
                await conn.execute(
                    "INSERT INTO clan_members (clan_id, user_id, role) VALUES ($1,$2,'owner')",
                    clan_id, creator_id,
                )
        except asyncpg.UniqueViolationError:
            return False, "Username уже занят", None
        return True, "", _clean_row(dict(row))


async def join_clan(user_id: int, username: str) -> tuple[bool, str, dict | None]:
    username = username.strip().lstrip("@").lower()
    pool = _pool_get()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT clan_id FROM clan_members WHERE user_id=$1", user_id
        )
        if existing:
            return False, "Вы уже состоите в клане", None
        clan = await conn.fetchrow("SELECT * FROM clans WHERE username=$1", username)
        if not clan:
            return False, "Клан не найден", None
        await conn.execute(
            "INSERT INTO clan_members (clan_id, user_id, role) VALUES ($1,$2,'member') ON CONFLICT DO NOTHING",
            clan["id"], user_id,
        )
        return True, "", _clean_row(dict(clan))


async def leave_clan(user_id: int) -> bool:
    pool = _pool_get()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT clan_id, role FROM clan_members WHERE user_id=$1", user_id
        )
        if not row:
            return False
        clan_id, role = row["clan_id"], row["role"]
        async with conn.transaction():
            await conn.execute("DELETE FROM clan_members WHERE user_id=$1", user_id)
            if role == "owner":
                next_owner = await conn.fetchrow(
                    "SELECT user_id FROM clan_members WHERE clan_id=$1 ORDER BY joined_at LIMIT 1",
                    clan_id,
                )
                if next_owner:
                    await conn.execute(
                        "UPDATE clan_members SET role='owner' WHERE clan_id=$1 AND user_id=$2",
                        clan_id, next_owner["user_id"],
                    )
                else:
                    await conn.execute("DELETE FROM clans WHERE id=$1", clan_id)
        return True


async def get_my_clan(user_id: int) -> dict | None:
    pool = _pool_get()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT c.*, cm.role,
                   (SELECT COUNT(*) FROM clan_members WHERE clan_id=c.id) AS member_count,
                   (SELECT COALESCE(SUM(s.games),0) FROM clan_members m2
                    LEFT JOIN stats s ON s.user_id=m2.user_id WHERE m2.clan_id=c.id) AS total_games,
                   (SELECT COALESCE(SUM(u2.coins),0) FROM clan_members m2
                    LEFT JOIN users u2 ON u2.id=m2.user_id WHERE m2.clan_id=c.id) AS total_coins
            FROM clans c
            JOIN clan_members cm ON cm.clan_id=c.id AND cm.user_id=$1
        """, user_id)
        if not row:
            return None
        clan = dict(row)
        members = await conn.fetch("""
            SELECT u.id, u.name, u.avatar_url, u.coins, cm.role,
                   COALESCE(s.games,0) AS games, COALESCE(s.wins,0) AS wins
            FROM clan_members cm
            JOIN users u ON u.id=cm.user_id
            LEFT JOIN stats s ON s.user_id=cm.user_id
            WHERE cm.clan_id=$1
            ORDER BY CASE cm.role WHEN 'owner' THEN 0 ELSE 1 END, COALESCE(s.games,0) DESC
        """, clan["id"])
        clan["members"] = _clean_rows([dict(m) for m in members])
        return _clean_row(clan)


async def get_clan_leaderboard(sort: str = "games", limit: int = 50) -> list[dict]:
    cache_key = f"durak:clan_lb:{sort}:{limit}"
    r = await get_redis()
    if r:
        cached = await r.get(cache_key)
        if cached:
            return json.loads(cached)

    col = "SUM(COALESCE(s.games,0))" if sort == "games" else "SUM(u.coins)"
    rows = await _pool_get().fetch(f"""
        SELECT c.id, c.name, c.username,
               COUNT(cm.user_id) AS member_count,
               COALESCE(SUM(COALESCE(s.games,0)),0) AS total_games,
               COALESCE(SUM(u.coins),0) AS total_coins
        FROM clans c
        JOIN clan_members cm ON cm.clan_id=c.id
        JOIN users u ON u.id=cm.user_id
        LEFT JOIN stats s ON s.user_id=cm.user_id
        GROUP BY c.id
        ORDER BY {col} DESC
        LIMIT $1
    """, limit)
    result = _clean_rows([dict(r) for r in rows])
    if r:
        await r.setex(cache_key, 5, json.dumps(result))
    return result


# ── Admin helpers ──────────────────────────────────────────────────────────────

async def admin_set_games(pid: int, games: int) -> None:
    await _pool_get().execute("""
        INSERT INTO stats (user_id, games) VALUES ($1, $2)
        ON CONFLICT (user_id) DO UPDATE SET games=$2
    """, pid, games)


async def admin_set_coins(pid: int, coins: int) -> None:
    await _pool_get().execute("UPDATE users SET coins=$1 WHERE id=$2", coins, pid)


async def admin_set_stat(pid: int, field: str, value: int) -> None:
    allowed = {"wins", "losses", "draws", "streak", "best_streak"}
    if field not in allowed:
        return
    await _pool_get().execute(f"""
        INSERT INTO stats (user_id, {field}) VALUES ($1, $2)
        ON CONFLICT (user_id) DO UPDATE SET {field}=$2
    """, pid, value)


# ── User Packs ─────────────────────────────────────────────────────────────────

async def create_user_pack(pack_id: str, creator_id: int, name: str, price: int, supply: int) -> None:
    await _pool_get().execute(
        "INSERT INTO user_packs (id, creator_id, name, price, supply) VALUES ($1,$2,$3,$4,$5)",
        pack_id, creator_id, name, price, supply,
    )


async def get_user_packs_market(limit: int = 100) -> list[dict]:
    rows = await _pool_get().fetch("""
        SELECT p.id, p.creator_id, p.name, p.price, p.supply, p.sold, p.created_at,
               u.name AS creator_name
        FROM user_packs p JOIN users u ON u.id = p.creator_id
        WHERE p.status = 'approved'
        ORDER BY p.sold DESC, p.created_at DESC
        LIMIT $1
    """, limit)
    return _clean_rows([dict(r) for r in rows])


async def get_user_packs_pending() -> list[dict]:
    rows = await _pool_get().fetch("""
        SELECT p.id, p.creator_id, p.name, p.price, p.supply, p.sold, p.created_at,
               u.name AS creator_name
        FROM user_packs p JOIN users u ON u.id = p.creator_id
        WHERE p.status = 'pending'
        ORDER BY p.created_at ASC
    """)
    return _clean_rows([dict(r) for r in rows])


async def get_my_packs(creator_id: int) -> list[dict]:
    rows = await _pool_get().fetch(
        "SELECT * FROM user_packs WHERE creator_id=$1 ORDER BY created_at DESC",
        creator_id,
    )
    return _clean_rows([dict(r) for r in rows])


async def set_pack_status(pack_id: str, status: str) -> None:
    await _pool_get().execute(
        "UPDATE user_packs SET status=$1 WHERE id=$2", status, pack_id
    )


async def buy_user_pack(pack_id: str, buyer_id: int, price: int) -> tuple[bool, str]:
    pool = _pool_get()
    async with pool.acquire() as conn:
        async with conn.transaction():
            pack = await conn.fetchrow(
                "SELECT * FROM user_pack_purchases WHERE pack_id=$1 AND buyer_id=$2",
                pack_id, buyer_id,
            )
            if pack:
                return False, "уже куплен"
            p = await conn.fetchrow(
                "SELECT * FROM user_packs WHERE id=$1 AND status='approved'", pack_id
            )
            if not p:
                return False, "пак не найден"
            if p["supply"] > 0 and p["sold"] >= p["supply"]:
                return False, "пак распродан"
            row = await conn.fetchrow("SELECT coins FROM users WHERE id=$1", buyer_id)
            if not row or row["coins"] < p["price"]:
                return False, "недостаточно монет"
            creator_cut = int(p["price"] * 0.70)
            await conn.execute(
                "UPDATE users SET coins = coins - $1 WHERE id=$2", p["price"], buyer_id
            )
            await conn.execute(
                "UPDATE users SET coins = coins + $1 WHERE id=$2", creator_cut, p["creator_id"]
            )
            await conn.execute(
                "INSERT INTO user_pack_purchases (pack_id, buyer_id) VALUES ($1,$2)",
                pack_id, buyer_id,
            )
            await conn.execute(
                "UPDATE user_packs SET sold = sold + 1 WHERE id=$1", pack_id
            )
            return True, ""


async def get_owned_user_packs(buyer_id: int) -> list[str]:
    rows = await _pool_get().fetch(
        "SELECT pack_id FROM user_pack_purchases WHERE buyer_id=$1", buyer_id
    )
    return [r["pack_id"] for r in rows]
