import random
import threading
import time
from typing import List, Optional

try:
    import pyautogui
except ImportError:
    raise ImportError('pyautogui is required for ghost.py')

class GhostArm:
    def __init__(self):
        self.arm_busy = threading.Lock()
        pyautogui.FAILSAFE = True
        self.min_delay = 0.06
        self.max_delay = 0.34
        self.move_variance = 4

    def _human_delay(self, base: float = 0.15) -> float:
        delay = random.gauss(base, base * 0.22)
        delay += random.uniform(-0.05, 0.05)
        delay = max(self.min_delay, min(delay, self.max_delay))
        return delay

    def _safe_pause(self, base: float = 0.12) -> None:
        time.sleep(self._human_delay(base))

    def click(self, x: int, y: int, button: str = 'left') -> bool:
        if not self.arm_busy.acquire(blocking=False):
            return False
        try:
            target_x = x + random.randint(-self.move_variance, self.move_variance)
            target_y = y + random.randint(-self.move_variance, self.move_variance)
            pyautogui.moveTo(target_x, target_y, duration=self._human_delay(0.11))
            self._safe_pause(0.08)
            pyautogui.click(x, y, button=button)
            self._safe_pause(0.10)
            return True
        except Exception:
            return False
        finally:
            self.arm_busy.release()

    def click_sequence(self, steps: List[dict]) -> bool:
        if not self.arm_busy.acquire(blocking=False):
            return False
        try:
            for step in steps:
                x = step.get('x')
                y = step.get('y')
                button = step.get('button', 'left')
                if x is None or y is None:
                    continue
                target_x = x + random.randint(-self.move_variance, self.move_variance)
                target_y = y + random.randint(-self.move_variance, self.move_variance)
                pyautogui.moveTo(target_x, target_y, duration=self._human_delay(0.12))
                self._safe_pause(0.08)
                pyautogui.click(x, y, button=button)
                self._safe_pause(0.12)
            return True
        except Exception:
            return False
        finally:
            self.arm_busy.release()

    def execute_move(self, x: int, y: int, delay: Optional[float] = None) -> bool:
        if delay is None:
            delay = self._human_delay(0.16)
        time.sleep(delay)
        return self.click(x, y)
