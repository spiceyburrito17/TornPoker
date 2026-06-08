import csv
import json
import os
import time
from datetime import datetime
from typing import List, Optional


class SessionLogger:
    CSV_FIELDS = [
        'timestamp', 'game_id', 'hand_num', 'street',
        'hero_cards', 'board', 'hero_position',
        'pot_size', 'amount_to_call', 'stack',
        'equity_pct', 'pot_odds_pct', 'decision',
    ]

    def __init__(self, session_dir: str = 'sessions'):
        os.makedirs(session_dir, exist_ok=True)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.csv_path  = os.path.join(session_dir, f'session_{ts}.csv')
        self.json_path = os.path.join(session_dir, f'hands_{ts}.json')
        self._hand_num = 0
        self._current_hand: Optional[dict] = None
        self._hands: List[dict] = []
        self._csv_file = open(self.csv_path, 'w', newline='', encoding='utf-8')
        self._writer = csv.DictWriter(self._csv_file, fieldnames=self.CSV_FIELDS)
        self._writer.writeheader()
        self._csv_file.flush()

    def start_hand(self, game_id: Optional[str]) -> None:
        if self._current_hand:
            self._finalise_hand()
        self._hand_num += 1
        self._current_hand = {
            'hand_num':    self._hand_num,
            'game_id':     game_id,
            'started_at':  time.time(),
            'hero_cards':  None,
            'board':       [],
            'decisions':   [],
        }

    def log_decision(
        self,
        game_id:        Optional[str],
        street:         str,
        hero_cards:     List[str],
        board:          List[str],
        hero_position:  str,
        pot_size:       Optional[float],
        amount_to_call: float,
        stack:          Optional[str],
        equity_pct:     float,
        decision:       str,
    ) -> None:
        if self._current_hand is None:
            self.start_hand(game_id)

        pot_odds_pct = 0.0
        if pot_size and amount_to_call:
            total = pot_size + amount_to_call
            pot_odds_pct = round(amount_to_call / total * 100.0, 2) if total > 0 else 0.0

        row = {
            'timestamp':      datetime.now().isoformat(timespec='seconds'),
            'game_id':        game_id or '',
            'hand_num':       self._hand_num,
            'street':         street,
            'hero_cards':     ' '.join(hero_cards) if hero_cards else '',
            'board':          ' '.join(board) if board else '',
            'hero_position':  hero_position,
            'pot_size':       round(pot_size, 2) if pot_size is not None else '',
            'amount_to_call': round(amount_to_call, 2),
            'stack':          stack or '',
            'equity_pct':     round(equity_pct, 2),
            'pot_odds_pct':   pot_odds_pct,
            'decision':       decision,
        }
        self._writer.writerow(row)
        self._csv_file.flush()

        decision_record = dict(row)
        decision_record['hero_cards'] = list(hero_cards) if hero_cards else []
        decision_record['board']      = list(board) if board else []
        if self._current_hand is not None:
            self._current_hand['hero_cards'] = decision_record['hero_cards']
            if decision_record['board']:
                self._current_hand['board'] = decision_record['board']
            self._current_hand['decisions'].append(decision_record)

    def _finalise_hand(self) -> None:
        if self._current_hand:
            self._current_hand['ended_at'] = time.time()
            self._hands.append(self._current_hand)
            self._current_hand = None
            self._flush_json()

    def _flush_json(self) -> None:
        try:
            with open(self.json_path, 'w', encoding='utf-8') as fh:
                json.dump(self._hands, fh, indent=2)
        except Exception:
            pass

    def close(self) -> None:
        self._finalise_hand()
        try:
            self._csv_file.close()
        except Exception:
            pass
        self._flush_json()
