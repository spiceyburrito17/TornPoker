import random
from typing import Dict, Iterable, List, Optional, Tuple

try:
    from treys import Card, Evaluator
except ImportError:
    raise ImportError('treys is required for monte_carlo.py')

RANKS = ['A', 'K', 'Q', 'J', 'T', '9', '8', '7', '6', '5', '4', '3', '2']
SUITS = ['s', 'h', 'd', 'c']

class MonteCarloSolver:
    def __init__(self, trials: int = 1000):
        self.trials = max(100, trials)
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
        hero_list = self._normalize_cards(hero_cards)
        board_list = self._normalize_cards(community_cards)
        print(f"[MC DEBUG] hero={hero_cards}→{hero_list} board={community_cards}→{board_list} range_len={len(self._build_actual_range(opponent_range, set(hero_list + board_list)))}")
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
                # treys expects rank uppercase, suit lowercase (e.g. "Js" not "JS")
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
        # Generate all cross-suit combinations: for each suit of the high card,
        # pair it with every different suit of the low card (4 * 3 = 12 combos).
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
