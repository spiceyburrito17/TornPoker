import random
from typing import Dict, Iterable, List, Optional, Tuple

# ─── Feature Flag ───────────────────────────────────────────────────────────
USE_PHEVALUATOR = True

if USE_PHEVALUATOR:
    from phevaluator import evaluate_cards as _pheval
else:
    pass  # treys imported below in legacy path

try:
    from treys import Card, Evaluator
except ImportError:
    if not USE_PHEVALUATOR:
        raise ImportError('treys is required when USE_PHEVALUATOR=False')

RANKS = ['A', 'K', 'Q', 'J', 'T', '9', '8', '7', '6', '5', '4', '3', '2']
SUITS = ['s', 'h', 'd', 'c']


# ─── Card normalization ────────────────────────────────────────────────────
def _normalize_card_str(card: str) -> str:
    """Normalize card string to Rank(upper) + suit(lower), e.g. 'ah' -> 'Ah'"""
    if not card or len(card) < 2:
        return card
    return card[0].upper() + card[1].lower()


class MonteCarloSolver:
    def __init__(self, trials: int = 1000):
        self.trials = max(100, trials)
        if not USE_PHEVALUATOR:
            self.evaluator = Evaluator()

    def estimate_equity(
        self,
        hero_cards: List[str],
        community_cards: List[str],
        opponent_range: Iterable[str],
        trials: Optional[int] = None,
    ) -> float:
        if not hero_cards or hero_cards is None:
            return 0.0
        trials = self.trials if trials is None else max(10, trials)

        if USE_PHEVALUATOR:
            return self._estimate_equity_phevaluator(hero_cards, community_cards, opponent_range, trials)
        else:
            return self._estimate_equity_treys(hero_cards, community_cards, opponent_range, trials)

    # ─── phevaluator path (new default) ───────────────────────────────────
    def _estimate_equity_phevaluator(
        self,
        hero_cards: List[str],
        community_cards: List[str],
        opponent_range: Iterable[str],
        trials: int,
    ) -> float:
        hero_str = [_normalize_card_str(c) for c in hero_cards if c and len(c) >= 2]
        board_str = [_normalize_card_str(c) for c in community_cards if c and len(c) >= 2]
        blocked_str = set(hero_str + board_str)

        actual_opponent_hands = self._build_range_str(opponent_range, blocked_str)
        if not actual_opponent_hands:
            return 0.0

        deck = [r + s for r in RANKS for s in SUITS]
        available_deck = [c for c in deck if c not in blocked_str]
        cards_needed = 5 - len(board_str)
        if len(available_deck) < cards_needed:
            return 0.0

        hero_wins = 0
        ties = 0
        valid = 0
        for _ in range(trials):
            opp = random.choice(actual_opponent_hands)
            if opp[0] in blocked_str or opp[1] in blocked_str:
                continue
            opp_blocked = set(opp)
            avail = [c for c in available_deck if c not in opp_blocked]
            if len(avail) < cards_needed:
                continue
            if cards_needed > 0:
                runout = random.sample(avail, cards_needed)
                full_board = board_str + runout
            else:
                full_board = board_str

            hero_rank = _pheval(*(hero_str + full_board))
            opp_rank = _pheval(*(list(opp) + full_board))

            if hero_rank < opp_rank:
                hero_wins += 1
            elif hero_rank == opp_rank:
                ties += 1
            valid += 1

        if valid == 0:
            return 0.0
        equity = float(hero_wins + ties * 0.5) / float(valid)
        return round(equity * 100.0, 2)

    # ─── Range building (string-based, for phevaluator) ──────────────────
    def _build_range_str(self, opponent_range: Iterable[str], blocked: set) -> List[Tuple[str, str]]:
        combos = []
        for combo in opponent_range:
            if len(combo) == 2:
                combos.extend(self._gen_pair_str(combo, blocked))
            elif len(combo) == 3 and combo[2] in {'s', 'o'}:
                if combo[2] == 's':
                    combos.extend(self._gen_suited_str(combo[:2], blocked))
                else:
                    combos.extend(self._gen_offsuit_str(combo[:2], blocked))
        return combos

    def _gen_pair_str(self, pair: str, blocked: set) -> List[Tuple[str, str]]:
        rank = pair[0].upper()
        cards = [rank + s for s in SUITS]
        result = []
        for i in range(len(cards)):
            for j in range(i + 1, len(cards)):
                if cards[i] not in blocked and cards[j] not in blocked:
                    result.append((cards[i], cards[j]))
        return result

    def _gen_suited_str(self, pair: str, blocked: set) -> List[Tuple[str, str]]:
        hi, lo = pair[0].upper(), pair[1].upper()
        result = []
        for s in SUITS:
            c1, c2 = hi + s, lo + s
            if c1 not in blocked and c2 not in blocked:
                result.append((c1, c2))
        return result

    def _gen_offsuit_str(self, pair: str, blocked: set) -> List[Tuple[str, str]]:
        hi, lo = pair[0].upper(), pair[1].upper()
        result = []
        for s1 in SUITS:
            for s2 in SUITS:
                if s1 == s2:
                    continue
                c1, c2 = hi + s1, lo + s2
                if c1 not in blocked and c2 not in blocked:
                    result.append((c1, c2))
        return result

    # ─── treys fallback path (original) ──────────────────────────────────
    def _estimate_equity_treys(
        self,
        hero_cards: List[str],
        community_cards: List[str],
        opponent_range: Iterable[str],
        trials: int,
    ) -> float:
        hero_list = self._normalize_cards(hero_cards)
        board_list = self._normalize_cards(community_cards)
        blocked = set(hero_list + board_list)
        actual_opponent_hands = self._build_actual_range(opponent_range, blocked)
        if not actual_opponent_hands:
            return 0.0
        available_deck = [card for card in self._full_deck() if card not in blocked]
        if len(available_deck) < 5 - len(board_list):
            return 0.0
        hero_wins = 0
        ties = 0
        for _ in range(trials):
            opp_hole = random.choice(actual_opponent_hands)
            if self._cards_overlap(opp_hole, blocked):
                continue
            board = list(board_list)
            if len(board) < 5:
                runout = random.sample([c for c in available_deck if c not in opp_hole], 5 - len(board))
                board.extend(runout)
            try:
                hero_score = self.evaluator.evaluate(board, hero_list)
                opp_score = self.evaluator.evaluate(board, list(opp_hole))
            except Exception:
                continue
            if hero_score < opp_score:
                hero_wins += 1
            elif hero_score == opp_score:
                ties += 1
        equity = float(hero_wins + ties * 0.5) / float(trials)
        return round(equity * 100.0, 2)

    def _normalize_cards(self, cards: Optional[List[str]]) -> List[int]:
        if not cards:
            return []
        normalized = []
        for card in cards:
            if not isinstance(card, str) or len(card) < 2:
                continue
            try:
                normalized.append(Card.new(card[0].upper() + card[1].lower()))
            except Exception:
                continue
        return normalized

    def _full_deck(self) -> List[int]:
        return [Card.new(rank + suit) for rank in RANKS for suit in SUITS]

    def _build_actual_range(self, opponent_range: Iterable[str], blocked: set) -> List[Tuple[int, int]]:
        actual = []
        for combo in opponent_range:
            if len(combo) == 2:
                actual.extend(self._generate_pair_combos(combo, blocked))
            elif len(combo) == 3 and combo[2] in {'s', 'o'}:
                if combo[2] == 's':
                    actual.extend(self._generate_suited_combos(combo[:2], blocked))
                else:
                    actual.extend(self._generate_offsuit_combos(combo[:2], blocked))
        return actual

    def _generate_pair_combos(self, pair: str, blocked: set) -> List[Tuple[int, int]]:
        rank = pair[0].upper()
        cards = [Card.new(rank + suit) for suit in SUITS]
        combos = []
        for i in range(len(cards)):
            for j in range(i + 1, len(cards)):
                if cards[i] in blocked or cards[j] in blocked:
                    continue
                combos.append((cards[i], cards[j]))
        return combos

    def _generate_suited_combos(self, pair: str, blocked: set) -> List[Tuple[int, int]]:
        hi, lo = pair[0].upper(), pair[1].upper()
        combos = []
        for suit in SUITS:
            c1 = Card.new(hi + suit)
            c2 = Card.new(lo + suit)
            if c1 in blocked or c2 in blocked:
                continue
            combos.append((c1, c2))
        return combos

    def _generate_offsuit_combos(self, pair: str, blocked: set) -> List[Tuple[int, int]]:
        hi, lo = pair[0].upper(), pair[1].upper()
        combos = []
        for suit1 in SUITS:
            for suit2 in SUITS:
                if suit1 == suit2:
                    continue
                c1 = Card.new(hi + suit1)
                c2 = Card.new(lo + suit2)
                if c1 in blocked or c2 in blocked:
                    continue
                combos.append((c1, c2))
        return combos

    def _cards_overlap(self, hole: Tuple[int, int], blocked: set) -> bool:
        return hole[0] in blocked or hole[1] in blocked
