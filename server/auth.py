"""Telegram WebApp initData verification with Redis token cache."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from typing import Optional
from urllib.parse import parse_qsl

from .redis_client import get_redis


# Telegram recommends rejecting initData older than this
MAX_AGE_SECONDS = 86400  # 24 hours
# How long to cache a verified session in Redis
SESSION_TTL = 3600  # 1 hour; refreshed on each reconnect


def _verify_signature(init_data: str, bot_token: str) -> Optional[dict]:
    if not init_data:
        return None
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        return None

    data_check = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received_hash):
        return None

    user_raw = pairs.get("user")
    if not user_raw:
        return None
    try:
        user = json.loads(user_raw)
    except json.JSONDecodeError:
        return None

    return {
        "id": int(user["id"]),
        "first_name": user.get("first_name", ""),
        "username": user.get("username"),
        "start_param": pairs.get("start_param"),
        "auth_date": int(pairs.get("auth_date", 0)),
    }


def verify_init_data(init_data: str, bot_token: str) -> Optional[dict]:
    """Synchronous verification (used at startup). Returns user dict or None."""
    return _verify_signature(init_data, bot_token)


async def verify_init_data_cached(init_data: str, bot_token: str) -> Optional[dict]:
    """Verify initData with Redis caching. Extends session TTL on each use."""
    if not init_data:
        return None

    redis = await get_redis()
    cache_key = f"durak:auth:{hashlib.sha256(init_data.encode()).hexdigest()}"

    if redis:
        try:
            cached = await redis.get(cache_key)
            if cached:
                user = json.loads(cached)
                # Refresh TTL so active users stay logged in
                await redis.expire(cache_key, SESSION_TTL)
                return user
        except Exception:
            pass

    # Full crypto verification
    user = _verify_signature(init_data, bot_token)
    if not user:
        return None

    # Reject stale tokens
    if user.get("auth_date", 0):
        age = time.time() - user["auth_date"]
        if age > MAX_AGE_SECONDS:
            return None

    if redis:
        try:
            await redis.setex(cache_key, SESSION_TTL, json.dumps(user))
        except Exception:
            pass

    return user
