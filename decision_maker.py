import json
import os
from dataclasses import dataclass
from typing import Iterable, List, Optional


@dataclass
class PreflopContext:
    """Context for preflop decision making."""
    position: str                       # UTG, HJ, CO, BTN, SB, BB
    hero_action_type: str               # "unopened", "vs_open", "vs_3bet"
    vs_position: Optional[str] = None   # Position of opener (e.g., "CO") or 3-bettor
    effective_stack_bb: float = 100.0   # Stack size in BB


class DecisionMaker:
    def __init__(
        self,
        call_threshold: float = 1.0,
        raise_threshold: float = 5.0,
        wide_range_cutoff: float = 0.55,
        pfr_chart_path: str = 'pfr_chart.json',
    ):
        self.call_threshold = call_threshold
        self.raise_threshold = raise_threshold
        self.wide_range_cutoff = wide_range_cutoff
        self.pfr_chart = self._load_pfr_chart(pfr_chart_path)

    def calculate_ev(
        self,
        equity_pct: float,
        potential_pot: float,
        cost_to_call: float,
    ) -> float:
        equity = max(0.0, min(equity_pct / 100.0, 1.0))
        return (equity * potential_pot) - ((1.0 - equity) * cost_to_call)

    def is_range_wide(self, active_range: Iterable[str]) -> bool:
        active_count = len(list(active_range))
        return active_count / 169.0 >= self.wide_range_cutoff

    def _load_pfr_chart(self, path: str) -> dict:
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as fh:
                    return json.load(fh)
            except Exception:
                pass
        # default minimal chart with new nested structure (fallback)
        return {
            'cash_100bb': {
                'UTG': {
                    'open': ['AA', 'KK', 'QQ', 'JJ', 'TT', 'AKs', 'AQs', 'AKo'],
                    'vs_open': {
                        'call_default': [],
                        '3bet_default': []
                    },
                    'vs_3bet': ['AA', 'KK', 'QQ', 'AKs', 'AKo']
                },
                'HJ': {
                    'open': ['AA', 'KK', 'QQ', 'JJ', 'TT', '99', 'AKs', 'AQs', 'AJs', 'KQs', 'AKo', 'AQo'],
                    'vs_open': {
                        'call_UTG': ['JJ', 'TT', '99', 'AQs', 'AJs', 'KQs', 'QJs'],
                        '3bet_UTG': ['AA', 'KK', 'QQ', 'AKs', 'AKo', 'AQs'],
                        'call_default': [],
                        '3bet_default': []
                    },
                    'vs_3bet': ['AA', 'KK', 'QQ', 'AKs', 'AKo']
                },
                'CO': {
                    'open': ['AA', 'KK', 'QQ', 'JJ', 'TT', '99', '88', '77', 'AKs', 'AQs', 'AJs', 'ATs', 'KQs', 'KJs', 'QJs', 'JTs', 'AKo', 'AQo', 'AJo', 'KQo'],
                    'vs_open': {
                        'call_UTG': ['99', '88', '77', '66', 'AQs', 'AJs', 'ATs', 'KQs', 'QJs', 'JTs'],
                        '3bet_UTG': ['AA', 'KK', 'QQ', 'JJ', 'AKs', 'AKo', 'AQs', 'AQo'],
                        'call_HJ': ['99', '88', '77', '66', 'AQs', 'AJs', 'ATs', 'KQs', 'QJs', 'JTs'],
                        '3bet_HJ': ['AA', 'KK', 'QQ', 'JJ', 'AKs', 'AKo', 'AQs', 'AQo'],
                        'call_default': [],
                        '3bet_default': []
                    },
                    'vs_3bet': ['AA', 'KK', 'QQ', 'AKs', 'AKo']
                },
                'BTN': {
                    'open': ['AA', 'KK', 'QQ', 'JJ', 'TT', '99', '88', '77', '66', 'AKs', 'AQs', 'AJs', 'ATs', 'A9s', 'A8s', 'A7s', 'A5s', 'KQs', 'KJs', 'KTs', 'QJs', 'QTs', 'JTs', 'T9s', 'AKo', 'AQo', 'AJo', 'KQo'],
                    'vs_open': {
                        'call_UTG': ['99', '88', '77', '66', '55', '44', 'AQs', 'AJs', 'ATs', 'A9s', 'KQs', 'KJs', 'QJs', 'JTs'],
                        '3bet_UTG': ['AA', 'KK', 'QQ', 'JJ', 'AKs', 'AKo', 'AQs', 'AQo', 'AJs'],
                        'call_HJ': ['99', '88', '77', '66', '55', 'AQs', 'AJs', 'ATs', 'KQs', 'QJs', 'JTs'],
                        '3bet_HJ': ['AA', 'KK', 'QQ', 'JJ', 'AKs', 'AKo', 'AQs', 'AQo'],
                        'call_CO': ['99', '88', '77', '66', '55', '44', 'AQs', 'AJs', 'ATs', 'A9s', 'KQs', 'KJs', 'QJs', 'JTs'],
                        '3bet_CO': ['AA', 'KK', 'QQ', 'JJ', 'AKs', 'AKo', 'AQs', 'AQo', 'AJs'],
                        'call_default': [],
                        '3bet_default': []
                    },
                    'vs_3bet': ['AA', 'KK', 'QQ', 'AKs', 'AKo']
                },
                'SB': {
                    'open': ['AA', 'KK', 'QQ', 'JJ', 'TT', '99', '88', '77', '66', '55', 'AKs', 'AQs', 'AJs', 'ATs', 'A9s', 'A8s', 'A7s', 'A6s', 'A5s', 'KQs', 'KJs', 'KTs', 'K9s', 'QJs', 'QTs', 'JTs', 'T9s', '98s', 'AKo', 'AQo', 'AJo', 'ATo', 'KQo', 'KJo'],
                    'vs_open': {
                        'call_UTG': ['99', '88', '77', '66', '55', 'AQs', 'AJs', 'ATs', 'A9s', 'KQs', 'KJs', 'QJs', 'JTs'],
                        '3bet_UTG': ['AA', 'KK', 'QQ', 'JJ', 'AKs', 'AKo', 'AQs', 'AQo'],
                        'call_HJ': ['99', '88', '77', '66', '55', 'AQs', 'AJs', 'ATs', 'A9s', 'KQs', 'KJs', 'QJs', 'JTs'],
                        '3bet_HJ': ['AA', 'KK', 'QQ', 'JJ', 'AKs', 'AKo', 'AQs', 'AQo'],
                        'call_CO': ['99', '88', '77', '66', '55', 'AQs', 'AJs', 'ATs', 'A9s', 'KQs', 'KJs', 'QJs', 'JTs'],
                        '3bet_CO': ['AA', 'KK', 'QQ', 'JJ', 'AKs', 'AKo', 'AQs', 'AQo'],
                        'call_BTN': ['99', '88', '77', '66', '55', 'AQs', 'AJs', 'ATs', 'A9s', 'KQs', 'KJs', 'QJs', 'JTs'],
                        '3bet_BTN': ['AA', 'KK', 'QQ', 'JJ', 'AKs', 'AKo', 'AQs', 'AQo'],
                        'call_default': [],
                        '3bet_default': []
                    },
                    'vs_3bet': ['AA', 'KK', 'QQ', 'AKs', 'AKo']
                },
                'BB': {
                    'open': [],
                    'vs_open': {
                        'call_UTG': ['77', '66', '55', '44', '33', '22', 'AJs', 'ATs', 'A9s', 'A8s', 'KJs', 'QJs', 'JTs'],
                        '3bet_UTG': ['AA', 'KK', 'QQ', 'JJ', 'AKs', 'AKo', 'AQs', 'AQo', 'AJs'],
                        'call_HJ': ['77', '66', '55', '44', '33', '22', 'AJs', 'ATs', 'A9s', 'A8s', 'KJs', 'QJs', 'JTs'],
                        '3bet_HJ': ['AA', 'KK', 'QQ', 'JJ', 'AKs', 'AKo', 'AQs', 'AQo', 'AJs'],
                        'call_CO': ['77', '66', '55', '44', '33', '22', 'AJs', 'ATs', 'A9s', 'A8s', 'KJs', 'QJs', 'JTs'],
                        '3bet_CO': ['AA', 'KK', 'QQ', 'JJ', 'AKs', 'AKo', 'AQs', 'AQo', 'AJs'],
                        'call_BTN': ['77', '66', '55', '44', '33', '22', 'AJs', 'ATs', 'A9s', 'A8s', 'KJs', 'QJs', 'JTs'],
                        '3bet_BTN': ['AA', 'KK', 'QQ', 'JJ', 'AKs', 'AKo', 'AQs', 'AQo', 'AJs'],
                        'call_SB': ['77', '66', '55', '44', '33', '22', 'AJs', 'ATs', 'A9s', 'A8s', 'KJs', 'QJs', 'JTs'],
                        '3bet_SB': ['AA', 'KK', 'QQ', 'JJ', 'AKs', 'AKo', 'AQs', 'AQo', 'AJs'],
                        'call_default': [],
                        '3bet_default': []
                    },
                    'vs_3bet': ['AA', 'KK', 'QQ', 'AKs', 'AKo']
                }
            }
        }

    @staticmethod
    def _cards_to_combo(hero_cards: List[str]) -> str:
        # hero_cards like ['As','Kh'] or ['A','K'] with suits optional
        if not hero_cards or len(hero_cards) < 2:
            return ''
        a = hero_cards[0].strip()
        b = hero_cards[1].strip()
        rank_map = lambda c: c[0].upper()
        ra = rank_map(a)
        rb = rank_map(b)
        if ra == rb:
            return ra + rb
        # determine suit if present
        sa = a[1].lower() if len(a) > 1 else ''
        sb = b[1].lower() if len(b) > 1 else ''
        high, low = (ra, rb) if 'AKQJT98765432'.index(ra) < 'AKQJT98765432'.index(rb) else (rb, ra)
        suited = sa and sb and sa == sb
        return f"{high}{low}{'s' if suited else 'o'}"

    def choose_preflop_action(self, hero_cards: List[str], context: PreflopContext) -> str:
        """Choose preflop action based on hero cards and game context."""
        combo = self._cards_to_combo(hero_cards)
        pos = (context.position or 'BTN').upper()
        action_type = (context.hero_action_type or 'unopened').lower()

        # Get the chart, default to cash_100bb
        chart = self.pfr_chart.get('cash_100bb', {})
        pos_ranges = chart.get(pos, {})

        # Branch on action type
        if action_type == 'unopened':
            open_range = pos_ranges.get('open', [])
            if combo in open_range:
                return 'Raise_3BB'
            return 'Fold'

        elif action_type == 'vs_open':
            vs_open_ranges = pos_ranges.get('vs_open', {})
            # Construct key from vs_position, e.g., 'call_CO' or '3bet_CO'
            vs_pos = (context.vs_position or 'CO').upper()
            call_key = f'call_{vs_pos}'
            bet_key = f'3bet_{vs_pos}'

            call_range = vs_open_ranges.get(call_key, [])
            if not call_range:
                call_range = vs_open_ranges.get('call_default', [])
            if not call_range:
                call_range = ['AA', 'KK', 'QQ', 'AKs']

            bet_range = vs_open_ranges.get(bet_key, [])
            if not bet_range:
                bet_range = vs_open_ranges.get('3bet_default', [])
            if not bet_range:
                bet_range = ['AA', 'KK', 'QQ', 'AKs']

            if combo in bet_range:
                return 'Raise_Pot'
            if combo in call_range:
                return 'Call'
            return 'Fold'

        elif action_type == 'vs_3bet':
            vs_3bet_range = pos_ranges.get('vs_3bet', [])
            if not vs_3bet_range:
                vs_3bet_range = ['AA', 'KK', 'QQ', 'AKs']
            if combo in vs_3bet_range:
                return 'Raise_Pot'
            return 'Fold'

        # Default fallback
        return 'Fold'

    def choose_action(
        self,
        equity_pct: float,
        pot_size: float,
        amount_to_call: float,
        bankroll: float,
        active_range: Iterable[str],
    ) -> str:
        if amount_to_call is None or pot_size is None:
            return 'Fold'
        if amount_to_call > bankroll:
            return 'Fold'

        potential_pot = max(0.0, pot_size + amount_to_call)
        cost = max(0.0, amount_to_call)
        ev = self.calculate_ev(equity_pct, potential_pot, cost)

        if ev < 0:
            return 'Fold'
        if ev < self.call_threshold:
            # If there's nothing to call, prefer checking instead of calling
            if cost == 0.0:
                return 'Check'
            return 'Call'

        if ev >= self.raise_threshold and self.is_range_wide(active_range):
            # Determine sizing based on EV strength and simple board texture proxy
            # Stronger EV -> larger sizing
            if ev >= self.raise_threshold * 3 or (bankroll > 0 and ev >= bankroll * 0.5):
                return 'Raise_AllIn'
            if ev >= self.raise_threshold * 1.5:
                return 'Raise_Pot'
            return 'Raise_Half'

        # If cost to call is zero and we decide to continue, prefer a check label
        if cost == 0.0:
            return 'Check'
        return 'Call'

