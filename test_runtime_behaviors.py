#!/usr/bin/env python3
"""Focused runtime regressions that avoid GUI/OCR dependencies."""

import os
import tempfile

from range_matrix import RangeMatrix
from tracker import TableTracker


def test_range_matrix_accepts_ocr_action_forms():
    matrix = RangeMatrix()
    player_id = 'villain'

    matrix.add_opponent(player_id)
    full_count = len(matrix.get_active_combos(player_id))

    matrix.update_range_from_action(player_id, 'raises', historical_pfr=20.0)
    raised_count = len(matrix.get_active_combos(player_id))
    assert 0 < raised_count < full_count, (
        f"expected plural 'raises' to narrow range below {full_count}, got {raised_count}"
    )

    matrix = RangeMatrix()
    matrix.update_range_from_action(player_id, 'calls')
    calling_range = set(matrix.get_active_combos(player_id))
    assert 'AA' not in calling_range
    assert 'KK' not in calling_range


def test_tracker_accepts_engine_game_started_text():
    with tempfile.TemporaryDirectory() as temp_dir:
        stats_path = os.path.join(temp_dir, 'player_stats.json')
        tracker = TableTracker(path=stats_path)

        tracker.parse_action_log(
            'Game ABC123 started\n'
            'villain calls preflop\n'
            'villain raises\n'
        )

        summary = tracker.summarize_player('villain')
        assert tracker.current_game_id == 'ABC123'
        assert summary['hands'] == 1
        assert summary['vpip_count'] == 1
        assert summary['calls'] == 1
        assert summary['raises'] == 1


if __name__ == '__main__':
    test_range_matrix_accepts_ocr_action_forms()
    test_tracker_accepts_engine_game_started_text()
    print('runtime behavior regressions passed')
