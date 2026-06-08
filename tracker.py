import json
import os
import re
from typing import Dict, List, Optional


PLAYER_STATS_FILE = 'player_stats.json'

# ---------------------------------------------------------------------------
# PHASE 1: VPIP/PFR Exploit — fully wired opponent profiling
# ---------------------------------------------------------------------------

# How many hands we need before trusting the stats. Below this we use
# conservative defaults so the bot doesn't over-exploit on a 2-hand sample.
MIN_RELIABLE_HANDS = 15

# Profile -> (range_width_multiplier, aggression_multiplier)
# range_width_multiplier > 1 widens the assumed opponent range (loose players)
# aggression_multiplier  > 1 means we defend wider vs their bets (bluff more)
PROFILE_RANGE_MODIFIERS = {
    'NIT':              (0.55, 0.7),
    'PASSIVE':          (0.75, 0.8),
    'TAG':              (1.00, 1.0),
    'LOOSE_PASSIVE':    (1.35, 0.9),
    'LOOSE_AGGRESSIVE': (1.45, 1.3),
    'MANIAC':           (1.65, 1.5),
    'UNKNOWN':          (1.00, 1.0),
}


class PlayerTracker:
    def __init__(self, path: str = PLAYER_STATS_FILE):
        self.path = path
        self.players: Dict[str, Dict] = {}
        self.current_game_id: Optional[str] = None
        self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def _load(self) -> None:
        if not os.path.exists(self.path):
            self.players = {}
            return
        try:
            with open(self.path, 'r', encoding='utf-8') as fh:
                payload = json.load(fh)
            self.players = payload.get('players', {})
        except Exception:
            self.players = {}

    def save(self) -> None:
        try:
            payload = {'players': self.players}
            with open(self.path, 'w', encoding='utf-8') as fh:
                json.dump(payload, fh, indent=2)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Log parsing
    # ------------------------------------------------------------------
    def parse_action_log(self, log: str) -> None:
        if not log:
            return
        cleaned = self._clean_log_bleed(log)
        for line in cleaned.splitlines():
            parsed = self._parse_line(line)
            if parsed:
                player, action, is_preflop = parsed
                self._update_player(player, action, is_preflop)

    def _clean_log_bleed(self, log: str) -> str:
        game_start = re.search(
            r'Game\s*ID\s*Started[:\s]*([0-9A-Za-z_-]+)', log, re.IGNORECASE
        )
        if game_start:
            new_id = game_start.group(1).strip()
            if new_id != self.current_game_id:
                self.current_game_id = new_id
                return log.split(game_start.group(0))[-1]
        return log

    BLOCKED_NAMES = {
        'your', 'hero', 'turn', 'act', 'you', 'player', 'game', 'started'
    }

    def _parse_line(self, line: str) -> Optional[tuple]:
        line = line.strip()
        if not line:
            return None
        street_match = re.search(
            r'\b(preflop|flop|turn|river)\b', line, re.IGNORECASE
        )
        is_preflop = (
            street_match.group(1).lower() == 'preflop'
            if street_match else False
        )
        match = re.match(
            r'^(?P<player>[A-Za-z0-9_]+)\s+'
            r'(?P<action>calls|raises|bets|folds|checks|limps)(?:\b|\s|\.)',
            line, re.IGNORECASE,
        )
        if not match:
            return None
        player = match.group('player').lower()
        if player in self.BLOCKED_NAMES or len(player) < 3:
            return None
        return match.group('player'), match.group('action').lower(), is_preflop

    # ------------------------------------------------------------------
    # Stats update
    # ------------------------------------------------------------------
    def _update_player(self, player: str, action: str, is_preflop: bool) -> None:
        record = self.players.setdefault(player, {
            'hands':             0,
            'vpip_count':        0,
            'pfr_count':         0,
            'bets':              0,
            'raises':            0,
            'calls':             0,
            'folds':             0,
            'aggression_factor': 0.0,
            'profile':           'UNKNOWN',
            'seen_games':        [],
        })
        # Only count hands once per unique game_id
        if self.current_game_id and self.current_game_id not in record.get('seen_games', []):
            record.setdefault('seen_games', []).append(self.current_game_id)
            record['hands'] = record.get('hands', 0) + 1
            # Bound seen_games to prevent unbounded growth
            if len(record['seen_games']) > 200:
                record['seen_games'] = record['seen_games'][-100:]

        # VPIP: any voluntary money in preflop
        if is_preflop and action in {'calls', 'raises', 'bets', 'limps'}:
            record['vpip_count'] = record.get('vpip_count', 0) + 1

        # PFR: preflop raise only
        if is_preflop and action == 'raises':
            record['pfr_count'] = record.get('pfr_count', 0) + 1

        # Raw action counters (all streets)
        if action == 'raises':
            record['raises'] = record.get('raises', 0) + 1
        elif action == 'bets':
            record['bets'] = record.get('bets', 0) + 1
        elif action == 'calls':
            record['calls'] = record.get('calls', 0) + 1
        elif action == 'folds':
            record['folds'] = record.get('folds', 0) + 1

        self._update_aggression(record)
        record['profile'] = self._cluster_profile(record)
        self.save()

    def _update_aggression(self, record: Dict) -> None:
        calls = record.get('calls', 0)
        raises = record.get('raises', 0)
        bets = record.get('bets', 0)
        record['aggression_factor'] = round(
            (raises + bets) / max(1.0, calls), 2
        )

    def _cluster_profile(self, record: Dict) -> str:
        hands = record.get('hands', 0)
        if hands < MIN_RELIABLE_HANDS:
            return 'UNKNOWN'
        vpip = self.get_vpip_rate_from_record(record)
        pfr  = self.get_pfr_rate_from_record(record)
        af   = record.get('aggression_factor', 0.0)

        if vpip <= 12 and pfr <= 8:
            return 'NIT'
        if vpip >= 35 and af >= 3.0:
            return 'MANIAC'
        if vpip >= 25 and pfr >= 18 and af >= 1.5:
            return 'LOOSE_AGGRESSIVE'
        if vpip >= 25:
            return 'LOOSE_PASSIVE'
        if af < 1.0:
            return 'PASSIVE'
        return 'TAG'

    # ------------------------------------------------------------------
    # Public stat accessors
    # ------------------------------------------------------------------
    def summarize_player(self, player: str) -> Dict:
        record = self.players.get(player, {
            'hands': 0, 'vpip_count': 0, 'pfr_count': 0,
            'bets': 0, 'raises': 0, 'calls': 0, 'folds': 0,
            'aggression_factor': 0.0, 'profile': 'UNKNOWN',
        })
        record = dict(record)
        record['vpip_rate'] = self.get_vpip_rate_from_record(record)
        record['pfr_rate']  = self.get_pfr_rate_from_record(record)
        return record

    def get_player_profile(self, player: str) -> str:
        return self.summarize_player(player).get('profile', 'UNKNOWN')

    def get_pfr_rate(self, player: str) -> float:
        return self.summarize_player(player).get('pfr_rate', 0.0)

    def get_vpip_rate(self, player: str) -> float:
        return self.summarize_player(player).get('vpip_rate', 0.0)

    def get_range_modifiers(self, player: str) -> tuple:
        """Return (range_width_mult, aggression_mult) for this player's profile."""
        profile = self.get_player_profile(player)
        return PROFILE_RANGE_MODIFIERS.get(profile, (1.0, 1.0))

    def get_vpip_rate_from_record(self, record: Dict) -> float:
        return self._percentage(
            record.get('vpip_count', 0), record.get('hands', 1)
        )

    def get_pfr_rate_from_record(self, record: Dict) -> float:
        return self._percentage(
            record.get('pfr_count', 0), record.get('hands', 1)
        )

    @staticmethod
    def _percentage(numerator: int, denominator: int) -> float:
        if denominator <= 0:
            return 0.0
        return round(float(numerator) / float(denominator) * 100.0, 2)


# ---------------------------------------------------------------------------
# Table-level seat / position tracking (unchanged structure, extended docs)
# ---------------------------------------------------------------------------

class TableTracker(PlayerTracker):
    """Combines PlayerTracker stats with seat-layout awareness."""

    def __init__(self, path: str = PLAYER_STATS_FILE):
        super().__init__(path)
        # Pixel anchors for each seat in the capture region.
        # Seat 0 = hero. Adjust if your table layout differs.
        self.seat_anchors = {
            0: (679, 504),
            1: (372, 482),
            2: (182, 461),
            3: (182, 282),
            4: (321, 106),
            5: (879, 103),
            6: (1016, 288),
            7: (1018, 465),
            8: (825, 487),
        }

    # ------------------------------------------------------------------
    # Position calculation
    # ------------------------------------------------------------------
    def calculate_hero_position(
        self, active_seats: List[int], dealer_seat: int
    ) -> str:
        if not active_seats or dealer_seat is None:
            return 'UTG'
        try:
            dealer_idx = active_seats.index(dealer_seat)
            hero_idx   = active_seats.index(0)
        except ValueError:
            return 'UTG'

        dist = (hero_idx - dealer_idx) % len(active_seats)
        n    = len(active_seats)

        if n == 2:
            return 'BB' if dist == 1 else 'BTN'
        if dist == 0:
            return 'BTN'
        if dist == 1:
            return 'SB'
        if dist == 2:
            return 'BB'
        if dist == n - 1:
            return 'CO'
        if dist == n - 2:
            return 'HJ'
        return 'UTG'

    def get_primary_opponent(self) -> Optional[str]:
        """Return the opponent most relevant to the current game."""
        if not self.players:
            return None
        # Prefer opponent seen in the current game
        if self.current_game_id:
            current_game_players = [
                p for p, rec in self.players.items()
                if self.current_game_id in rec.get('seen_games', [])
            ]
            if current_game_players:
                return max(current_game_players, key=lambda p: self.players[p].get('hands', 0))
        # Fallback to global most frequent
        return max(self.players, key=lambda p: self.players[p].get('hands', 0))

    def is_hero_in_position(
        self, active_seats: List[int], dealer_seat: int
    ) -> bool:
        """
        Phase 4 helper.
        Returns True if hero acts LAST postflop (IP = BTN or CO when BTN folded).
        Postflop, the last-to-act seat is the BTN or the closest active seat
        clockwise before it.
        """
        if not active_seats or dealer_seat is None:
            return False
        try:
            dealer_idx = active_seats.index(dealer_seat)
            hero_idx   = active_seats.index(0)
        except ValueError:
            return False

        # The BTN acts last postflop. Hero is IP if no active player sits
        # between hero and the BTN (dealer) going clockwise.
        n = len(active_seats)
        dist_hero_to_btn = (dealer_idx - hero_idx) % n
        # dist == 0 means hero IS the BTN (last to act) — IP
        # dist == 1 means one player acts after hero — OOP
        return dist_hero_to_btn == 0
