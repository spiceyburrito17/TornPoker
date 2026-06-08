import json
import math
import os
from typing import Dict, List, Optional, Tuple

RANKS = ['A', 'K', 'Q', 'J', 'T', '9', '8', '7', '6', '5', '4', '3', '2']
SUITE_PLACEHOLDER = 's'
OFFSUIT_PLACEHOLDER = 'o'

# A baseline ordering of 169 Texas Hold'em starting combinations.
# Higher score means stronger hand.

class RangeMatrix:
    def __init__(self):
        self.opponent_ranges: Dict[str, Dict[str, bool]] = {}
        self.hand_order = self._build_hand_order()

    def _build_hand_order(self) -> List[str]:
        combos = []
        for i, hi in enumerate(RANKS):
            for j, lo in enumerate(RANKS):
                if i < j:
                    combos.append(f"{hi}{lo}{SUITE_PLACEHOLDER}")
                    combos.append(f"{hi}{lo}{OFFSUIT_PLACEHOLDER}")
                elif i == j:
                    combos.append(f"{hi}{lo}")
        return sorted(combos, key=self._hand_strength, reverse=True)

    def _hand_strength(self, combo: str) -> float:
        if len(combo) == 2:
            rank = RANKS.index(combo[0])
            return 1000.0 - rank * 10
        hi = RANKS.index(combo[0])
        lo = RANKS.index(combo[1])
        if combo[2] == SUITE_PLACEHOLDER:
            return 800.0 - hi * 8 - lo * 0.4
        return 600.0 - hi * 7 - lo * 0.2

    def add_opponent(self, player_id: str) -> None:
        if player_id not in self.opponent_ranges:
            self.opponent_ranges[player_id] = {combo: True for combo in self.hand_order}

    def remove_opponent(self, player_id: str) -> None:
        self.opponent_ranges.pop(player_id, None)

    def get_active_combos(self, player_id: str) -> List[str]:
        if player_id not in self.opponent_ranges:
            return []
        return [combo for combo, active in self.opponent_ranges[player_id].items() if active]

    def set_range(self, player_id: str, combos: List[str]) -> None:
        self.add_opponent(player_id)
        for combo in self.hand_order:
            self.opponent_ranges[player_id][combo] = combo in combos

    def narrow_top_percent(self, player_id: str, percent: float) -> None:
        self.add_opponent(player_id)
        percent = max(0.01, min(percent, 1.0))
        keep_count = max(1, int(len(self.hand_order) * percent))
        active = self.get_active_combos(player_id)
        active_set = set(active)
        ranked = [combo for combo in self.hand_order if combo in active_set]
        keep = set(ranked[:keep_count])
        for combo in self.hand_order:
            self.opponent_ranges[player_id][combo] = combo in keep

    def narrow_by_strength(self, player_id: str, target_combos: List[str]) -> None:
        self.add_opponent(player_id)
        target_set = set(target_combos)
        for combo in self.hand_order:
            self.opponent_ranges[player_id][combo] = combo in target_set

    def update_range_from_action(self, player_id: str, action: str, historical_pfr: Optional[float] = None) -> None:
        self.add_opponent(player_id)
        normalized = action.strip().lower()
        if normalized == 'call':
            self.narrow_top_percent(player_id, 0.45)
            for combo in ['AA', 'KK']:
                if combo in self.opponent_ranges[player_id]:
                    self.opponent_ranges[player_id][combo] = False
        elif normalized == 'raise':
            percent = 0.15
            if historical_pfr is not None and historical_pfr > 0:
                percent = min(max(historical_pfr / 100.0, 0.10), 0.30)
            self.narrow_top_percent(player_id, percent)
        elif normalized in {'limp', 'check'}:
            self.narrow_top_percent(player_id, 0.40)
        elif normalized == 'fold':
            for combo in self.hand_order:
                self.opponent_ranges[player_id][combo] = False

    def prune_by_board(self, player_id: str, board_cards: List[str]) -> None:
        self.add_opponent(player_id)
        if not board_cards:
            return
        blocked_cards = set()
        for card in board_cards:
            if len(card) >= 2:
                blocked_cards.add(card[0].upper() + card[1].lower())
        blocked_ranks = set(c[0] for c in blocked_cards)
        blocked_suits = {}
        for c in blocked_cards:
            blocked_suits.setdefault(c[0], set()).add(c[1])

        for combo in self.hand_order:
            if not self.opponent_ranges[player_id].get(combo, False):
                continue
            if len(combo) == 2:
                rank = combo[0]
                if rank in blocked_ranks:
                    suits_blocked = blocked_suits.get(rank, set())
                    remaining = 4 - len(suits_blocked)
                    if remaining <= 0:
                        self.opponent_ranges[player_id][combo] = False
            elif len(combo) == 3:
                hi, lo, suf = combo[0], combo[1], combo[2]
                hi_suits_blocked = blocked_suits.get(hi, set())
                lo_suits_blocked = blocked_suits.get(lo, set())
                if suf == 's':
                    available_suits = {'h', 'd', 'c', 's'} - hi_suits_blocked - lo_suits_blocked
                    if not available_suits:
                        self.opponent_ranges[player_id][combo] = False
                else:
                    hi_avail = 4 - len(hi_suits_blocked)
                    lo_avail = 4 - len(lo_suits_blocked)
                    if hi_avail <= 0 or lo_avail <= 0:
                        self.opponent_ranges[player_id][combo] = False

    def describe_range(self, player_id: str) -> str:
        active = self.get_active_combos(player_id)
        if not active:
            return 'Empty Range'
        return f"{len(active)} combos active, top {round(100.0 * len(active) / len(self.hand_order), 1)}%"

    def save(self, path: str = 'range_matrix.json') -> None:
        try:
            payload = {'ranges': self.opponent_ranges}
            with open(path, 'w', encoding='utf-8') as fh:
                json.dump(payload, fh, indent=2)
        except Exception:
            pass

    def load(self, path: str = 'range_matrix.json') -> None:
        if not os.path.exists(path):
            return
        try:
            with open(path, 'r', encoding='utf-8') as fh:
                payload = json.load(fh)
            self.opponent_ranges = payload.get('ranges', {})
        except Exception:
            self.opponent_ranges = {}
