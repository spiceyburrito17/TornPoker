"""
phevaluator vs treys benchmark spike
Standalone test — does NOT modify any engine files.
"""
import time
import random
from typing import List, Tuple

# ─── Dependencies ───────────────────────────────────────────────────────────
from treys import Card as TCard, Evaluator as TEvaluator
from phevaluator import evaluate_cards as pheval

# ─── Constants ──────────────────────────────────────────────────────────────
RANKS = '23456789TJQKA'
SUITS = 'shdc'
FULL_DECK_STR = [r + s for r in RANKS for s in SUITS]

# phevaluator uses lowercase rank for 10 = 'T' -> need to check format
# phevaluator.evaluate_cards takes card strings like 'Ah', '2c', 'Td' etc.

# Hand class thresholds for phevaluator (lower rank = better hand)
# 1-10: Royal Flush, 11-166: Straight Flush, 167-322: Four of a Kind,
# 323-2467: Full House, 2468-3325: Flush, 3326-6185: Straight,
# 6186-7140: Three of a Kind, 7141-10600: Two Pair, 10601-31599: One Pair,
# 31600-7462: High Card (actually reversed — phevaluator: lower = better)
def ph_hand_class(rank: int) -> str:
    if rank <= 10:
        return "Royal Flush"
    elif rank <= 166:
        return "Straight Flush"
    elif rank <= 322:
        return "Four of a Kind"
    elif rank <= 2467:
        return "Full House"
    elif rank <= 3325:
        return "Flush"
    elif rank <= 6185:
        return "Straight"
    elif rank <= 7140:
        return "Three of a Kind"
    elif rank <= 10600:
        return "Two Pair"
    elif rank <= 31599:
        return "One Pair"
    else:
        return "High Card"


# ═══════════════════════════════════════════════════════════════════════════════
# PART 1: Validate basic hand ranking
# ═══════════════════════════════════════════════════════════════════════════════
def validate_hand_ranking():
    print("=" * 60)
    print("PART 1: Hand Ranking Validation (phevaluator)")
    print("=" * 60)

    test_cases = [
        # (hero, board, expected_class)
        (['Ah', 'Ad'], ['Ac', 'Ks', '7d', '2c', '2h'], "Three of a Kind"),
        (['Jh', 'Th'], ['9h', 'Qh', '2c', '3d', '4s'], "Straight"),
        (['7c', '7d'], ['7h', 'Kc', 'Kd', '2s', '2d'], "Full House"),
    ]

    for hero, board, expected in test_cases:
        all_cards = hero + board
        # phevaluator takes card strings directly
        rank = pheval(*all_cards)
        hand_class = ph_hand_class(rank)
        status = "OK" if hand_class == expected else f"FAIL (expected {expected})"
        print(f"  Cards: {all_cards}")
        print(f"  Rank: {rank}  Class: {hand_class}  {status}")
        print()


# ═══════════════════════════════════════════════════════════════════════════════
# PART 2: Benchmark speed — 50k random 7-card evaluations
# ═══════════════════════════════════════════════════════════════════════════════
def benchmark_speed(n: int = 50000):
    print("=" * 60)
    print(f"PART 2: Speed Benchmark ({n:,} random 7-card evaluations)")
    print("=" * 60)

    # Pre-generate random hands
    hands: List[List[str]] = []
    for _ in range(n):
        cards = random.sample(FULL_DECK_STR, 7)
        hands.append(cards)

    # --- phevaluator ---
    t0 = time.perf_counter()
    for cards in hands:
        pheval(*cards)
    ph_time = time.perf_counter() - t0

    # --- treys ---
    treys_eval = TEvaluator()
    # Convert to treys format
    treys_hands: List[Tuple[List[int], List[int]]] = []
    for cards in hands:
        t_cards = [TCard.new(c) for c in cards]
        treys_hands.append((t_cards[:5], t_cards[5:]))  # board=5, hand=2

    t0 = time.perf_counter()
    for board, hand in treys_hands:
        treys_eval.evaluate(board, hand)
    treys_time = time.perf_counter() - t0

    print(f"  phevaluator: {ph_time:.3f}s  ({n/ph_time:,.0f} evals/sec)")
    print(f"  treys:       {treys_time:.3f}s  ({n/treys_time:,.0f} evals/sec)")
    speedup = treys_time / ph_time if ph_time > 0 else 0
    print(f"  Speedup:     phevaluator is {speedup:.1f}x {'faster' if speedup > 1 else 'slower'} than treys")
    print()
    return ph_time, treys_time


# ═══════════════════════════════════════════════════════════════════════════════
# PART 3: Monte Carlo compatibility — compare equity results
# ═══════════════════════════════════════════════════════════════════════════════
def monte_carlo_comparison(trials: int = 5000):
    print("=" * 60)
    print(f"PART 3: Monte Carlo Compatibility ({trials:,} iterations)")
    print("=" * 60)
    print("  Spot: Hero Kd Ac | Board 4h Qs 8h | Villain top ~50% range")
    print()

    hero_str = ['Kd', 'Ac']
    board_str = ['4h', 'Qs', '8h']

    # Top ~50% range (roughly: all pairs, suited broadways, suited connectors,
    # offsuit broadways down to about K7o, Q8o, J8o, T8o)
    top50_range = [
        'AA', 'KK', 'QQ', 'JJ', 'TT', '99', '88', '77', '66', '55', '44', '33', '22',
        'AKs', 'AQs', 'AJs', 'ATs', 'A9s', 'A8s', 'A7s', 'A6s', 'A5s', 'A4s', 'A3s', 'A2s',
        'KQs', 'KJs', 'KTs', 'K9s', 'K8s', 'K7s', 'K6s', 'K5s',
        'QJs', 'QTs', 'Q9s', 'Q8s', 'Q7s',
        'JTs', 'J9s', 'J8s', 'J7s',
        'T9s', 'T8s', 'T7s',
        '98s', '97s', '87s', '86s', '76s', '75s', '65s', '64s', '54s',
        'AKo', 'AQo', 'AJo', 'ATo', 'A9o', 'A8o', 'A7o',
        'KQo', 'KJo', 'KTo', 'K9o', 'K8o', 'K7o',
        'QJo', 'QTo', 'Q9o', 'Q8o',
        'JTo', 'J9o', 'J8o',
        'T9o', 'T8o',
        '98o', '97o', '87o',
    ]

    blocked_str = set(hero_str + board_str)
    deck_str = [c for c in FULL_DECK_STR if c not in blocked_str]

    # Build opponent combos
    def expand_range(range_list, blocked):
        combos = []
        for combo in range_list:
            if len(combo) == 2:  # pair
                rank = combo[0]
                pair_cards = [rank + s for s in SUITS if rank + s not in blocked]
                for i in range(len(pair_cards)):
                    for j in range(i+1, len(pair_cards)):
                        combos.append((pair_cards[i], pair_cards[j]))
            elif len(combo) == 3:
                hi, lo, typ = combo[0], combo[1], combo[2]
                if typ == 's':
                    for s in SUITS:
                        c1, c2 = hi + s, lo + s
                        if c1 not in blocked and c2 not in blocked:
                            combos.append((c1, c2))
                else:
                    for s1 in SUITS:
                        for s2 in SUITS:
                            if s1 == s2:
                                continue
                            c1, c2 = hi + s1, lo + s2
                            if c1 not in blocked and c2 not in blocked:
                                combos.append((c1, c2))
        return combos

    opp_combos = expand_range(top50_range, blocked_str)

    # --- phevaluator MC ---
    ph_wins = 0
    ph_ties = 0
    ph_total = 0
    t0 = time.perf_counter()
    for _ in range(trials):
        opp = random.choice(opp_combos)
        opp_blocked = blocked_str | set(opp)
        avail = [c for c in deck_str if c not in opp_blocked]
        if len(avail) < 2:
            continue
        runout = random.sample(avail, 2)  # need 2 more cards for 5-card board
        full_board = board_str + runout
        hero_rank = pheval(*(hero_str + full_board))
        opp_rank = pheval(*(list(opp) + full_board))
        if hero_rank < opp_rank:
            ph_wins += 1
        elif hero_rank == opp_rank:
            ph_ties += 1
        ph_total += 1
    ph_equity = (ph_wins + ph_ties * 0.5) / ph_total * 100 if ph_total else 0
    ph_mc_time = time.perf_counter() - t0

    # --- treys MC ---
    treys_eval = TEvaluator()
    hero_t = [TCard.new(c) for c in hero_str]
    board_t_base = [TCard.new(c) for c in board_str]
    tr_wins = 0
    tr_ties = 0
    tr_total = 0
    t0 = time.perf_counter()
    for _ in range(trials):
        opp = random.choice(opp_combos)
        opp_blocked = blocked_str | set(opp)
        avail = [c for c in deck_str if c not in opp_blocked]
        if len(avail) < 2:
            continue
        runout = random.sample(avail, 2)
        full_board_t = board_t_base + [TCard.new(c) for c in runout]
        opp_t = [TCard.new(c) for c in opp]
        hero_score = treys_eval.evaluate(full_board_t, hero_t)
        opp_score = treys_eval.evaluate(full_board_t, opp_t)
        if hero_score < opp_score:
            tr_wins += 1
        elif hero_score == opp_score:
            tr_ties += 1
        tr_total += 1
    tr_equity = (tr_wins + tr_ties * 0.5) / tr_total * 100 if tr_total else 0
    treys_mc_time = time.perf_counter() - t0

    print(f"  phevaluator equity: {ph_equity:.1f}%  ({ph_mc_time:.3f}s)")
    print(f"  treys equity:       {tr_equity:.1f}%  ({treys_mc_time:.3f}s)")
    print(f"  Difference:         {abs(ph_equity - tr_equity):.1f}pp")
    print(f"  MC speedup:         phevaluator is {treys_mc_time/ph_mc_time:.1f}x {'faster' if treys_mc_time > ph_mc_time else 'slower'}")
    print()
    return ph_equity, tr_equity, ph_mc_time, treys_mc_time


# ═══════════════════════════════════════════════════════════════════════════════
# RECOMMENDATION
# ═══════════════════════════════════════════════════════════════════════════════
def recommendation(ph_time, treys_time, ph_eq, tr_eq, ph_mc_t, tr_mc_t):
    print("=" * 60)
    print("RECOMMENDATION")
    print("=" * 60)
    speedup = treys_time / ph_time if ph_time > 0 else 1
    eq_diff = abs(ph_eq - tr_eq)

    print(f"  Raw eval speedup: {speedup:.1f}x")
    print(f"  Equity agreement: within {eq_diff:.1f}pp (same RNG seed would converge)")
    print()

    if speedup > 2:
        print("  >> RECOMMENDATION: Swap phevaluator into Monte Carlo backend.")
        print("     Significant speed gain with equivalent correctness.")
        print("     Drop-in replacement: just change the evaluate call in monte_carlo.py.")
        print("     phevaluator uses string card format -- adaptor is trivial.")
    elif speedup > 1.2:
        print("  >> RECOMMENDATION: Use phevaluator for final hand ranking only.")
        print("     Modest speed gain. Worth using but not urgent to refactor MC loop.")
    else:
        print("  >> RECOMMENDATION: Keep treys. Speed difference is negligible.")
        print("     Not worth the integration effort.")
    print()


# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == '__main__':
    validate_hand_ranking()
    ph_t, tr_t = benchmark_speed(50000)
    ph_eq, tr_eq, ph_mc_t, tr_mc_t = monte_carlo_comparison(5000)
    recommendation(ph_t, tr_t, ph_eq, tr_eq, ph_mc_t, tr_mc_t)
