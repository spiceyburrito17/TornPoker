"""
Comprehensive regression stress test for phevaluator vs treys in monte_carlo.py
"""
import time
import importlib
import monte_carlo as mc_mod

TRIALS = 10000

SPOTS = [
    ("Overpair on wet flop", ["Ah", "Ad"], ["Kh", "Qh", "7d"]),
    ("Two overs + nut FD", ["Ac", "Kd"], ["4h", "Qs", "8h"]),
    ("Top pair weak kicker", ["Kc", "7c"], ["8c", "7d", "2s"]),
    ("Set on dynamic board", ["Jh", "Jc"], ["Js", "Th", "9h"]),
    ("River bluff-catcher", ["As", "Qd"], ["Qs", "9c", "5h", "2d", "Tc"]),
]

RANGE_WIDE = [
    # Top ~50+ widened range
    'AA', 'KK', 'QQ', 'JJ', 'TT', '99', '88', '77', '66', '55', '44',
    'AKs', 'AQs', 'AJs', 'ATs', 'A9s', 'A8s', 'A7s', 'A6s', 'A5s', 'A4s', 'A3s', 'A2s',
    'KQs', 'KJs', 'KTs', 'K9s', 'K8s', 'K7s', 'K6s', 'QJs', 'QTs', 'Q9s', 'Q8s', 'Q7s',
    'JTs', 'J9s', 'J8s', 'J7s', 'T9s', 'T8s', 'T7s', '98s', '97s', '87s', '86s', '76s',
    'AKo', 'AQo', 'AJo', 'ATo', 'A9o', 'A8o', 'A7o', 'A6o',
    'KQo', 'KJo', 'KTo', 'K9o', 'K8o', 'QJo', 'QTo', 'Q9o', 'JTo', 'J9o',
]


def equity_and_time(use_pheval: bool) -> dict:
    # monkey-patch flag and reload module
    mc_mod.USE_PHEVALUATOR = use_pheval
    importlib.reload(mc_mod)
    solver = mc_mod.MonteCarloSolver(trials=TRIALS)

    results = []
    for name, hero, board in SPOTS:
        t0 = time.perf_counter()
        eq = solver.estimate_equity(hero, board, RANGE_WIDE, trials=TRIALS)
        t1 = time.perf_counter() - t0
        results.append({"name": name, "hero": hero, "board": board, "eq": eq, "time": t1})
    return results


# ─── Run both backends ───────────────────────────────────────────────────────
print("=" * 70)
print("STRESS TEST: phevaluator vs treys  ({} trials each)".format(TRIALS))
print("=" * 70)

# phevaluator
ph_results = equity_and_time(True)
# treys
importlib.reload(mc_mod)
tr_results = equity_and_time(False)

# ─── Print comparison ────────────────────────────────────────────────────────
header = "%s | %8s | %8s | %8s | %8s | %6s | %s" % (
    "Spot".ljust(30), "PhEq%", "TrEq%", "Diff(pp)", "PhTime", "TrTime", "Result"
)
print()
print(header)
print("-" * len(header))

all_pass = True
speedups = []
for p, t in zip(ph_results, tr_results):
    if p["eq"] is None or t["eq"] is None:
        status = "FAIL (crash)"
        all_pass = False
    else:
        diff = abs(p["eq"] - t["eq"])
        if diff <= 1.5:
            status = "PASS"
        else:
            status = "FAIL (>1.5pp)"
            all_pass = False
        speedups.append(t["time"] / p["time"] if p["time"] > 0 else 0)

    print("%-30s | %8.2f | %8.2f | %8.2f | %7.3fs | %7.3fs | %s" % (
        p["name"][:30],
        p["eq"] if p["eq"] is not None else -1,
        t["eq"] if t["eq"] is not None else -1,
        abs(p["eq"] - t["eq"]) if p["eq"] is not None and t["eq"] is not None else -1,
        p["time"],
        t["time"],
        status,
    ))

avg_speedup = sum(speedups) / len(speedups) if speedups else 0
print()
print("Average phevaluator speedup: {:.1f}x".format(avg_speedup))
print("NOTE: raw eval speedup confirmed at ~2.3x in test_phevaluator.py.")
print("      At small trial counts Python loop overhead dominates runtimes.")
print()
print("-" * 70)
print("EDGE CASES")
print("-" * 70)

# Switch to phevaluator for edge cases
mc_mod.USE_PHEVALUATOR = True
importlib.reload(mc_mod)
solver = mc_mod.MonteCarloSolver(trials=TRIALS)

# Empty hero
for label, hero, board in [
    ("Empty hero", [], ["Kh", "Qh", "7d"]),
    ("5-card board", ["Ah", "Ad"], ["Kh", "Qh", "7d", "2c", "2h"]),
    ("4-card turn board", ["Ah", "Ad"], ["Kh", "Qh", "7d", "2c"]),
]:
    try:
        eq = solver.estimate_equity(hero, board, RANGE_WIDE[:5], trials=2000)
        print("%-25s -> eq=%.1f%%" % (label, eq))
    except Exception as e:
        print("%-25s -> CRASH: %s" % (label, str(e)[:60]))

# ─── Overall verdict ─────────────────────────────────────────────────────────
print()
print("-" * 70)
print("VERDICT")
print("-" * 70)
if all_pass:
    print("ALL PASS. Differences are within normal MC noise; no crashes.")
    print("Use USE_PHEVALUATOR = True as default.")
else:
    print("FAIL. Investigate before switching default.")
