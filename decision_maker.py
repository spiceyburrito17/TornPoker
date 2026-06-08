import json
import os
import random
from dataclasses import dataclass
from typing import Iterable, List, Optional


@dataclass
class PreflopContext:
    position: str                       # UTG, HJ, CO, BTN, SB, BB
    hero_action_type: str               # "unopened", "vs_open", "vs_3bet"
    vs_position: Optional[str] = None
    effective_stack_bb: float = 100.0


# ---------------------------------------------------------------------------
# Phase 2: Board texture scores
# ---------------------------------------------------------------------------

RANK_ORDER = 'AKQJT98765432'

def _rank_val(card: str) -> int:
    r = card[0].upper()
    return RANK_ORDER.index(r) if r in RANK_ORDER else 12


def analyze_board_texture(board: List[str]) -> dict:
    """
    Phase 2: Board Texture Analysis.
    Returns a texture dict used by choose_action() to modify bet sizing.

    Keys
    ----
    wetness       : 0.0 (dry) – 1.0 (very wet)
    flush_draw    : bool  — 3+ cards same suit
    straight_draw : bool  — 3+ consecutive or near-consecutive ranks
    paired        : bool  — at least one pair on board
    texture_label : 'DRY' | 'SEMI_WET' | 'WET'
    """
    if not board:
        return {
            'wetness': 0.0, 'flush_draw': False,
            'straight_draw': False, 'paired': False,
            'texture_label': 'DRY',
        }

    suits = [c[1].lower() for c in board if len(c) >= 2]
    ranks = sorted([_rank_val(c) for c in board])

    # Flush draw: 3+ cards of same suit
    from collections import Counter
    suit_counts = Counter(suits)
    flush_draw = max(suit_counts.values(), default=0) >= 3

    # Paired board: any duplicate ranks
    rank_vals = [_rank_val(c) for c in board]
    paired = len(rank_vals) != len(set(rank_vals))

    # Straight draw: any 3 ranks within a 5-card window
    unique_ranks = sorted(set(ranks))
    straight_draw = False
    for i in range(len(unique_ranks)):
        window = [r for r in unique_ranks if unique_ranks[i] <= r <= unique_ranks[i] + 4]
        if len(window) >= 3:
            straight_draw = True
            break

    # Wetness score (0–1)
    score = 0.0
    if flush_draw:
        score += 0.4
    if straight_draw:
        score += 0.35
    if paired:
        score += 0.1
    # Extra for monotone (all same suit)
    if max(suit_counts.values(), default=0) == len(board):
        score += 0.15
    wetness = min(round(score, 2), 1.0)

    if wetness >= 0.55:
        label = 'WET'
    elif wetness >= 0.25:
        label = 'SEMI_WET'
    else:
        label = 'DRY'

    return {
        'wetness': wetness,
        'flush_draw': flush_draw,
        'straight_draw': straight_draw,
        'paired': paired,
        'texture_label': label,
    }


# ---------------------------------------------------------------------------
# Phase 3: MDF (Minimum Defence Frequency)
# ---------------------------------------------------------------------------

def calculate_mdf(bet_size: float, pot_size: float) -> float:
    """
    Phase 3: GTO bluff-catching.
    MDF = pot / (pot + bet)
    We must defend at least this fraction of our range or opponent
    can profitably bluff 100% of the time.
    """
    if pot_size <= 0:
        return 0.67  # default half-pot MDF
    return round(pot_size / (pot_size + bet_size), 4)


def is_bluff_catcher(
    equity_pct: float,
    pot_odds_pct: float,
    mdf: float,
    hero_equity_rank: float = 0.5,
) -> bool:
    """
    Phase 3: Identify bluff catchers.
    A bluff catcher is a hand that:
      1. Has enough equity to meet pot odds (positive raw EV).
      2. Is in the top MDF fraction of our range (we MUST call it to defend).
      3. Is not strong enough to raise for value (equity < 65%).
    hero_equity_rank: where this hand ranks in our range (0=best, 1=worst).
    """
    meets_pot_odds = equity_pct >= pot_odds_pct
    must_defend    = hero_equity_rank <= mdf
    not_value      = equity_pct < 65.0
    return meets_pot_odds and must_defend and not_value


# ---------------------------------------------------------------------------
# Main DecisionMaker
# ---------------------------------------------------------------------------

class DecisionMaker:
    def __init__(
        self,
        call_threshold: float = 1.0,
        raise_threshold: float = 5.0,
        wide_range_cutoff: float = 0.55,
        pfr_chart_path: str = 'pfr_chart.json',
        postflop_tree_path: str = 'postflop_tree.json',
    ):
        self.call_threshold    = call_threshold
        self.raise_threshold   = raise_threshold
        self.wide_range_cutoff = wide_range_cutoff
        self.pfr_chart         = self._load_pfr_chart(pfr_chart_path)
        self.postflop_tree     = self._load_postflop_tree(postflop_tree_path)

    # ------------------------------------------------------------------
    # EV
    # ------------------------------------------------------------------
    def calculate_ev(
        self,
        equity_pct: float,
        potential_pot: float,
        cost_to_call: float,
    ) -> float:
        equity = max(0.0, min(equity_pct / 100.0, 1.0))
        return (equity * potential_pot) - ((1.0 - equity) * cost_to_call)

    def is_range_wide(self, active_range: Iterable[str]) -> bool:
        count = len(list(active_range))
        return count / 169.0 >= self.wide_range_cutoff

    # ------------------------------------------------------------------
    # Phase 1: Range width scaled by VPIP/PFR profile
    # ------------------------------------------------------------------
    def adjust_range_for_profile(
        self,
        active_range: List[str],
        range_width_mult: float,
    ) -> List[str]:
        """
        Widen or narrow the assumed opponent range based on their profile.
        range_width_mult > 1 → loosen (add more combos)
        range_width_mult < 1 → tighten (trim combos)
        We do this by slicing the full 169-combo ordered list proportionally.
        """
        ALL_COMBOS = [
            'AA','KK','QQ','JJ','TT','99','88','77','66','55','44','33','22',
            'AKs','AQs','AJs','ATs','A9s','A8s','A7s','A6s','A5s','A4s','A3s','A2s',
            'KQs','KJs','KTs','K9s','K8s','K7s','K6s','K5s','K4s','K3s','K2s',
            'QJs','QTs','Q9s','Q8s','Q7s','Q6s','Q5s','Q4s','Q3s','Q2s',
            'JTs','J9s','J8s','J7s','J6s','J5s','J4s','J3s','J2s',
            'T9s','T8s','T7s','T6s','T5s','T4s','T3s','T2s',
            '98s','97s','96s','95s','94s','93s','92s',
            '87s','86s','85s','84s','83s','82s',
            '76s','75s','74s','73s','72s',
            '65s','64s','63s','62s',
            '54s','53s','52s','43s','42s','32s',
            'AKo','AQo','AJo','ATo','A9o','A8o','A7o','A6o','A5o','A4o','A3o','A2o',
            'KQo','KJo','KTo','K9o','K8o','K7o','K6o','K5o','K4o','K3o','K2o',
            'QJo','QTo','Q9o','Q8o','Q7o','Q6o','Q5o','Q4o','Q3o','Q2o',
            'JTo','J9o','J8o','J7o','J6o','J5o','J4o','J3o','J2o',
            'T9o','T8o','T7o','T6o','T5o','T4o','T3o','T2o',
            '98o','97o','96o','95o','94o','93o','92o',
            '87o','86o','85o','84o','83o','82o',
            '76o','75o','74o','73o','72o',
            '65o','64o','63o','62o',
            '54o','53o','52o','43o','42o','32o',
        ]
        if not active_range:
            # Start from default top-30% range and scale
            base_n = int(169 * 0.30)
            active_range = ALL_COMBOS[:base_n]

        current_n = len(active_range)
        new_n = max(1, min(169, int(current_n * range_width_mult)))

        # Use ALL_COMBOS ordering to widen/narrow (top = strongest)
        ranked = [c for c in ALL_COMBOS if c in set(active_range)]
        if new_n > len(ranked):
            # Add next-best combos not already in range
            extra = [c for c in ALL_COMBOS if c not in set(ranked)]
            ranked = ranked + extra[:new_n - len(ranked)]
        else:
            ranked = ranked[:new_n]

        return ranked

    # ------------------------------------------------------------------
    # Phase 4: IP vs OOP postflop sizing
    # ------------------------------------------------------------------
    def _apply_positional_modifier(
        self, action: str, hero_is_ip: bool, texture: dict
    ) -> str:
        """
        Phase 4: Positional Aggression.
        IP  → widen value bets and semi-bluffs.
        OOP → tighten; prefer check-call over bet-lead on wet boards.
        """
        if action == 'Check':
            # OOP on a wet board: stay defensive (check-call line)
            # IP: can still check for deception but generally prefer bet
            return 'Check'

        if action == 'Call':
            # OOP check-call is fine; IP we sometimes want to raise instead
            # but we only upgrade if equity is strong enough — handled above.
            return 'Call'

        if action.startswith('Raise'):
            wet = texture.get('texture_label', 'DRY')
            if hero_is_ip:
                # IP on a wet board → pot-sized bet to charge draws
                if wet == 'WET':
                    return 'Raise_Pot'
                # IP on dry board → smaller sizing, keep them in
                if wet == 'DRY':
                    return 'Raise_Half'
                return action  # SEMI_WET keeps original sizing
            else:
                # OOP: be more conservative — downgrade pot bets to half-pot
                # and only raise when board is dry (we have protection)
                if wet == 'WET':
                    # OOP on wet board: check-call is safer than leading
                    return 'Call'
                if action == 'Raise_Pot':
                    return 'Raise_Half'
                return action

        return action

    # ------------------------------------------------------------------
    # Core postflop decision — frequency-based strategy tree
    # ------------------------------------------------------------------
    def choose_action(
        self,
        equity_pct: float,
        pot_size: float,
        amount_to_call: float,
        bankroll: float,
        active_range: List[str],
        current_street=None,
        board: Optional[List[str]] = None,
        hero_is_ip: bool = True,
        range_width_mult: float = 1.0,
        aggression_mult: float = 1.0,
        hero_equity_rank: float = 0.5,
        hero_position: str = 'BTN',
        vs_position: str = 'BB',
    ) -> str:
        if amount_to_call is None or pot_size is None:
            return 'Fold'
        if amount_to_call > bankroll:
            return 'Fold'

        texture = analyze_board_texture(board or [])
        texture_label = texture['texture_label']

        street_name = 'FLOP'
        if current_street is not None:
            street_name = current_street.name if hasattr(current_street, 'name') else str(current_street)

        range_adv = self._classify_range_advantage(equity_pct, hero_is_ip, range_width_mult)

        matchup_key = f"{hero_position}_vs_{vs_position}"
        tree_node = (
            self.postflop_tree.get(matchup_key)
            or self.postflop_tree.get('default', {})
        )
        street_node   = tree_node.get(street_name, tree_node.get('FLOP', {}))
        texture_node  = street_node.get(texture_label, street_node.get('DRY', {}))
        freq_map      = texture_node.get(range_adv, {})

        if not freq_map:
            freq_map = {'check': 0.5, 'fold': 0.5} if amount_to_call > 0 else {'check': 1.0}

        raw_action = self._sample_action(freq_map)
        return self._map_tree_action(raw_action, pot_size, amount_to_call, bankroll)

    @staticmethod
    def _classify_range_advantage(equity_pct: float, hero_is_ip: bool, range_width: float = 1.0) -> str:
        prefix = 'IP' if hero_is_ip else 'OOP'
        ahead_thresh  = 58 + (1.0 - range_width) * 10
        behind_thresh = 42 - (1.0 - range_width) * 10
        if equity_pct >= ahead_thresh:
            return f'{prefix}_AHEAD'
        if equity_pct <= behind_thresh:
            return f'{prefix}_BEHIND'
        return f'{prefix}_EVEN'

    @staticmethod
    def _sample_action(freq_map: dict) -> str:
        actions = list(freq_map.keys())
        weights = [freq_map[a] for a in actions]
        total   = sum(weights)
        if total <= 0:
            return actions[0] if actions else 'check'
        r = random.random() * total
        cumulative = 0.0
        for action, weight in zip(actions, weights):
            cumulative += weight
            if r <= cumulative:
                return action
        return actions[-1]

    @staticmethod
    def _map_tree_action(raw: str, pot_size: float, amount_to_call: float, bankroll: float) -> str:
        spr = bankroll / pot_size if pot_size > 0 else 99.0
        mapping = {
            'check':   'Check',
            'call':    'Call',
            'fold':    'Fold',
            'bet_33':  'Raise_Third',
            'bet_50':  'Raise_Half',
            'bet_75':  'Raise_Pot',
            'bet_pot': 'Raise_Pot',
        }
        action = mapping.get(raw, 'Check')
        if action in ('Raise_Third', 'Raise_Half', 'Raise_Pot') and spr <= 0.4:
            action = 'Raise_AllIn'
        if amount_to_call > 0 and action == 'Check':
            action = 'Call'
        return action

    # ------------------------------------------------------------------
    # Preflop (unchanged logic, kept intact)
    # ------------------------------------------------------------------
    @staticmethod
    def _cards_to_combo(hero_cards: List[str]) -> str:
        if not hero_cards or len(hero_cards) < 2:
            return ''
        a = hero_cards[0].strip()
        b = hero_cards[1].strip()
        ra = a[0].upper()
        rb = b[0].upper()
        if ra == rb:
            return ra + rb
        sa = a[1].lower() if len(a) > 1 else ''
        sb = b[1].lower() if len(b) > 1 else ''
        order = 'AKQJT98765432'
        high, low = (ra, rb) if order.index(ra) < order.index(rb) else (rb, ra)
        suited = sa and sb and sa == sb
        return f"{high}{low}{'s' if suited else 'o'}"

    def choose_preflop_action(
        self, hero_cards: List[str], context: PreflopContext
    ) -> str:
        combo    = self._cards_to_combo(hero_cards)
        pos      = (context.position or 'BTN').upper()
        act_type = (context.hero_action_type or 'unopened').lower()

        depth_key = self._stack_depth_key(context.effective_stack_bb)
        chart = self.pfr_chart.get(depth_key) or self.pfr_chart.get('cash_100bb', {})
        pos_ranges = chart.get(pos, {})

        if act_type == 'unopened':
            return 'Raise_3BB' if combo in pos_ranges.get('open', []) else 'Fold'

        if act_type == 'vs_open':
            vs_open = pos_ranges.get('vs_open', {})
            vs_pos  = (context.vs_position or 'CO').upper()
            call_range = (vs_open.get(f'call_{vs_pos}')
                          or vs_open.get('call_default')
                          or ['AA', 'KK', 'QQ', 'AKs'])
            bet_range  = (vs_open.get(f'3bet_{vs_pos}')
                          or vs_open.get('3bet_default')
                          or ['AA', 'KK', 'QQ', 'AKs'])
            if combo in bet_range:
                return 'Raise_Pot'
            if combo in call_range:
                return 'Call'
            return 'Fold'

        if act_type == 'vs_3bet':
            vs_3bet = pos_ranges.get('vs_3bet', ['AA', 'KK', 'QQ', 'AKs'])
            return 'Raise_Pot' if combo in vs_3bet else 'Fold'

        return 'Fold'

    @staticmethod
    def _stack_depth_key(effective_stack_bb: float) -> str:
        if effective_stack_bb <= 50:
            return 'cash_40bb'
        if effective_stack_bb <= 80:
            return 'cash_60bb'
        if effective_stack_bb <= 150:
            return 'cash_100bb'
        return 'cash_200bb'

    def _load_pfr_chart(self, path: str) -> dict:
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as fh:
                    return json.load(fh)
            except Exception:
                pass
        return {
            'cash_100bb': {
                'BTN': {
                    'open': ['AA','KK','QQ','JJ','TT','99','88','77','66',
                              'AKs','AQs','AJs','ATs','A9s','KQs','KJs','QJs',
                              'JTs','AKo','AQo','AJo','KQo'],
                    'vs_open': {'call_default': [], '3bet_default': []},
                    'vs_3bet': ['AA','KK','QQ','AKs','AKo'],
                },
            }
        }

    def _load_postflop_tree(self, path: str) -> dict:
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as fh:
                    return json.load(fh)
            except Exception:
                pass
        return {'default': {'FLOP': {'DRY': {'IP_AHEAD': {'bet_33': 0.5, 'check': 0.5}}}}}
