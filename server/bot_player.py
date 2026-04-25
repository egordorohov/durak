"""Simple AI opponent for single-player testing."""
from __future__ import annotations

import asyncio
import random
from typing import Optional

from . import game as G

BOT_ID  = -1
BOT_ID2 = -2
BOT_ID3 = -3
BOT_IDS = {BOT_ID, BOT_ID2, BOT_ID3}
BOT_NAME  = "Бот"
BOT_NAMES = {BOT_ID: "Бот", BOT_ID2: "Бот 2", BOT_ID3: "Бот 3"}

THINK_SHORT       = (0.8, 1.4)
THINK_DONE        = (2.5, 4.0)
THINK_LONG        = (1.2, 2.0)
THINK_HUMAN_FIRST = (4.5, 7.0)  # wait before throwing when human hasn't acted yet

REACT_CHANCE = 0.25
EMOJIS_WIN   = ["😄", "😎", "🔥", "👏", "😏"]
EMOJIS_TAKE  = ["😅", "😬", "🤡", "😤", "😩"]
EMOJIS_ATK   = ["⚡", "😈", "🃏", "💪"]


async def _think(range_: tuple[float, float]) -> None:
    await asyncio.sleep(random.uniform(*range_))


def _human_unacted(state: G.GameState) -> bool:
    """True if a human eligible player hasn't thrown or passed yet this round."""
    eligible = G._throwing_eligible(state)
    return any(
        p for p in eligible
        if p not in BOT_IDS and p != state.defender and p not in state.passed
    )


def _lowest_non_trump(cards: list[str], trump: str, rv: dict) -> Optional[str]:
    non = [c for c in cards if G.card_suit(c) != trump]
    if non:
        return min(non, key=lambda c: rv.get(G.card_rank(c), 0))
    return min(cards, key=lambda c: rv.get(G.card_rank(c), 0)) if cards else None


def _best_defence(attack: str, hand: list[str], trump: str, rv: dict) -> Optional[str]:
    candidates = [c for c in hand if G.beats(attack, c, trump, rv)]
    if not candidates:
        return None
    same = [c for c in candidates if G.card_suit(c) == G.card_suit(attack)]
    pool = same if same else candidates
    return min(pool, key=lambda c: rv.get(G.card_rank(c), 0))


def _choose_attack(state: G.GameState, bot_pid: int) -> Optional[str]:
    hand = list(state.hands[bot_pid])
    trump = state.trump
    rv = state.rank_value
    if not state.table:
        return _lowest_non_trump(hand, trump, rv)
    table_ranks = G.table_ranks(state)
    undef = G._undefended_count(state)
    if undef >= len(state.hands[state.defender]):
        return None
    if len(state.table) >= 6:
        return None
    throwable = [c for c in hand if G.card_rank(c) in table_ranks]
    if not throwable:
        return None
    return _lowest_non_trump(throwable, trump, rv)


def _should_take(state: G.GameState, bot_pid: int) -> bool:
    hand = list(state.hands[bot_pid])
    rv = state.rank_value
    for pair in state.table:
        if pair.defend is None:
            if _best_defence(pair.attack, hand, state.trump, rv) is None:
                return True
            beat = _best_defence(pair.attack, hand, state.trump, rv)
            if beat:
                hand.remove(beat)
    return False


async def run_bot(state_getter, action_cb, stop_event: asyncio.Event, bot_pid: int = BOT_ID,
                  react_cb=None, speed_up_getter=None) -> None:
    while not stop_event.is_set():
        await asyncio.sleep(0.15 if (speed_up_getter and speed_up_getter()) else 0.4)

        state = state_getter()
        if state is None or state.phase != G.Phase.PLAYING:
            if state and state.phase == G.Phase.FINISHED:
                break
            continue

        if bot_pid not in state.hands:
            continue

        hand = list(state.hands.get(bot_pid, []))
        fast = speed_up_getter and speed_up_getter()
        SHORT = (0.1, 0.2) if fast else THINK_SHORT
        LONG  = (0.2, 0.4) if fast else THINK_LONG
        DONE  = (0.1, 0.2) if fast else THINK_DONE

        if state.attacker == bot_pid:
            if not hand:
                if bot_pid not in state.passed:
                    await _think(SHORT)
                    action_cb("done")
                continue
            if state.defending_takes:
                if bot_pid not in state.passed:
                    card = _choose_attack(state, bot_pid)
                    if card:
                        think = SHORT if fast else (THINK_HUMAN_FIRST if _human_unacted(state) else SHORT)
                        await _think(think)
                        if react_cb and random.random() < REACT_CHANCE:
                            react_cb(random.choice(EMOJIS_ATK))
                        action_cb("attack", card=card)
                    else:
                        await _think(SHORT)
                        action_cb("pass")
            else:
                card = _choose_attack(state, bot_pid)
                if card:
                    think = SHORT if fast else (THINK_HUMAN_FIRST if _human_unacted(state) else SHORT)
                    await _think(think)
                    action_cb("attack", card=card)
                elif state.table and G._undefended_count(state) == 0 and bot_pid not in state.passed:
                    await _think(SHORT)
                    if react_cb and random.random() < REACT_CHANCE:
                        react_cb(random.choice(EMOJIS_WIN))
                    action_cb("done")
        elif state.attacker != bot_pid and state.defender != bot_pid:
            if bot_pid not in G._throwing_eligible(state):
                continue
            if not state.table or bot_pid in state.passed:
                continue
            if not hand:
                await _think(SHORT)
                action_cb("pass")
                continue
            undef = G._undefended_count(state)
            if undef == 0 or state.defending_takes:
                card = _choose_attack(state, bot_pid)
                if card:
                    think = SHORT if fast else (THINK_HUMAN_FIRST if _human_unacted(state) else SHORT)
                    await _think(think)
                    if react_cb and random.random() < REACT_CHANCE:
                        react_cb(random.choice(EMOJIS_ATK))
                    action_cb("attack", card=card)
                else:
                    await _think(SHORT)
                    action_cb("pass")
        elif state.defender == bot_pid:
            if _should_take(state, bot_pid):
                await _think(LONG)
                if react_cb and random.random() < REACT_CHANCE:
                    react_cb(random.choice(EMOJIS_TAKE))
                action_cb("take")
            else:
                hand = list(state.hands[bot_pid])
                if (state.mode == "perevodnoy" and state.table and
                        G._undefended_count(state) == len(state.table) and
                        len(state.table) < 6 and not state.defending_takes):
                    next_pid = state.players[(state.defender_idx + 1) % len(state.players)]
                    if len(state.hands.get(next_pid, [])) >= len(state.table) + 1:
                        ranks = G.table_ranks(state)
                        transfer_cards = [c for c in hand if G.card_rank(c) in ranks]
                        if transfer_cards:
                            card = max(transfer_cards, key=lambda c: state.rank_value.get(G.card_rank(c), 0))
                            await _think(SHORT)
                            action_cb("transfer", card=card)
                            continue
                for pair in state.table:
                    if pair.defend is None:
                        beat = _best_defence(pair.attack, hand, state.trump, state.rank_value)
                        if beat:
                            await _think(LONG)
                            action_cb("defend", attack=pair.attack, card=beat)
                            hand.remove(beat)
                            break
