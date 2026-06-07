#!/usr/bin/env python3
"""Test preflop context and decision integration."""

import json
from decision_maker import DecisionMaker, PreflopContext

def test_json_load():
    """Test that pfr_chart.json loads correctly."""
    with open('pfr_chart.json', 'r') as f:
        data = json.load(f)
    print(f"✓ pfr_chart.json loaded successfully")
    positions = list(data['cash_100bb'].keys())
    print(f"  Positions: {positions}")
    for pos in positions:
        open_range = data['cash_100bb'][pos]['open']
        vs_open = data['cash_100bb'][pos]['vs_open']
        print(f"  {pos}: open={len(open_range)} combos, vs_open keys={list(vs_open.keys())}")

def test_unopened():
    """Test unopened (raise first in) decisions."""
    dm = DecisionMaker()
    ctx_btn = PreflopContext(position='BTN', hero_action_type='unopened')
    ctx_utg = PreflopContext(position='UTG', hero_action_type='unopened')
    
    # Test premium hand from BTN
    result = dm.choose_preflop_action(['As', 'Ks'], ctx_btn)
    print(f"✓ BTN with AKs: {result} (expected 'Raise_3BB')")
    assert result == 'Raise_3BB', f"Expected Raise_3BB, got {result}"
    
    # Test weak hand from BTN
    result = dm.choose_preflop_action(['2d', '3c'], ctx_btn)
    print(f"✓ BTN with 23o: {result} (expected 'Fold')")
    assert result == 'Fold', f"Expected Fold, got {result}"
    
    # Test weak hand from UTG
    result = dm.choose_preflop_action(['2d', '3c'], ctx_utg)
    print(f"✓ UTG with 23o: {result} (expected 'Fold')")
    assert result == 'Fold', f"Expected Fold, got {result}"
    
    # Test medium hand from UTG
    result = dm.choose_preflop_action(['Jh', 'Jd'], ctx_utg)
    print(f"✓ UTG with JJ: {result} (expected 'Raise_3BB')")
    assert result == 'Raise_3BB', f"Expected Raise_3BB, got {result}"

def test_vs_open():
    """Test vs open decisions."""
    dm = DecisionMaker()
    ctx = PreflopContext(
        position='HJ',
        hero_action_type='vs_open',
        vs_position='UTG'
    )
    
    # Test 3-bet combo
    result = dm.choose_preflop_action(['Ks', 'Qs'], ctx)
    print(f"✓ HJ vs UTG open with KQs: {result} (expected 'Call')")
    assert result == 'Call', f"Expected Call, got {result}"
    
    # Test fold combo
    result = dm.choose_preflop_action(['7d', '7c'], ctx)
    print(f"✓ HJ vs UTG open with 77: {result} (expected 'Fold')")
    assert result == 'Fold', f"Expected Fold, got {result}"

def test_vs_3bet():
    """Test vs 3-bet decisions."""
    dm = DecisionMaker()
    ctx = PreflopContext(
        position='BTN',
        hero_action_type='vs_3bet',
        vs_position='SB'
    )
    
    result = dm.choose_preflop_action(['Ah', 'Kd'], ctx)
    print(f"✓ BTN vs SB 3bet with AK: {result} (expected 'Raise_Pot')")
    assert result == 'Raise_Pot', f"Expected Raise_Pot, got {result}"
    
    result = dm.choose_preflop_action(['Jd', 'Tc'], ctx)
    print(f"✓ BTN vs SB 3bet with JTo: {result} (expected 'Fold')")
    assert result == 'Fold', f"Expected Fold, got {result}"

if __name__ == '__main__':
    print("Testing preflop refactoring...\n")
    test_json_load()
    print()
    test_unopened()
    print()
    test_vs_open()
    print()
    test_vs_3bet()
    print("\n✓ All tests passed!")
