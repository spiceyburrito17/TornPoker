# TornPoker GTO Poker Engine

Modular computer-vision-driven Texas Hold'em bot.

## Overview

This project includes a complete Python engine for reading browser poker tables, tracking opponents, calculating equity, and automating mouse actions.

Modules:
- `range_matrix.py` - 169-hand range management and pre-flop narrowing
- `monte_carlo.py` - Monte Carlo equity solver using `treys`
- `tracker.py` - opponent profiling, VPIP/PFR/AF tracking, and JSON persistence
- `ghost.py` - pyautogui execution arm with mutex locking and human delay curves
- `engine.py` - Tkinter HUD overlay, OCR capture thread, sticky vision cache, bankroll lock, and log bleed protection

## Requirements

Install the environment dependencies before running:

```powershell
python -m pip install -r requirements.txt
```

## Recommended dependencies

- Python 3.10+ or newer
- `opencv-python`
- `easyocr`
- `mss`
- `numpy`
- `treys`
- `pyautogui`
- `pillow`
- `tk`

## Run the Engine

From the project folder:

```powershell
python engine.py
```

## Notes

- Ensure the poker browser window is visible on the primary monitor.
- Allow the overlay and automation access to the screen.
- If `easyocr` or `treys` are missing, install them with `pip`.
- This engine is built for deployment and should be run with caution in real environments.

## Sample Deployment Workflow

1. Create a fresh Python virtual environment.
2. Install dependencies via `pip install -r requirements.txt`.
3. Launch `python engine.py`.
4. Observe the HUD overlay and confirm the OCR is reading the table.

## File Structure

- `engine.py` - main application loop and overlay
- `range_matrix.py` - opponent range matrix
- `monte_carlo.py` - equity simulations
- `tracker.py` - player log tracking and profiling
- `ghost.py` - click automation arm
- `player_stats.json` - tracked stats storage (generated at runtime)
