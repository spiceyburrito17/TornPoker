import json
import os
import re
from typing import Dict, List, Optional

PLAYER_STATS_FILE = 'player_stats.json'

class PlayerTracker:
    def __init__(self, path: str = PLAYER_STATS_FILE):
        self.path = path
        self.players: Dict[str, Dict[str, float]] = {}
        self.current_game_id: Optional[str] = None
        self._load()

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

    def parse_action_log(self, log: str) -> None:
        if not log:
            return
        cleaned = self._clean_log_bleed(log)
        for line in cleaned.splitlines():
            parsed = self._parse_line(line)
            if parsed:
                player, action = parsed
                self._update_player(player, action)

    def _clean_log_bleed(self, log: str) -> str:
        game_start = re.search(r'Game\s*ID\s*Started[:\s]*([0-9A-Za-z_-]+)', log, re.IGNORECASE)
        if game_start:
            new_id = game_start.group(1).strip()
            if new_id != self.current_game_id:
                self.current_game_id = new_id
                return log.split(game_start.group(0))[-1]
        return log

    def _parse_line(self, line: str) -> Optional[tuple]:
        line = line.strip()
        if not line:
            return None
        match = re.match(r'^(?P<player>[A-Za-z0-9_]+)\s+(?P<action>calls|raises|bets|folds|checks|limps)(?:\b|\s|\.)', line, re.IGNORECASE)
        if not match:
            return None
        return match.group('player'), match.group('action').lower()

    def _update_player(self, player: str, action: str) -> None:
        record = self.players.setdefault(player, {
            'hands': 0,
            'vpip': 0,
            'pfr': 0,
            'bets': 0,
            'raises': 0,
            'calls': 0,
            'folds': 0,
            'aggression_factor': 0.0,
            'profile': 'UNKNOWN'
        })
        record['hands'] = max(record.get('hands', 0), 1)
        if action in {'calls', 'raises', 'bets', 'limps'}:
            record['vpip'] = record.get('vpip', 0) + 1
        if action == 'raises':
            record['pfr'] = record.get('pfr', 0) + 1
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

    def _update_aggression(self, record: Dict[str, float]) -> None:
        calls = record.get('calls', 0)
        raises = record.get('raises', 0)
        bets = record.get('bets', 0)
        denominator = max(1.0, calls)
        record['aggression_factor'] = round((raises + bets) / denominator, 2)

    def _cluster_profile(self, record: Dict[str, float]) -> str:
        vpip = record.get('vpip', 0)
        pfr = record.get('pfr', 0)
        af = record.get('aggression_factor', 0.0)
        if vpip <= 10 and pfr <= 5:
            return 'NIT'
        if vpip >= 35 and af >= 3:
            return 'MANIAC'
        if vpip >= 25 and af >= 1.5:
            return 'LOOSE_AGGRESSIVE'
        if vpip >= 25:
            return 'LOOSE_PASSIVE'
        if af < 1:
            return 'PASSIVE'
        return 'TAG'

    def summarize_player(self, player: str) -> Dict[str, float]:
        record = self.players.get(player, {
            'hands': 0,
            'vpip': 0,
            'pfr': 0,
            'bets': 0,
            'raises': 0,
            'calls': 0,
            'folds': 0,
            'aggression_factor': 0.0,
            'profile': 'UNKNOWN'
        })
        record['vpip_rate'] = self._percentage(record.get('vpip', 0), record.get('hands', 1))
        record['pfr_rate'] = self._percentage(record.get('pfr', 0), record.get('hands', 1))
        return record

    def get_player_profile(self, player: str) -> str:
        return self.summarize_player(player).get('profile', 'UNKNOWN')

    def get_pfr_rate(self, player: str) -> float:
        return self.summarize_player(player).get('pfr_rate', 0.0)

    def get_vpip_rate(self, player: str) -> float:
        return self.summarize_player(player).get('vpip_rate', 0.0)

    def _percentage(self, numerator: int, denominator: int) -> float:
        if denominator <= 0:
            return 0.0
        return round(float(numerator) / float(denominator) * 100.0, 2)


class TableTracker:
    def __init__(self):
        self.seat_anchors = {
            0: (679, 504),
            1: (372, 482),
            2: (182, 461),
            3: (182, 282),
            4: (321, 106),
            5: (879, 103),
            6: (1016, 288),
            7: (1018, 465),
            8: (825, 487)
        }

    def calculate_hero_position(self, active_seats: List[int], dealer_seat: int) -> str:
        if not active_seats or dealer_seat is None:
            return 'UTG'
        try:
            dealer_idx = active_seats.index(dealer_seat)
            hero_idx = active_seats.index(0)
        except ValueError:
            return 'UTG'

        dist = (hero_idx - dealer_idx) % len(active_seats)
        if len(active_seats) == 2:
            return 'BB' if dist == 1 else 'UTG'
        if dist == 0:
            return 'BTN'
        if dist == 1:
            return 'SB'
        if dist == 2:
            return 'BB'
        if dist == len(active_seats) - 2:
            return 'HJ'
        if dist == len(active_seats) - 1:
            return 'CO'
        if dist == 3:
            return 'UTG'
        return 'UTG'
