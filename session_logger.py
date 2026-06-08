import csv
import json
import os
import time
import uuid
from datetime import datetime
from typing import List, Optional


class SessionLogger:
    CSV_FIELDS = [
        'session_id', 'timestamp', 'game_id', 'hand_num', 'street',
        'hero_cards', 'board', 'hero_position',
        'pot_size', 'amount_to_call', 'stack',
        'equity_pct', 'pot_odds_pct', 'ev_pct', 'decision',
        'result_dollars', 'result_bb', 'showdown_seen', 'stack_start', 'stack_end',
    ]

    def __init__(self, session_dir: str = 'sessions', big_blind: float = 20.0):
        os.makedirs(session_dir, exist_ok=True)
        self.session_id = str(uuid.uuid4())[:8]
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.csv_path  = os.path.join(session_dir, f'session_{ts}.csv')
        self.json_path = os.path.join(session_dir, f'hands_{ts}.json')
        self.big_blind = big_blind
        self._hand_num = 0
        self._current_hand: Optional[dict] = None
        self._hands: List[dict] = []
        self._closed = False
        self._csv_file = open(self.csv_path, 'w', newline='', encoding='utf-8')
        self._writer = csv.DictWriter(self._csv_file, fieldnames=self.CSV_FIELDS)
        self._writer.writeheader()
        self._csv_file.flush()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def start_hand(self, game_id: Optional[str]) -> None:
        if self._current_hand:
            self._finalise_hand()
        self._hand_num += 1
        self._current_hand = {
            'session_id':  self.session_id,
            'hand_num':    self._hand_num,
            'game_id':     game_id,
            'started_at':  time.time(),
            'hero_cards':  None,
            'board':       [],
            'decisions':   [],
            'result_dollars': None,
            'result_bb':      None,
            'showdown_seen':  False,
            'stack_start':    None,
            'stack_end':      None,
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
        if self._current_hand is not None and self._current_hand.get('stack_start') is None:
            self._current_hand['stack_start'] = self._coerce_stack_value(stack)

        pot_odds_pct = 0.0
        if pot_size and amount_to_call:
            total = pot_size + amount_to_call
            pot_odds_pct = round(amount_to_call / total * 100.0, 2) if total > 0 else 0.0

        ev_pct = round(equity_pct - pot_odds_pct, 2) if amount_to_call > 0 else ''

        row = {
            'session_id':     self.session_id,
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
            'ev_pct':         ev_pct,
            'decision':       decision,
            'result_dollars': '',
            'result_bb':      '',
            'showdown_seen':  '',
            'stack_start':    '',
            'stack_end':      '',
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

    def record_outcome(self, game_id: str, result_dollars: float, showdown_seen: bool = False) -> None:
        if self._current_hand is None:
            return
        self._current_hand['game_id'] = game_id
        self._current_hand['result_dollars'] = result_dollars
        self._current_hand['result_bb'] = round(result_dollars / self.big_blind, 2)
        self._current_hand['showdown_seen'] = showdown_seen

    def _finalise_hand(self) -> None:
        if self._current_hand:
            stack_start = self._current_hand.get('stack_start')
            stack_end = self._extract_stack_end(self._current_hand)
            self._current_hand['stack_end'] = stack_end
            if self._current_hand.get('result_dollars') is None and stack_start is not None and stack_end is not None:
                result_dollars = round(stack_end - stack_start, 2)
                self._current_hand['result_dollars'] = result_dollars
                self._current_hand['result_bb'] = round(result_dollars / self.big_blind, 2)
            self._current_hand['ended_at'] = time.time()
            self._hands.append(self._current_hand)
            self._current_hand = None
            self._flush_json()

    def get_bb_per_100(self) -> float:
        completed = [hand for hand in self._hands if hand.get('result_bb') is not None]
        if not completed:
            return 0.0
        total_bb = sum(hand['result_bb'] for hand in completed)
        return (total_bb / len(completed)) * 100

    def _extract_stack_end(self, hand: dict) -> Optional[float]:
        decisions = hand.get('decisions') or []
        for decision in reversed(decisions):
            stack_value = self._coerce_stack_value(decision.get('stack'))
            if stack_value is not None:
                return stack_value
        return None

    def _coerce_stack_value(self, stack: Optional[str]) -> Optional[float]:
        if stack in (None, ''):
            return None
        if isinstance(stack, (int, float)):
            return float(stack)
        if isinstance(stack, str):
            cleaned = stack.replace('$', '').replace(',', '').strip()
            try:
                return float(cleaned)
            except ValueError:
                return None
        return None

    def _flush_json(self) -> None:
        try:
            with open(self.json_path, 'w', encoding='utf-8') as fh:
                json.dump(self._hands, fh, indent=2)
        except Exception:
            pass

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._finalise_hand()
        try:
            self._csv_file.close()
        except Exception:
            pass
        self._flush_json()

