import json
import math
import re
import threading
import time

import cv2
import easyocr
import mss
import numpy as np
import tkinter as tk

from decision_maker import DecisionMaker, PreflopContext
from ghost import GhostArm
from monte_carlo import MonteCarloSolver
from range_matrix import RangeMatrix
from tracker import TableTracker

OCR_KEYS = {
    'hero': re.compile(r'Hero\s*:\s*([AKQJT2-9][shdc])\s*([AKQJT2-9][shdc])', re.IGNORECASE),
    'stack': re.compile(r'Bankroll\s*:\s*\$?([0-9,]+)', re.IGNORECASE),
    'pot_size': re.compile(r'(?:Current\s*Pot\s*Size|POT)\s*[:\-]?\s*\$?([0-9,]+(?:\.[0-9]{1,2})?)', re.IGNORECASE),
    'amount_to_call': re.compile(r'Amount\s*to\s*Call\s*[:\-]?\s*\$?([0-9,]+(?:\.[0-9]{1,2})?)', re.IGNORECASE),
    'game_id': re.compile(r'Game\s+([0-9A-Za-z_-]+)\s+started', re.IGNORECASE),
    'hero_turn': re.compile(r'(Your\s+Turn|Hero\s+to\s+act|Action\s*[:\s]*You)', re.IGNORECASE)
}

class OverlayEngine:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title('TornPoker HUD')
        self.root.overrideredirect(True)
        self.root.attributes('-topmost', True)
        self.root.attributes('-transparentcolor', 'grey')
        self.root.geometry('420x220+-1900+20')
        self.canvas = tk.Canvas(self.root, bg='grey', highlightthickness=0)
        self.canvas.pack(fill='both', expand=True)
        self.root.bind('<ButtonPress-1>', self.start_move)
        self.root.bind('<B1-Motion>', self.do_move)
        self.canvas.bind('<ButtonPress-1>', self.start_move)
        self.canvas.bind('<B1-Motion>', self.do_move)
        self.status_text = tk.StringVar(value='Initializing HUD...')
        self.status_label = tk.Label(self.canvas, textvariable=self.status_text, bg='grey', fg='white', font=('Consolas', 11))
        self.status_label.place(x=10, y=10)
        self.range_matrix = RangeMatrix()
        self.solver = MonteCarloSolver(trials=1000)
        self.tracker = TableTracker()
        self.ghost = GhostArm()
        self.ocr_reader = easyocr.Reader(['en'], gpu=True)
        self.screen_capture = mss.MSS()
        self.rank_templates = {}
        for rank in ['A', 'K', 'Q', 'J', 'T', '9', '8', '7', '6', '5', '4', '3', '2']:
            template_path = f'templates/{rank}.png'
            template = cv2.imread(template_path, cv2.IMREAD_GRAYSCALE)
            if template is not None and template.size > 0:
                self.rank_templates[rank] = template
        self.dealer_template = cv2.imread('templates/dealer.png', cv2.IMREAD_GRAYSCALE)
        self.empty_seat_template = cv2.imread('templates/empty_seat.png', cv2.IMREAD_GRAYSCALE)
        # Define a default capture region (top, left, width, height).
        # Adjust these values to match your poker table window. For a second monitor
        # set the `left` value to the horizontal offset of that monitor (e.g. 1920
        # for a 1920x1080 primary display), e.g. `{'top': 100, 'left': 1920, 'width': 800, 'height': 600}`.
        self.capture_region = {'top': 150, 'left': -1600, 'width': 1280, 'height': 850}
        self.hero_cards_region = {'top': 450, 'left': 605, 'width': 147, 'height': 105}
        self.board_cards_region = {'top': 220, 'left': 450, 'width': 395, 'height': 105}
        self.decision_maker = DecisionMaker()
        self.button_coords = {}
        self.last_known = {
            'hero_cards': None,
            'board': [],
            'stack': None,
            'game_id': None,
            'pot_size': None,
            'amount_to_call': None,
        }
        # Default hero position for preflop decisions. Adjust as needed.
        self.hero_position = 'BTN'
        # Debounce / stability tracking to avoid acting on transient UI animations
        self.stable_frames = 0
        self.REQUIRED_STABLE_FRAMES = 3
        self._stable_snapshot = None
        self.locked_stack = None
        self.log_memory = ''
        self.frame_index = 0
        self.running = True
        self.ocr_lock = threading.Lock()
        self.latest_frame_data = {}
        self.drag_start_x = 0
        self.drag_start_y = 0
        self.win_x = 0
        self.win_y = 0
        self._start_ocr_worker()
        self.root.after(30, self._main_tick)

    def _start_ocr_worker(self):
        worker = threading.Thread(target=self._ocr_loop, daemon=True)
        worker.start()

    def start_move(self, event):
        self.drag_start_x = event.x_root
        self.drag_start_y = event.y_root
        self.win_x = self.root.winfo_x()
        self.win_y = self.root.winfo_y()

    def do_move(self, event):
        dx = event.x_root - self.drag_start_x
        dy = event.y_root - self.drag_start_y
        new_x = self.win_x + dx
        new_y = self.win_y + dy
        self.root.geometry(f'+{new_x}+{new_y}')

    def _ocr_loop(self):
        while self.running:
            try:
                frame = self._grab_screen()
                text_results = self.ocr_reader.readtext(frame, detail=1, paragraph=False)
                button_coords = {}
                text_lines = []
                # Prepare a display copy for debug overlay (draw boxes and centers)
                try:
                    disp = cv2.cvtColor(frame.copy(), cv2.COLOR_RGB2BGR)
                except Exception:
                    disp = frame.copy()
                for result in text_results:
                    bbox, detected_text, _confidence = result
                    normalized_text = detected_text.strip().lower()
                    xs = [point[0] for point in bbox]
                    ys = [point[1] for point in bbox]
                    center_x = int(sum(xs) / len(xs))
                    center_y = int(sum(ys) / len(ys))
                    # Convert coordinates from crop-relative to monitor-relative
                    left_offset = int(self.capture_region.get('left', 0)) if isinstance(self.capture_region, dict) else 0
                    top_offset = int(self.capture_region.get('top', 0)) if isinstance(self.capture_region, dict) else 0
                    monitor_x = center_x + left_offset
                    monitor_y = center_y + top_offset

                    # Draw bounding polygon and center on debug frame
                    try:
                        pts = np.array(bbox, np.int32).reshape((-1, 1, 2))
                        cv2.polylines(disp, [pts], True, (0, 255, 0), 2)
                        cv2.circle(disp, (center_x, center_y), 4, (0, 0, 255), -1)
                        cv2.putText(disp, f"{detected_text} ({center_x},{center_y})", (center_x + 5, center_y - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 1)
                    except Exception:
                        pass

                    # Only consider buttons from the bottom 30% of the captured image.
                    is_bottom_button = center_y > (frame.shape[0] * 0.7)

                    # Primary action buttons
                    if normalized_text in {'fold', 'call', 'raise', 'check'} and is_bottom_button:
                        button_coords[normalized_text] = (monitor_x, monitor_y)

                    # Bet sizing labels commonly displayed on poker clients
                    sizing_map = {
                        '1/2': 'raise_half',
                        '1/2 pot': 'raise_half',
                        'half': 'raise_half',
                        'pot': 'raise_pot',
                        'pot+': 'raise_pot',
                        'max': 'raise_allin',
                        'all-in': 'raise_allin',
                        'allin': 'raise_allin',
                        'all in': 'raise_allin',
                        'min': 'raise_half'
                    }
                    key = sizing_map.get(normalized_text)
                    if key and is_bottom_button:
                        button_coords[key] = (monitor_x, monitor_y)
                    text_lines.append(detected_text)

                # Draw hero and board calibration boundaries on the debug display.
                try:
                    if self.hero_cards_region:
                        x = self.hero_cards_region['left']
                        y = self.hero_cards_region['top']
                        w = self.hero_cards_region['width']
                        h = self.hero_cards_region['height']
                        cv2.rectangle(disp, (x, y), (x + w, y + h), (255, 0, 0), 2)
                    if self.board_cards_region:
                        x = self.board_cards_region['left']
                        y = self.board_cards_region['top']
                        w = self.board_cards_region['width']
                        h = self.board_cards_region['height']
                        cv2.rectangle(disp, (x, y), (x + w, y + h), (0, 255, 255), 2)
                except Exception:
                    pass

                hero_cards = self._read_hole_cards(frame)
                board_cards = self._read_board_cards(frame)
                frame_gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
                dealer_seat = self._find_dealer_seat(frame_gray)
                active_seats = self._get_active_seats(frame_gray)
                hero_position = None
                if dealer_seat is not None:
                    hero_position = self.tracker.calculate_hero_position(active_seats, dealer_seat)

                try:
                    stable_frames = getattr(self, 'stable_frames', 0)
                    stable_snapshot = getattr(self, '_stable_snapshot', None)
                    with self.ocr_lock:
                        debug_frame_data = dict(self.latest_frame_data)
                    cur_amount = debug_frame_data.get('amount_to_call')
                    cur_pot = debug_frame_data.get('pot_size')
                    # derive simple snapshot summary for display
                    try:
                        if stable_snapshot is None:
                            snapshot_text = 'None'
                        else:
                            amt, pot, btns = stable_snapshot
                            btn_keys = [k for k, _ in btns]
                            snapshot_text = f"amt:{amt} pot:{pot} btns:{btn_keys[:6]}"
                    except Exception:
                        snapshot_text = str(stable_snapshot)

                    status_line = f"stable_frames: {stable_frames} | stable_snapshot: {snapshot_text}"
                    hero_position_text = f"hero_pos: {hero_position or 'Unknown'}"
                    active_seats_text = f"active_seats: {active_seats}"
                    current_line = f"cur_amt: {cur_amount} cur_pot: {cur_pot} buttons: {list(button_coords.keys())}"
                    cv2.putText(disp, status_line, (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
                    cv2.putText(disp, current_line, (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
                    cv2.putText(disp, active_seats_text, (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
                    cv2.putText(disp, hero_position_text, (10, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
                    cv2.putText(disp, f"hero_cards: {hero_cards}", (10, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
                    cv2.putText(disp, f"board_cards: {board_cards}", (10, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
                    cv2.imshow('TornPoker Debug', disp)
                    cv2.waitKey(1)
                except Exception:
                    pass
                text_blob = '\n'.join(text_lines)
                parsed = self._parse_ocr_text(text_blob)
                if hero_cards:
                    parsed['hero_cards'] = hero_cards
                if board_cards:
                    parsed['board'] = board_cards
                with self.ocr_lock:
                    self.latest_frame_data = parsed
                    self.button_coords = button_coords
                time.sleep(0.03)
            except Exception:
                time.sleep(0.05)

    def _grab_screen(self) -> np.ndarray:
        # Prefer the configured capture_region; fall back to the full primary monitor
        region = self.capture_region if isinstance(self.capture_region, dict) else self.screen_capture.monitors[1]
        shot = self.screen_capture.grab(region)
        frame = np.array(shot)
        frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2RGB)
        return frame

    def _classify_suit_color(self, patch: np.ndarray) -> str:
        if patch.size == 0:
            return 's'
        hsv = cv2.cvtColor(patch, cv2.COLOR_RGB2HSV)
        # Mask out low-saturation or dark pixels (likely background)
        sat = hsv[:, :, 1]
        val = hsv[:, :, 2]
        mask = (sat > 40) & (val > 60)
        if not np.any(mask):
            return 's'
        valid_hues = hsv[:, :, 0][mask]
        med_h = float(np.median(valid_hues))
        # Red spans hue near 0 and high (e.g., >150)
        if med_h < 10 or med_h > 150:
            return 'h'
        # Green
        if 40 < med_h < 90:
            return 'c'
        # Blue/Cyan
        if 90 <= med_h <= 140:
            return 'd'
        return 's'

    def _match_templates(self, gray_crop: np.ndarray, threshold: float = 0.82) -> list:
        matches = []
        for rank, template in self.rank_templates.items():
            if template is None or template.size == 0:
                continue
            if template.shape[0] > gray_crop.shape[0] or template.shape[1] > gray_crop.shape[1]:
                continue
            res = cv2.matchTemplate(gray_crop, template, cv2.TM_CCOEFF_NORMED)
            loc = np.where(res >= threshold)
            h, w = template.shape[:2]
            for y, x in zip(*loc):
                matches.append({
                    'rank': rank,
                    'x': int(x),
                    'y': int(y),
                    'w': int(w),
                    'h': int(h),
                    'score': float(res[y, x])
                })
        matches.sort(key=lambda m: (m['x'], -m['score']))
        nms = []
        for match in matches:
            replaced = False
            for idx, kept in enumerate(nms):
                if abs(match['x'] - kept['x']) <= 15:
                    replaced = True
                    if match['score'] > kept['score']:
                        nms[idx] = match
                    break
            if not replaced:
                nms.append(match)
        return sorted(nms, key=lambda m: m['x'])

    def _find_dealer_seat(self, frame_gray: np.ndarray):
        if self.dealer_template is None or self.dealer_template.size == 0:
            return None
        if frame_gray is None or frame_gray.size == 0:
            return None
        if self.dealer_template.shape[0] > frame_gray.shape[0] or self.dealer_template.shape[1] > frame_gray.shape[1]:
            return None

        res = cv2.matchTemplate(frame_gray, self.dealer_template, cv2.TM_CCOEFF_NORMED)
        min_val, max_val, _, max_loc = cv2.minMaxLoc(res)
        if max_val <= 0.70:
            return None

        x, y = max_loc
        h, w = self.dealer_template.shape[:2]
        center_x = x + w // 2
        center_y = y + h // 2

        closest_seat = None
        closest_dist = float('inf')
        for seat, anchor in self.tracker.seat_anchors.items():
            dist = math.hypot(center_x - anchor[0], center_y - anchor[1])
            if dist < closest_dist:
                closest_dist = dist
                closest_seat = seat
        return closest_seat

    def _get_active_seats(self, frame_gray: np.ndarray) -> list[int]:
        active_seats = [0]
        if self.empty_seat_template is None or self.empty_seat_template.size == 0:
            return active_seats
        if frame_gray is None or frame_gray.size == 0:
            return active_seats

        for seat in range(1, 9):
            anchor = self.tracker.seat_anchors.get(seat)
            if anchor is None:
                continue
            x_center, y_center = anchor
            top = max(0, y_center - 30)
            bottom = min(frame_gray.shape[0], y_center + 30)
            left = max(0, x_center - 30)
            right = min(frame_gray.shape[1], x_center + 30)
            patch = frame_gray[top:bottom, left:right]
            if patch.size == 0:
                continue
            if patch.shape[0] < self.empty_seat_template.shape[0] or patch.shape[1] < self.empty_seat_template.shape[1]:
                continue
            res = cv2.matchTemplate(patch, self.empty_seat_template, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(res)
            if max_val < 0.65:
                active_seats.append(seat)

        return sorted(active_seats)

    def _read_hole_cards(self, frame: np.ndarray) -> list:
        if not self.hero_cards_region:
            return []
        crop = frame[
            self.hero_cards_region['top']:self.hero_cards_region['top'] + self.hero_cards_region['height'],
            self.hero_cards_region['left']:self.hero_cards_region['left'] + self.hero_cards_region['width']
        ]
        if crop.size == 0:
            return []
        gray_crop = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
        matches = self._match_templates(gray_crop)
        cards = []
        for match in matches[:2]:
            center_x = match['x'] + (match['w'] // 2)
            bottom_y = match['y'] + match['h']
            sample_top = bottom_y
            sample_bottom = min(bottom_y + 25, crop.shape[0])
            sample_left = max(center_x - 12, 0)
            sample_right = min(center_x + 12, crop.shape[1])
            patch = crop[sample_top:sample_bottom, sample_left:sample_right]
            suit = self._classify_suit_color(patch)
            cards.append(f"{match['rank']}{suit}")
        return cards

    def _read_board_cards(self, frame: np.ndarray) -> list:
        if not self.board_cards_region:
            return []
        crop = frame[
            self.board_cards_region['top']:self.board_cards_region['top'] + self.board_cards_region['height'],
            self.board_cards_region['left']:self.board_cards_region['left'] + self.board_cards_region['width']
        ]
        if crop.size == 0:
            return []
        gray_crop = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
        matches = self._match_templates(gray_crop)
        cards = []
        for match in matches[:5]:
            center_x = match['x'] + (match['w'] // 2)
            bottom_y = match['y'] + match['h']
            sample_top = bottom_y
            sample_bottom = min(bottom_y + 25, crop.shape[0])
            sample_left = max(center_x - 12, 0)
            sample_right = min(center_x + 12, crop.shape[1])
            patch = crop[sample_top:sample_bottom, sample_left:sample_right]
            suit = self._classify_suit_color(patch)
            cards.append(f"{match['rank']}{suit}")
        return cards

    def _clean_currency_value(self, raw_value: str):
        if not raw_value:
            return None
        cleaned = raw_value.strip()
        cleaned = cleaned.replace('$', '')
        cleaned = cleaned.replace(',', '')
        cleaned = re.sub(r'[^0-9.]', '', cleaned)
        if cleaned.count('.') > 1:
            parts = cleaned.split('.')
            cleaned = parts[0] + '.' + ''.join(parts[1:])
        if cleaned.startswith('.'):
            cleaned = '0' + cleaned
        if cleaned == '':
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None

    def _parse_ocr_text(self, text: str) -> dict:
        parsed = {
            'hero_cards': None,
            'board': [],
            'stack': None,
            'pot_size': None,
            'amount_to_call': None,
            'game_id': None,
            'hero_turn': False,
            'log': text,
        }
        for key, pattern in OCR_KEYS.items():
            found = pattern.search(text)
            if not found:
                continue
            if key == 'hero':
                parsed['hero_cards'] = [found.group(1).upper(), found.group(2).upper()]
            elif key == 'board':
                board = [grp.upper() for grp in found.groups() if grp]
                parsed['board'] = board
            elif key == 'stack':
                parsed['stack'] = found.group(1).replace(',', '')
            elif key in {'pot_size', 'amount_to_call'}:
                parsed[key] = self._clean_currency_value(found.group(1))
            elif key == 'game_id':
                parsed['game_id'] = found.group(1)
            elif key == 'hero_turn':
                parsed['hero_turn'] = True
        return parsed

    def _main_tick(self):
        if not self.running:
            return
        self.frame_index += 1
        try:
            # Read latest OCR data and current button coordinates atomically
            with self.ocr_lock:
                frame_data = dict(self.latest_frame_data)
                detected_buttons = dict(self.button_coords)

            if frame_data:
                # Debounce: compare critical fields across consecutive OCR passes
                cur_amount = frame_data.get('amount_to_call')
                cur_pot = frame_data.get('pot_size')
                # Normalize button snapshot for comparison
                buttons_snapshot = tuple(sorted(detected_buttons.items()))
                snapshot = (cur_amount, cur_pot, buttons_snapshot)

                if snapshot == self._stable_snapshot:
                    self.stable_frames += 1
                else:
                    self.stable_frames = 0
                    self._stable_snapshot = snapshot

                # Apply sticky vision and other protections regardless
                self._apply_sticky_vision(frame_data)
                self._apply_bankroll_lock(frame_data)
                self._apply_log_bleed_protection(frame_data)
                self.tracker.parse_action_log(frame_data.get('log', ''))

            hero_cards = self.last_known['hero_cards']
            board = self.last_known['board']
            stack = self.locked_stack or self.last_known['stack']
            pot_size = self.last_known.get('pot_size')
            amount_to_call = self.last_known.get('amount_to_call')

            # Only act when the detected state has been stable for REQUIRED_STABLE_FRAMES
            if frame_data and frame_data.get('hero_turn') and self.stable_frames >= self.REQUIRED_STABLE_FRAMES:
                self._try_make_decision(hero_cards, board, stack, pot_size, amount_to_call)
                # Reset after taking action to avoid duplicate execution
                self.stable_frames = 0
                self._stable_snapshot = None
            summary = self._build_summary(hero_cards, board, stack, pot_size, amount_to_call)
            self.status_text.set(summary)
        except Exception:
            self.status_text.set('HUD error: retrying...')
        finally:
            self.root.after(30, self._main_tick)

    def _apply_sticky_vision(self, frame_data: dict) -> None:
        hero = frame_data.get('hero_cards')
        if hero and len(hero) == 2:
            self.last_known['hero_cards'] = hero
        elif self.last_known['hero_cards'] is None:
            self.last_known['hero_cards'] = None
        board = frame_data.get('board', [])
        if board:
            self.last_known['board'] = board
        if frame_data.get('pot_size') is not None:
            self.last_known['pot_size'] = frame_data['pot_size']
        if frame_data.get('amount_to_call') is not None:
            self.last_known['amount_to_call'] = frame_data['amount_to_call']

    def _apply_bankroll_lock(self, frame_data: dict) -> None:
        if self.frame_index == 1 and frame_data.get('stack'):
            self.locked_stack = frame_data['stack']
        if frame_data.get('game_id') != self.last_known['game_id']:
            if self.last_known['game_id'] is not None:
                self.locked_stack = None
            self.last_known['game_id'] = frame_data.get('game_id')

    def _apply_log_bleed_protection(self, frame_data: dict) -> None:
        game_id = frame_data.get('game_id')
        if game_id and game_id != self.last_known.get('game_id'):
            self.log_memory = ''
            self.last_known['hero_cards'] = None
            self.last_known['board'] = []
        self.last_known['game_id'] = game_id

    def _build_summary(self, hero_cards, board, stack, pot_size, amount_to_call) -> str:
        lines = []
        if hero_cards:
            lines.append(f'Hero: {hero_cards[0]} {hero_cards[1]}')
        else:
            lines.append('Hero: unknown')
        if board:
            lines.append(f'Board: {" ".join(board)}')
        else:
            lines.append('Board: empty')
        if stack:
            lines.append(f'Bankroll: ${stack}')
        else:
            lines.append('Bankroll: unknown')
        if pot_size is not None:
            lines.append(f'Pot: ${pot_size:.2f}')
        if amount_to_call is not None:
            lines.append(f'Call: ${amount_to_call:.2f}')
        if hero_cards and board is not None:
            opp_id = next(iter(self.tracker.players), None)
            equity_text = 'N/A'
            pot_odds_text = 'N/A'
            if amount_to_call is not None and pot_size is not None and amount_to_call >= 0 and pot_size >= 0:
                total_pot = pot_size + amount_to_call
                if total_pot > 0:
                    pot_odds = amount_to_call / total_pot * 100.0
                    pot_odds_text = f'{pot_odds:.1f}%'
            if opp_id:
                self.range_matrix.add_opponent(opp_id)
                self.range_matrix.update_range_from_action(opp_id, 'raise', self.tracker.get_pfr_rate(opp_id))
                active_range = self.range_matrix.get_active_combos(opp_id)
                equity = self.solver.estimate_equity(hero_cards, board, active_range)
                equity_text = f'{equity:.1f}%'
                lines.append(f'Opponent ({opp_id}) profile: {self.tracker.get_player_profile(opp_id)}')
                lines.append(f'Range: {self.range_matrix.describe_range(opp_id)}')
            lines.append(f'Equity: {equity_text} | Pot Odds: {pot_odds_text}')
        return '\n'.join(lines)

    def _try_make_decision(self, hero_cards, board, stack, pot_size, amount_to_call) -> None:
        if not hero_cards:
            return

        # Pre-flop bypass: use PFR chart and avoid Monte Carlo
        if board is not None and len(board) == 0:
            # Build preflop context
            context = PreflopContext(
                position=self.hero_position,
                hero_action_type='unopened',
                vs_position=None,
                effective_stack_bb=100.0,
            )
            decision = self.decision_maker.choose_preflop_action(hero_cards, context)
            
            # Log preflop decision
            combo = DecisionMaker._cards_to_combo(hero_cards)
            print(f"[PREFLOP] hero_cards={hero_cards} combo={combo} context={context} decision={decision}")
            
            # Route decision directly to execution
            if decision == 'Raise':
                raise_coord = self.button_coords.get('raise')
                if raise_coord:
                    self.safe_execute_decision(raise_coord[0], raise_coord[1])
                return
            elif decision == 'Call':
                call_coord = self.button_coords.get('call')
                if call_coord:
                    self.safe_execute_decision(call_coord[0], call_coord[1])
                return
            elif decision == 'Fold':
                fold_coord = self.button_coords.get('fold')
                if fold_coord:
                    self.safe_execute_decision(fold_coord[0], fold_coord[1])
                return

        # Post-flop: use equity + EV decision
        if pot_size is None or amount_to_call is None:
            return
        opp_id = next(iter(self.tracker.players), None)
        if not opp_id:
            return
        active_range = self.range_matrix.get_active_combos(opp_id)
        equity = self.solver.estimate_equity(hero_cards, board, active_range)
        decision = self.decision_maker.choose_action(
            equity_pct=equity,
            pot_size=pot_size,
            amount_to_call=amount_to_call,
            bankroll=float(stack or 0),
            active_range=active_range,
        )
        # Handle sized raises: e.g., 'Raise_Pot', 'Raise_Half', 'Raise_AllIn'
        if isinstance(decision, str) and decision.startswith('Raise'):
            parts = decision.split('_')
            size_key = parts[1].lower() if len(parts) > 1 else 'pot'
            sizing_map_keys = {
                'half': 'raise_half',
                'pot': 'raise_pot',
                'allin': 'raise_allin',
                'allin': 'raise_allin',
                'allin': 'raise_allin',
                'allin': 'raise_allin',
                'allin': 'raise_allin'
            }
            sizing_key = f"raise_{size_key}"
            sizing_coord = self.button_coords.get(sizing_key)
            raise_coord = self.button_coords.get('raise')
            if sizing_coord and raise_coord:
                # Click sizing then raise
                try:
                    self.ghost.click_sequence([
                        {'x': sizing_coord[0], 'y': sizing_coord[1]},
                        {'x': raise_coord[0], 'y': raise_coord[1]}
                    ])
                except Exception:
                    pass
                return
            # Fallback: click raise only
            if raise_coord:
                self.safe_execute_decision(raise_coord[0], raise_coord[1])
            return

        target = self.button_coords.get(decision.lower())
        if target:
            self.safe_execute_decision(target[0], target[1])

    def safe_execute_decision(self, x: int, y: int) -> bool:
        print(f"DRY RUN - WOULD CLICK: {x}, {y}")
        return True # self.ghost.execute_move(x, y)

    def run(self) -> None:
        try:
            self.root.mainloop()
        finally:
            self.running = False


if __name__ == '__main__':
    engine = OverlayEngine()
    engine.run()
