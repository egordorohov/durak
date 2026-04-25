"""Подкидной / переводной дурак, 2-4 игрока, 36 или 52 карты."""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

SUITS = ("S", "C", "H", "D")  # ♠ ♣ ♥ ♦
RANKS_36 = ("6", "7", "8", "9", "10", "J", "Q", "K", "A")
RANKS_52 = ("2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A")
RANK_VALUE_36 = {r: i for i, r in enumerate(RANKS_36)}
RANK_VALUE_52 = {r: i for i, r in enumerate(RANKS_52)}
RANK_VALUE = RANK_VALUE_36  # default for backward compat

def card(rank: str, suit: str) -> str:
    return f"{rank}{suit}"

def card_rank(c: str) -> str:
    return c[:-1]

def card_suit(c: str) -> str:
    return c[-1]


class Phase(str, Enum):
    WAITING = "waiting"
    PLAYING = "playing"
    FINISHED = "finished"


@dataclass
class Pair:
    attack: str
    defend: Optional[str] = None
    by: int = 0  # pid who threw the attack card


@dataclass
class GameState:
    players: list[int]
    hands: dict[int, list[str]] = field(default_factory=dict)
    deck: list[str] = field(default_factory=list)
    trump: str = ""
    trump_card: Optional[str] = None
    table: list[Pair] = field(default_factory=list)
    attacker_idx: int = 0
    phase: Phase = Phase.WAITING
    winner: Optional[int] = None
    loser: Optional[int] = None
    last_action: Optional[dict] = None
    passed: set = field(default_factory=set)
    mode: str = "perevodnoy"
    bet: int = 100
    deck_size: int = 36
    rank_value: dict = field(default_factory=lambda: RANK_VALUE_36)
    defending_takes: bool = False
    finish_order: list = field(default_factory=list)

    @property
    def defender_idx(self) -> int:
        if not self.players:
            return 0
        return (self.attacker_idx + 1) % len(self.players)

    @property
    def attacker(self) -> int:
        if not self.players:
            return -1
        return self.players[self.attacker_idx % len(self.players)]

    @attacker.setter
    def attacker(self, pid: int) -> None:
        self.attacker_idx = self.players.index(pid)

    @property
    def defender(self) -> int:
        if not self.players:
            return -1
        return self.players[self.defender_idx]

    @defender.setter
    def defender(self, pid: int) -> None:
        pass

    def opponent(self, pid: int) -> int:
        """For 2-player backward compat."""
        others = [p for p in self.players if p != pid]
        return others[0] if others else pid

    def active_players(self) -> list[int]:
        if self.deck:
            return list(self.players)
        return [p for p in self.players if self.hands.get(p)]


def _build_deck(deck_size: int, rng: random.Random) -> list[str]:
    ranks = RANKS_36 if deck_size == 36 else RANKS_52
    deck = [card(r, s) for s in SUITS for r in ranks]
    rng.shuffle(deck)
    return deck


def new_game(
    *player_ids: int,
    seed: Optional[int] = None,
    mode: str = "perevodnoy",
    bet: int = 100,
    deck_size: int = 36,
) -> GameState:
    if len(player_ids) < 2:
        raise ValueError("need at least 2 players")
    rng = random.Random(seed)
    deck = _build_deck(deck_size, rng)
    rv = RANK_VALUE_36 if deck_size == 36 else RANK_VALUE_52

    state = GameState(players=list(player_ids), mode=mode, bet=bet, deck_size=deck_size, rank_value=rv)
    state.hands = {pid: [] for pid in player_ids}

    for _ in range(6):
        for pid in player_ids:
            if deck:
                state.hands[pid].append(deck.pop(0))

    trump_card = deck[-1] if deck else state.hands[player_ids[0]][-1]
    state.trump = card_suit(trump_card)
    state.trump_card = trump_card if deck else None
    state.deck = deck

    state.attacker_idx, _ = _choose_first(state)
    state.phase = Phase.PLAYING
    return state


def _choose_first(state: GameState) -> tuple[int, int]:
    rv = state.rank_value
    best = None
    first_idx = 0
    for idx, pid in enumerate(state.players):
        for c in state.hands[pid]:
            if card_suit(c) == state.trump:
                v = rv[card_rank(c)]
                if best is None or v < best[0]:
                    best = (v, idx)
    if best:
        first_idx = best[1]
    defender_idx = (first_idx + 1) % len(state.players)
    return first_idx, defender_idx


def beats(attack: str, defend: str, trump: str, rank_value: dict = RANK_VALUE_36) -> bool:
    a_r, a_s = card_rank(attack), card_suit(attack)
    d_r, d_s = card_rank(defend), card_suit(defend)
    if a_s == d_s:
        return rank_value[d_r] > rank_value[a_r]
    if d_s == trump and a_s != trump:
        return True
    return False


def table_ranks(state: GameState) -> set[str]:
    out: set[str] = set()
    for p in state.table:
        out.add(card_rank(p.attack))
        if p.defend:
            out.add(card_rank(p.defend))
    return out


def _undefended_count(state: GameState) -> int:
    return sum(1 for p in state.table if p.defend is None)


def _throwing_eligible(state: GameState) -> set[int]:
    """All non-defending players — everyone gets asked Пас regardless of hand."""
    return {p for p in state.players if p != state.defender}


# ────── actions ──────
class GameError(Exception):
    pass


def attack(state: GameState, pid: int, c: str) -> None:
    if state.phase != Phase.PLAYING:
        raise GameError("игра не идёт")
    if pid == state.defender:
        raise GameError("вы защищаетесь")
    if pid != state.attacker and not state.table:
        raise GameError("не ваш ход")
    if c not in state.hands[pid]:
        raise GameError("нет такой карты")
    if state.table:
        if pid not in _throwing_eligible(state):
            raise GameError("только не-защитник может подкидывать")
        if card_rank(c) not in table_ranks(state):
            raise GameError("подкидывать можно только ранги со стола")
        if len(state.table) >= 6:
            raise GameError("максимум 6 пар")
        if not state.defending_takes:
            if _undefended_count(state) >= len(state.hands[state.defender]):
                raise GameError("у соперника не хватит карт отбиться")
    state.hands[pid].remove(c)
    state.table.append(Pair(attack=c, by=pid))
    state.passed.clear()  # any new card resets post-take pass confirmations
    state.last_action = {"type": "attack", "by": pid, "card": c}


def defend(state: GameState, pid: int, attack_card: str, defend_card: str) -> None:
    if state.phase != Phase.PLAYING:
        raise GameError("игра не идёт")
    if pid != state.defender:
        raise GameError("вы не защищаетесь")
    if defend_card not in state.hands[pid]:
        raise GameError("нет такой карты")
    target = next((p for p in state.table if p.attack == attack_card and p.defend is None), None)
    if not target:
        raise GameError("нет такой атаки")
    if not beats(attack_card, defend_card, state.trump, state.rank_value):
        raise GameError("эта карта не бьёт")
    state.hands[pid].remove(defend_card)
    target.defend = defend_card
    state.last_action = {"type": "defend", "by": pid, "attack": attack_card, "card": defend_card}
    # If all cards now defended and deck empty, auto-pass empty-hand players and maybe finalize
    if _undefended_count(state) == 0 and not state.deck and not state.defending_takes:
        _auto_pass_empty(state)
        eligible = _throwing_eligible(state)
        if all(p in state.passed for p in eligible):
            _finalize_done(state)


def transfer(state: GameState, pid: int, c: str) -> None:
    """Defender transfers attack by playing same-rank card (переводной)."""
    if state.phase != Phase.PLAYING:
        raise GameError("игра не идёт")
    if pid != state.defender:
        raise GameError("перевести может только защищающийся")
    if c not in state.hands[pid]:
        raise GameError("нет такой карты")
    if _undefended_count(state) != len(state.table):
        raise GameError("нельзя перевести — часть карт уже отбита")
    if card_rank(c) not in table_ranks(state):
        raise GameError("ранг карты не совпадает с атакой")
    if len(state.table) >= 6:
        raise GameError("максимум 6 пар")
    new_def_pid = state.players[(state.defender_idx + 1) % len(state.players)]
    if len(state.hands[new_def_pid]) < len(state.table) + 1:
        raise GameError("у следующего игрока недостаточно карт для приёма")
    state.hands[pid].remove(c)
    state.table.append(Pair(attack=c, by=pid))
    state.attacker_idx = state.defender_idx  # old defender becomes new attacker
    state.passed.clear()
    state.last_action = {"type": "transfer", "by": pid, "card": c}


def take(state: GameState, pid: int) -> None:
    """Defender declares intent to take all cards.
    Attacking-eligible players may still throw more cards.
    Round finalizes when all eligible players pass."""
    if pid != state.defender:
        raise GameError("брать может только защищающийся")
    if not state.table:
        raise GameError("нечего брать")
    if state.defending_takes:
        raise GameError("взятие уже объявлено")
    state.defending_takes = True
    state.passed.clear()
    state.last_action = {"type": "take", "by": pid}


def done(state: GameState, pid: int) -> None:
    """Attacker votes бито — round ends only when all eligible have voted."""
    if state.phase != Phase.PLAYING:
        raise GameError("игра не идёт")
    if pid != state.attacker:
        raise GameError("закрывать ход может только атакующий")
    if not state.table:
        # Attacker has no cards to open the round — skip turn immediately
        if not state.hands.get(pid):
            _finalize_done(state)
            return
        raise GameError("стол пуст")
    if _undefended_count(state) > 0:
        raise GameError("есть неотбитые карты")
    if state.defending_takes:
        raise GameError("нельзя бито — защищающийся берёт карты")
    if pid in state.passed:
        raise GameError("вы уже нажали бито")
    state.passed.add(pid)
    state.last_action = {"type": "done", "by": pid}
    _auto_pass_empty(state)
    eligible = _throwing_eligible(state)
    if all(p in state.passed for p in eligible):
        _finalize_done(state)


def pass_turn(state: GameState, pid: int) -> None:
    """Eligible player passes: either after take declared, or as co-attacker
    signaling they won't throw more (when all cards are defended)."""
    if state.phase != Phase.PLAYING:
        raise GameError("игра не идёт")
    if pid == state.defender:
        raise GameError("защищающийся не может пасовать")
    eligible = _throwing_eligible(state)
    if pid not in eligible:
        raise GameError("вы не можете пасовать здесь")
    if not state.table:
        raise GameError("стол пуст")
    if pid in state.passed:
        raise GameError("вы уже пасовали")
    if not state.defending_takes and _undefended_count(state) > 0:
        raise GameError("есть неотбитые карты")
    state.passed.add(pid)
    state.last_action = {"type": "pass", "by": pid}
    _auto_pass_empty(state)
    eligible = _throwing_eligible(state)
    if state.defending_takes:
        if all(p in state.passed for p in eligible):
            _finalize_take(state, state.defender)
    else:
        # All non-defenders voted done/pass — finalize round
        if all(p in state.passed for p in eligible):
            _finalize_done(state)


def recall(state: GameState, pid: int) -> None:
    """Return last thrown card and all subsequent cards to their owners' hands."""
    if state.phase != Phase.PLAYING:
        raise GameError("игра не идёт")
    if pid == state.defender:
        raise GameError("защитник не может вернуть карту")
    indices = [i for i, p in enumerate(state.table) if p.by == pid]
    if not indices:
        raise GameError("вы не бросали карт в этом раунде")
    cut = indices[-1]
    returning = state.table[cut:]
    del state.table[cut:]
    defender = state.defender
    for pair in returning:
        state.hands[pair.by].append(pair.attack)
        if pair.defend is not None and defender in state.hands:
            state.hands[defender].append(pair.defend)
    state.passed.clear()
    state.last_action = {"type": "recall", "by": pid}


# ────── helpers ──────
def _auto_pass_empty(state: GameState) -> None:
    """Auto-vote pass for eligible players with no cards when deck is gone."""
    if state.deck:
        return
    for pid in _throwing_eligible(state):
        if not state.hands.get(pid) and pid not in state.passed:
            state.passed.add(pid)


def _finalize_done(state: GameState) -> None:
    state.table.clear()
    state.passed.clear()
    _refill(state, taker=None)
    state.attacker_idx = state.defender_idx
    _check_end(state)


def _finalize_take(state: GameState, defender_pid: int) -> None:
    for p in state.table:
        state.hands[defender_pid].append(p.attack)
        if p.defend:
            state.hands[defender_pid].append(p.defend)
    state.table.clear()
    state.passed.clear()
    state.defending_takes = False
    _refill(state, taker=defender_pid)
    # Skip the taker: player after the taker attacks next.
    # In 2-player this wraps back to the original attacker (same as before).
    state.attacker_idx = (state.defender_idx + 1) % len(state.players)
    _check_end(state)


def _refill(state: GameState, taker: Optional[int]) -> None:
    order = list(state.players)
    if taker is not None:
        order = [p for p in order if p != taker] + [taker]
    for pid in order:
        while len(state.hands[pid]) < 6 and state.deck:
            state.hands[pid].append(state.deck.pop(0))
    if not state.deck:
        state.trump_card = None


def _check_end(state: GameState) -> None:
    if state.deck:
        return

    finished: list[int] = []
    for pid in list(state.players):
        if not state.hands.get(pid):
            idx = state.players.index(pid)
            state.players.remove(pid)
            finished.append(pid)
            if pid not in state.finish_order:
                state.finish_order.append(pid)
            if idx < state.attacker_idx:
                state.attacker_idx -= 1
            elif idx == state.attacker_idx:
                state.attacker_idx %= max(1, len(state.players))

    alive = state.players
    if len(alive) <= 1:
        state.phase = Phase.FINISHED
        if not alive:
            state.loser = None
            state.winner = finished[0] if finished else None
        else:
            state.loser = alive[0]
            state.winner = finished[0] if finished else None
    return


def view_for(state: GameState, pid: int) -> dict:
    opp = state.opponent(pid)
    undefended = _undefended_count(state)
    throwing_eligible = _throwing_eligible(state)

    all_players = []
    for p in state.players:
        all_players.append({
            "id": p,
            "is_attacker": p == state.attacker,
            "is_defender": p == state.defender,
            "card_count": len(state.hands.get(p, [])),
        })

    return {
        "you": pid,
        "opponent": opp,
        "your_hand": list(state.hands.get(pid, [])),
        "opponent_count": len(state.hands.get(opp, [])),
        "deck_count": len(state.deck),
        "trump": state.trump,
        "trump_card": state.trump_card,
        "table": [{"attack": p.attack, "defend": p.defend} for p in state.table],
        "attacker": state.attacker,
        "defender": state.defender,
        "phase": state.phase.value,
        "winner": state.winner,
        "loser": state.loser,
        "last_action": state.last_action,
        "defending_takes": state.defending_takes,
        "bet": state.bet,
        "can_done": (
            pid == state.attacker and
            bool(state.table) and
            undefended == 0 and
            not state.defending_takes and
            pid not in state.passed and
            state.phase == Phase.PLAYING
        ),
        "can_take": (
            pid == state.defender and
            bool(state.table) and
            not state.defending_takes and
            undefended > 0 and
            state.phase == Phase.PLAYING
        ),
        "can_transfer": (
            pid == state.defender and
            state.mode == "perevodnoy" and
            not state.defending_takes and
            bool(state.table) and
            undefended == len(state.table) and
            len(state.table) < 6 and
            len(state.hands.get(state.players[(state.defender_idx + 1) % len(state.players)], [])) >= len(state.table) + 1 and
            any(card_rank(c) in table_ranks(state) for c in state.hands.get(pid, []))
        ),
        "can_recall": (
            pid != state.defender and
            any(p.by == pid for p in state.table) and
            not state.defending_takes and
            state.phase == Phase.PLAYING
        ),
        # Can throw: eligible + table not empty
        "can_throw": (
            pid in throwing_eligible and
            pid != state.defender and
            bool(state.table)
        ),
        # Пас: after take declared everyone passes; when all defended co-attackers pass
        "can_pass": (
            pid in throwing_eligible and
            pid != state.defender and
            bool(state.table) and
            pid not in state.passed and
            state.phase == Phase.PLAYING and
            (
                state.defending_takes or           # all eligible pass to finalize take
                (undefended == 0 and pid != state.attacker)  # co-attacker when all defended
            )
        ),
        "all_players": all_players,
        "passed_players": list(state.passed),
        "payouts": getattr(state, "payouts", {}),
        "mode": state.mode,
        "deck_size": state.deck_size,
        "finish_order": list(state.finish_order),
    }
