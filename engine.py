import json
import math
import re
import threading
import time
from enum import Enum, auto

import cv2
import easyocr
import mss
import numpy as np
import tkinter as tk

from decision_maker import DecisionMaker, PreflopContext
from ghost import GhostArm
from monte_carlo import MonteCarloSolver
from range_matrix import RangeMatrix
from session_logger import SessionLogger
from tracker import TableTracker

HERO_WINS_RE = re.compile(r'(?:Hero|you)\s+wins?\s+\$?([0-9,]+(?:\.[0-9]{1,2})?)', re.IGNORECASE)
HERO_LOSES_RE = re.compile(r'(?:Hero|you)\s+(?:loses?|mucks?|folds?)\b', re.IGNORECASE)

class Street(Enum):
    PREFLOP = auto()
    FLOP = auto()
    TURN = auto()
    RIVER = auto()

OCR_KEYS = {
    'hero': re.compile(r'Hero\s*:\s*([AKQJT2-9][shdc])\s*([AKQJT2-9][shdc])', re.IGNORECASE),
    'stack': re.compile(r'Bankroll\s*:\s*\$?([0-9,]+)', re.IGNORECASE),
    'pot_size': re.compile(r'(?:Current\s*Pot\s*Size|POT)\s*[:\-]?\s*\$?([0-9,]+(?:\.[0-9]{1,2})?)', re.IGNORECASE),
    'amount_to_call': re.compile(r'Amount\s*to\s*Call\s*[:\-]?\s*\$?([0-9,]+(?:\.[0-9]{1,2})?)', re.IGNORECASE),
    'game_id': re.compile(r'Game\s+([0-9A-Za-z_-]+)\s+started', re.IGNORECASE),
    'hero_turn': re.compile(r'(Your\s+Turn|Hero\s+to\s+act|Action\s*[:\s]*You)', re.IGNORECASE)
}

BET_INPUT_COORD = (-1030, 660)

class OverlayEngine:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title('TornPoker HUD')
        self.root.overrideredirect(True)
        self.root.attributes('-topmost', True)
        
        # --- NEW SLEEK UI BACKGROUND ---
        self.root.attributes('-alpha', 0.85)  # 85% solid, slightly see-through
        self.root.geometry('450x250+50+50')   # Starts at top-left of MAIN screen
        
        self.canvas = tk.Canvas(self.root, bg='black', highlightthickness=0)
        self.canvas.pack(fill='both', expand=True)
        self.root.bind('<ButtonPress-1>', self.start_move)
        self.root.bind('<B1-Motion>', self.do_move)
        self.canvas.bind('<ButtonPress-1>', self.start_move)
        self.canvas.bind('<B1-Motion>', self.do_move)
        self.status_text = tk.StringVar(value='Initializing HUD...')
        
        # --- BRIGHT GREEN TEXT ON BLACK ---
        self.status_label = tk.Label(self.canvas, textvariable=self.status_text, bg='black', fg='#00FF00', font=('Consolas', 12, 'bold'), justify='left')
        self.status_label.place(x=10, y=10)
        self.range_matrix = RangeMatrix()
        self.solver = MonteCarloSolver(trials=1000)
        self.tracker = TableTracker()
        self.ghost = GhostArm()
        self.screen_capture = mss.MSS()
        self.debug_window_name = 'TornPoker Debug'
        
        # --- BACKGROUND LOAD FIX ---
        self.ocr_reader = None
        self._ocr_ready = False
        threading.Thread(target=self._init_ocr, daemon=True).start()
        self._cv2_window_created = False
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
        self.stack_region = {'top': 577, 'left': 575, 'width': 140, 'height': 35} # Adjust these later to fit over your money
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
        self.current_street = Street.PREFLOP
        self.current_recommendation = 'WAIT'
        self._last_active_seats = []
        self._last_dealer_seat  = None
        # Debounce / stability tracking to avoid acting on transient UI animations
        self.stable_frames = 0
        self.REQUIRED_STABLE_FRAMES = 3
        self._stable_snapshot = None
        self.locked_stack = None
        self.log_memory = ''
        self.frame_index = 0
        self._last_range_game_id = None
        self._last_range_street = None
        self.session_logger = SessionLogger()
        self._showdown_recorded_for = None
        self._logger_game_id = None
        self.running = True
        self.ocr_lock = threading.Lock()
        self.latest_frame_data = {}
        self.drag_start_x = 0
        self.drag_start_y = 0
        self.win_x = 0
        self.win_y = 0
        self._start_ocr_worker()
        self.root.after(30, self._main_tick)

    def _init_ocr(self):
        print("[SYSTEM] Loading EasyOCR models... (Please wait 15-30 seconds)")
        self.ocr_reader = easyocr.Reader(['en'], gpu=True)
        self._ocr_ready = True
        print("[SYSTEM] EasyOCR Loaded! Engine is starting...")

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

    def _determine_current_street(self, board_cards: list) -> Street:
        count = len(board_cards) if board_cards is not None else 0
        if count == 0:
            return Street.PREFLOP
        elif count == 3:
            return Street.FLOP
        elif count == 4:
            return Street.TURN
        elif count == 5:
            return Street.RIVER
        return Street.PREFLOP

    def _get_action_color(self, action: str) -> tuple:
        if not action:
            return (255, 255, 255)
        action_lower = action.lower()
        if 'fold' in action_lower:
            return (0, 0, 255)
        if 'call' in action_lower or 'check' in action_lower:
            return (0, 255, 0)
        if 'raise' in action_lower:
            return (0, 215, 255)
        return (255, 255, 255)

    def _ocr_loop(self):
        while self.running:
            # 1. Wait for OCR to finish loading
            if not getattr(self, '_ocr_ready', False):
                time.sleep(0.5)
                continue

            # 2. Safely create the OpenCV window on the first active frame
            if not getattr(self, '_cv2_window_created', False):
                cv2.namedWindow(self.debug_window_name, cv2.WINDOW_NORMAL)
                monitors = self.screen_capture.monitors
                target = monitors[1] if len(monitors) > 1 else monitors[0]
                cv2.moveWindow(self.debug_window_name, target['left'] + 50, target['top'] + 50)
                self._cv2_window_created = True
            try:
                frame = self._grab_screen()
                text_results = self.ocr_reader.readtext(frame, detail=1, paragraph=False)
                button_coords = {}
                text_lines = []
                # Prepare a display copy for debug overlay (draw boxes and centers)
                visual_stack = None
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
                    # --- NEW STACK CAPTURE LOGIC ---
                    if getattr(self, 'stack_region', None):
                        sx = self.stack_region['left']
                        sy = self.stack_region['top']
                        sw = self.stack_region['width']
                        sh = self.stack_region['height']
                        if sx <= center_x <= sx + sw and sy <= center_y <= sy + sh:
                            cleaned = re.sub(r'[^0-9.,]', '', detected_text)
                            if cleaned.startswith('5') and ',' in cleaned:
                                candidate = cleaned[1:]
                                if re.match(r'^\d{1,3}(,\d{3})*$', candidate):
                                    cleaned = candidate
                            cleaned = cleaned.replace(',', '')
                            if cleaned:
                                visual_stack = cleaned
                    # -------------------------------

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

                    # Extract call amount from the call button label (e.g. "Call $250" or "CALL 250")
                    call_label_match = re.match(r'^call\s+\$?([\d,]+(?:\.\d{1,2})?)', normalized_text)
                    if call_label_match and is_bottom_button:
                        button_coords['call_amount_raw'] = call_label_match.group(1)

                    # Bet sizing labels commonly displayed on poker clients
                    sizing_map = {
                        '1/3': 'raise_third',
                        '1/3 pot': 'raise_third',
                        'third': 'raise_third',
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
                    if getattr(self, 'stack_region', None):
                        x = self.stack_region['left']
                        y = self.stack_region['top']
                        w = self.stack_region['width']
                        h = self.stack_region['height']
                        cv2.rectangle(disp, (x, y), (x + w, y + h), (0, 0, 255), 2)
                        cv2.putText(disp, "STACK", (x, y - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 255), 1)
                except Exception:
                    pass

                hero_cards = self._read_hole_cards(frame)
                board_cards = self._read_board_cards(frame)
                self.current_street = self._determine_current_street(board_cards)
                frame_gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
                dealer_seat = self._find_dealer_seat(frame_gray)
                active_seats = self._get_active_seats(frame_gray)
                hero_position = None
                if dealer_seat is not None:
                    hero_position = self.tracker.calculate_hero_position(active_seats, dealer_seat)
                    # Persist hero position for decision routing
                    if hero_position is not None:
                        self.hero_position = hero_position
                        self._last_active_seats = active_seats
                        self._last_dealer_seat = dealer_seat

                text_blob = '\n'.join(text_lines)
                current_game_id = self.last_known.get('game_id')
                if self._showdown_recorded_for != current_game_id:
                    wins_match = HERO_WINS_RE.search(text_blob)
                    if wins_match:
                        amount = float(wins_match.group(1).replace(',', ''))
                        self.session_logger.record_outcome(
                            current_game_id or '',
                            amount,
                            showdown_seen=True,
                        )
                        self._showdown_recorded_for = current_game_id
                    else:
                        loses_match = HERO_LOSES_RE.search(text_blob)
                        if loses_match:
                            self.session_logger.record_outcome(
                                current_game_id or '',
                                0.0,
                                showdown_seen=True,
                            )
                            self._showdown_recorded_for = current_game_id
                parsed = self._parse_ocr_text(text_blob)
                # Dedicated preprocessed stack crop for better digit accuracy
                if getattr(self, 'stack_region', None):
                    sr = self.stack_region
                    stack_crop = frame[sr['top']:sr['top']+sr['height'], sr['left']:sr['left']+sr['width']]
                    stack_crop = self._preprocess_number_crop(stack_crop)
                    stack_results = self.ocr_reader.readtext(stack_crop, allowlist='0123456789.,')
                    if stack_results:
                        raw_stack = ''.join([r[1] for r in stack_results])
                        cleaned_stack = re.sub(r'[^0-9.]', '', raw_stack.replace(',', ''))
                        if cleaned_stack:
                            visual_stack = cleaned_stack
                if visual_stack is not None:
                    parsed['stack'] = visual_stack
                if hero_cards:
                    parsed['hero_cards'] = hero_cards
                if board_cards:
                    parsed['board'] = board_cards
                call_amount_raw = button_coords.pop('call_amount_raw', None)
                if call_amount_raw is not None:
                    button_call_amount = self._clean_currency_value(call_amount_raw)
                    if button_call_amount is not None:
                        parsed['amount_to_call'] = button_call_amount

                req_equity = 0.0
                hero_equity = None
                if board_cards and hero_cards and parsed.get('amount_to_call') is not None and parsed.get('pot_size') is not None:
                    pot_size_val = parsed['pot_size']
                    amount_to_call_val = parsed['amount_to_call']
                    potential_pot = pot_size_val + amount_to_call_val
                    req_equity = (amount_to_call_val / potential_pot) * 100 if potential_pot > 0 else 0.0
                    opp_id = self.tracker.get_primary_opponent()
                    if opp_id:
                        active_range = self.range_matrix.get_active_combos(opp_id)
                        hero_equity = self.solver.estimate_equity(hero_cards, board_cards, active_range)

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

                    street_text = f"STREET: {self.current_street.name}"
                    status_line = f"stable_frames: {stable_frames} | stable_snapshot: {snapshot_text}"
                    hero_position_text = f"hero_pos: {hero_position or 'Unknown'}"
                    active_seats_text = f"active_seats: {active_seats}"
                    current_line = f"cur_amt: {cur_amount} cur_pot: {cur_pot} buttons: {list(button_coords.keys())}"
                    cv2.putText(disp, street_text, (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
                    cv2.putText(disp, status_line, (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
                    cv2.putText(disp, current_line, (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
                    cv2.putText(disp, active_seats_text, (10, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
                    cv2.putText(disp, hero_position_text, (10, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
                    cv2.putText(disp, f"hero_cards: {hero_cards}", (10, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
                    cv2.putText(disp, f"board_cards: {board_cards}", (10, 140), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
                    if hero_equity is not None:
                        cv2.putText(disp, f"Req Eq: {req_equity:.1f}% | Hero Eq: {hero_equity:.1f}%", (10, 160), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
                    final_action = getattr(self, 'current_recommendation', 'WAIT') or 'WAIT'
                    action_text = f"MOVE: {final_action.upper()}"
                    font = cv2.FONT_HERSHEY_SIMPLEX
                    font_scale = 1.5
                    thickness = 4
                    text_size, baseline = cv2.getTextSize(action_text, font, font_scale, thickness)
                    x, y = 50, 420
                    cv2.rectangle(
                        disp,
                        (x - 12, y - text_size[1] - 14),
                        (x + text_size[0] + 12, y + baseline + 8),
                        (0, 0, 0),
                        cv2.FILLED,
                    )
                    cv2.putText(
                        disp,
                        action_text,
                        (x, y),
                        font,
                        font_scale,
                        self._get_action_color(final_action),
                        thickness,
                        cv2.LINE_AA,
                    )
                    cv2.imshow(self.debug_window_name, disp)
                    cv2.waitKey(1)
                except Exception:
                    pass
                with self.ocr_lock:
                    self.latest_frame_data = parsed
                    self.button_coords = button_coords
                time.sleep(0.03)
            except Exception as e:
                print(f"OCR Error: {e}")
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

    def _preprocess_number_crop(self, img):
        """Upscale and threshold a number crop for better OCR accuracy."""
        img = cv2.resize(img, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
        _, thresh = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)
        return thresh

    def _clean_currency_value(self, raw_value: str):
        if not raw_value:
            return None
        cleaned = raw_value.strip()
        cleaned = cleaned.replace('$', '')
        # Fix $ → 5 OCR misread: if starts with '5' and remaining looks like a valid amount
        # that would be unreasonably large with the leading 5, strip it
        if cleaned.startswith('5') and len(cleaned) >= 4:
            candidate = cleaned[1:].replace(',', '')
            candidate_clean = re.sub(r'[^0-9.]', '', candidate)
            if candidate_clean and candidate_clean[0].isdigit():
                # If keeping the 5 makes it 10x larger than without, it's likely a misread
                try:
                    with_5 = float(re.sub(r'[^0-9.]', '', cleaned.replace(',', '')))
                    without_5 = float(candidate_clean)
                    if with_5 > 1000 and without_5 < 1000:
                        cleaned = cleaned[1:]
                except ValueError:
                    pass
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
                self.current_street = self._determine_current_street(self.last_known['board'])
                self.tracker.parse_action_log(frame_data.get('log', ''))
                self._update_range_matrix(frame_data.get('log', ''), frame_data.get('game_id'))
                if frame_data.get('stack') is not None:
                    self.last_known['stack'] = frame_data['stack']

            hero_cards = self.last_known['hero_cards']
            board = self.last_known['board']
            stack = self.locked_stack or self.last_known['stack']
            pot_size = self.last_known.get('pot_size')
            amount_to_call = self.last_known.get('amount_to_call')

            # Only act when the detected state has been stable for REQUIRED_STABLE_FRAMES
            if frame_data and self.stable_frames >= self.REQUIRED_STABLE_FRAMES:
                hero_turn = frame_data.get('hero_turn', False)
                print(f"[TRIGGER] stable_frames={self.stable_frames} hero_turn={hero_turn} street={self.current_street.name} hero_cards={hero_cards}")
                if hero_turn:
                    self._try_make_decision(hero_cards, board, stack, pot_size, amount_to_call)
                # Reset after taking action to avoid duplicate execution
                self.stable_frames = 0
                self._stable_snapshot = None
            summary = self._build_summary(hero_cards, board, stack, pot_size, amount_to_call)
            self.status_text.set(summary)
        except Exception as e:
            import traceback
            print(f'[DECISION ERROR] {e}')
            traceback.print_exc()
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
            if frame_data.get('game_id'):
                if self.last_known['game_id'] is not None:
                    self.locked_stack = None
                self.last_known['game_id'] = frame_data.get('game_id')
            # else: keep existing game_id — OCR missed it this frame

    def _apply_log_bleed_protection(self, frame_data: dict) -> None:
        game_id = frame_data.get('game_id')
        if game_id and game_id != self.last_known.get('game_id'):
            self.log_memory = ''
            self.last_known['hero_cards'] = None
            self.last_known['board'] = []
        self.last_known['game_id'] = game_id

    def _build_summary(self, hero_cards, board, stack, pot_size, amount_to_call) -> str:
        from decision_maker import analyze_board_texture, calculate_mdf
        lines = []

        if hero_cards:
            lines.append(f'Hero: {hero_cards[0]} {hero_cards[1]}')
        else:
            lines.append('Hero: unknown')

        if board:
            texture = analyze_board_texture(board)
            lines.append(
                f'Board: {" ".join(board)} '
                f'[{texture["texture_label"]} | wet={texture["wetness"]:.2f}]'
            )
        else:
            lines.append('Board: empty')

        lines.append(f'Bankroll: ${stack}' if stack else 'Bankroll: unknown')
        if pot_size is not None:
            lines.append(f'Pot: ${pot_size:.2f}')
        if amount_to_call is not None:
            lines.append(f'Call: ${amount_to_call:.2f}')

        opp_id = self.tracker.get_primary_opponent()
        equity = 0.0
        pot_odds_pct = 0.0
        active_range = []

        if hero_cards and board is not None and opp_id:
            vpip = self.tracker.get_vpip_rate(opp_id)
            pfr  = self.tracker.get_pfr_rate(opp_id)
            profile = self.tracker.get_player_profile(opp_id)
            rw_mult, ag_mult = self.tracker.get_range_modifiers(opp_id)
            lines.append(
                f'Opp ({opp_id}): {profile} | '
                f'VPIP={vpip:.0f}% PFR={pfr:.0f}% '
                f'RangeMult={rw_mult:.2f} AggMult={ag_mult:.2f}'
            )
            active_range = self.range_matrix.get_active_combos(opp_id)
            equity = self.solver.estimate_equity(hero_cards, board, active_range, trials=1000)

        if pot_size is not None and amount_to_call is not None:
            total = pot_size + amount_to_call
            pot_odds_pct = (amount_to_call / total * 100.0) if total > 0 else 0.0
            if hero_cards and board and active_range and abs(equity - pot_odds_pct) < 5.0:
                equity = self.solver.estimate_equity(hero_cards, board, active_range, trials=5000)

        equity_text   = f'{equity:.1f}%'
        pot_odds_text = f'{pot_odds_pct:.1f}%' if pot_odds_pct else 'N/A'
        mdf_text      = 'N/A'
        if amount_to_call is not None and amount_to_call > 0 and pot_size is not None:
            mdf = calculate_mdf(amount_to_call, pot_size)
            mdf_text = f'{mdf * 100:.1f}%'

        with self.ocr_lock:
            active_seats = getattr(self, '_last_active_seats', [0])
            dealer_seat  = getattr(self, '_last_dealer_seat', None)
        ip_label = 'IP' if self.tracker.is_hero_in_position(active_seats, dealer_seat) else 'OOP'
        lines.append(
            f'Equity: {equity_text} | PotOdds: {pot_odds_text} '
            f'| MDF: {mdf_text} | Pos: {ip_label}'
        )

        # Show current recommendation prominently
        rec = getattr(self, 'current_recommendation', 'WAIT') or 'WAIT'
        lines.append(f'>>> {rec} <<<')

        bb_100 = self.session_logger.get_bb_per_100()
        hands_count = len(self.session_logger._hands)
        lines.append(f'Session: {hands_count} hands | BB/100: {bb_100:+.1f}')
        return '\n'.join(lines)

    def _update_range_matrix(self, log: str, game_id) -> None:
        opp_id = self.tracker.get_primary_opponent()
        if not opp_id:
            return

        new_game = game_id and game_id != self._last_range_game_id
        new_street = self.current_street != self._last_range_street

        if new_game:
            self.range_matrix.remove_opponent(opp_id)
            self.range_matrix.add_opponent(opp_id)
            self._last_range_game_id = game_id
            self._last_range_street = None

        if new_street and self._last_range_street is not None:
            board = self.last_known.get('board', [])
            if board:
                self.range_matrix.prune_by_board(opp_id, board)
        self._last_range_street = self.current_street

        if not log:
            return

        pfr = self.tracker.get_pfr_rate(opp_id)
        for line in log.splitlines():
            line = line.strip()
            if not line:
                continue
            name_match = re.match(r'^([A-Za-z0-9_]+)\s+(raises|calls|folds|checks|bets|limps)', line, re.IGNORECASE)
            if not name_match:
                continue
            player = name_match.group(1)
            action = name_match.group(2).lower()
            if player.lower() == opp_id.lower():
                self.range_matrix.update_range_from_action(opp_id, action, pfr)

    def _try_make_decision(self, hero_cards, board, stack, pot_size, amount_to_call) -> None:
        self.current_recommendation = 'WAIT'
        if not hero_cards:
            return

        game_id = self.last_known.get('game_id')
        if game_id != self._logger_game_id:
            self.session_logger.start_hand(game_id)
            self._logger_game_id = game_id

        amount_to_call = amount_to_call if amount_to_call is not None else 0.0
        if amount_to_call == 0.0 and self.current_street != Street.PREFLOP:
            # Free action — still evaluate bet vs check, don't auto-skip
            pass

        print(f'[DECISION] street={self.current_street.name} hero_cards={hero_cards} amt={amount_to_call} pot={pot_size}')

        # Deduplication — only log/act once per game+hand+street combination
        _decision_key = f"{game_id}_{self.session_logger._hand_num}_{self.current_street.name}"
        if _decision_key == getattr(self, '_last_logged_decision', None):
            return  # already logged this decision
        self._last_logged_decision = _decision_key

        # ---------- PREFLOP ----------
        if self.current_street == Street.PREFLOP:
            with self.ocr_lock:
                log = self.latest_frame_data.get('log', '')
            raise_count = len(re.findall(r'\b(raises|raised|re-raise|3bet)\b', log, re.IGNORECASE))
            if raise_count >= 2:
                action_type = 'vs_3bet'
                vs_pos = self.hero_position
            elif raise_count == 1:
                action_type = 'vs_open'
                raiser_match = re.search(r'([A-Za-z0-9_]+)\s+raises', log, re.IGNORECASE)
                vs_pos = raiser_match.group(1) if raiser_match else 'CO'
            else:
                action_type = 'unopened'
                vs_pos = None
            context = PreflopContext(
                position=self.hero_position,
                hero_action_type=action_type,
                vs_position=vs_pos,
                effective_stack_bb=float(stack) / 1.0 if stack else 100.0,
            )
            final_action = self.decision_maker.choose_preflop_action(hero_cards, context)
            self.current_recommendation = final_action
            combo = DecisionMaker._cards_to_combo(hero_cards)
            print(f"[PREFLOP] hero_cards={hero_cards} combo={combo} decision={final_action}")
            self.session_logger.log_decision(
                game_id=game_id,
                street='PREFLOP',
                hero_cards=hero_cards,
                board=[],
                hero_position=self.hero_position,
                pot_size=pot_size,
                amount_to_call=amount_to_call,
                stack=stack,
                equity_pct=0.0,
                decision=final_action,
            )
            self.safe_execute_decision(final_action, pot_size=pot_size or 0.0)
            return

        # ---------- POSTFLOP ----------
        if pot_size is None:
            print(f'[DECISION SKIP] pot_size is None — skipping decision')
            return
        if amount_to_call is None:
            amount_to_call = 0.0
        opp_id = self.tracker.get_primary_opponent()
        if opp_id is None:
            print(f'[DECISION] no opponent profile yet — using default range')
            # Use top 50% of all combos as neutral default range
            active_range = self.range_matrix.hand_order[:len(self.range_matrix.hand_order) // 2]
            opp_profile = {'vpip': 50.0, 'pfr': 25.0, 'af': 1.0}
            range_width_mult, aggression_mult = 1.0, 1.0
        else:
            active_range = list(self.range_matrix.get_active_combos(opp_id))
            opp_profile = self.tracker.get_player_profile(opp_id)
            range_width_mult, aggression_mult = self.tracker.get_range_modifiers(opp_id)

        # Phase 4: is hero acting last?
        with self.ocr_lock:
            active_seats = getattr(self, '_last_active_seats', [0])
            dealer_seat  = getattr(self, '_last_dealer_seat', None)
        hero_is_ip = self.tracker.is_hero_in_position(active_seats, dealer_seat)

        equity = self.solver.estimate_equity(hero_cards, board, active_range, trials=1000)
        print(f"[MC RESULT] equity={equity}")
        pot_odds_pct = amount_to_call / (pot_size + amount_to_call) * 100.0 if (pot_size + amount_to_call) > 0 else 0.0
        if abs(equity - pot_odds_pct) < 5.0:
            equity = self.solver.estimate_equity(hero_cards, board, active_range, trials=5000)

        # Phase 3: rough equity rank (0 = top of range, 1 = bottom)
        # Simple approximation: invert equity percentage
        hero_equity_rank = max(0.0, min(1.0, 1.0 - equity / 100.0))

        final_action = self.decision_maker.choose_action(
            equity_pct=equity,
            pot_size=pot_size,
            amount_to_call=amount_to_call,
            bankroll=float(stack or 0),
            active_range=active_range,
            current_street=self.current_street,
            board=board,
            hero_is_ip=hero_is_ip,
            range_width_mult=range_width_mult,
            aggression_mult=aggression_mult,
            hero_equity_rank=hero_equity_rank,
            hero_position=self.hero_position,
            vs_position=opp_id,
        )
        self.current_recommendation = final_action
        self.session_logger.log_decision(
            game_id=game_id,
            street=self.current_street.name,
            hero_cards=hero_cards,
            board=board or [],
            hero_position=self.hero_position,
            pot_size=pot_size,
            amount_to_call=amount_to_call,
            stack=stack,
            equity_pct=equity,
            decision=final_action,
            opp_vpip=self.tracker.get_vpip_rate(opp_id) if opp_id else None,
            opp_pfr=self.tracker.get_pfr_rate(opp_id) if opp_id else None,
            opp_af=self.tracker.summarize_player(opp_id).get('aggression_factor') if opp_id else None,
        )
        self.safe_execute_decision(final_action, pot_size=pot_size or 0.0)

    def safe_execute_decision(self, action: str, pot_size: float = 0.0) -> bool:
        with self.ocr_lock:
            buttons = dict(self.button_coords)

        action_lower = (action or '').strip().lower()

        if action_lower in {'raise_third', 'raise_half', 'raise_pot'}:
            raise_coord = buttons.get('raise')
            if not raise_coord:
                print(f"DRY RUN - NO RAISE BUTTON FOUND FOR ACTION: {action}")
                return False
            sizing_map = {
                'raise_third': pot_size / 3.0,
                'raise_half': pot_size / 2.0,
                'raise_pot': pot_size,
            }
            amount = sizing_map.get(action_lower, 0.0)
            print(
                f"DRY RUN - WOULD EXECUTE SIZED RAISE: action={action_lower} "
                f"amount={amount:.2f} raise_button={raise_coord} bet_input={BET_INPUT_COORD}"
            )
            # self.ghost.execute_sized_raise(BET_INPUT_COORD, amount, raise_coord)
            return True

        if action_lower in {'raise_allin', 'allin'}:
            target_coord = buttons.get('raise_allin') or buttons.get('raise')
            if not target_coord:
                print(f"DRY RUN - NO ALL-IN TARGET FOUND FOR ACTION: {action}")
                return False
            print(f"DRY RUN - WOULD CLICK ALL-IN ACTION: {target_coord}")
            # self.ghost.click(*target_coord)
            return True

        if action_lower in {'fold', 'call', 'check'}:
            target_coord = buttons.get(action_lower)
            if not target_coord:
                print(f"DRY RUN - NO BUTTON FOUND FOR ACTION: {action}")
                return False
            print(f"DRY RUN - WOULD CLICK {action_lower.upper()}: {target_coord}")
            # self.ghost.click(*target_coord)
            return True

        print(f"DRY RUN - NO HANDLER FOR ACTION: {action}")
        return False

    def run(self) -> None:
        try:
            self.root.mainloop()
        finally:
            self.running = False
            self.session_logger.close()


if __name__ == '__main__':
    engine = OverlayEngine()
    engine.run()