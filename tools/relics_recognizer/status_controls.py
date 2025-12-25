"""
Detect and toggle relic lock/discard state via template matching.

The icon panel is at (1207, 191) with size 32x78 (for 1280x720 layout).
Top area is the discard (trash) button; bottom area is the lock button.

Templates are expected under tools/relics_recognizer/assets/status:
    - trash_off.png (20x20), trash_on.png (20x20)
    - lock_off.png (20x20), lock_on.png (20x19)

All templates must exist under this directory; legacy fallback is removed.

We match both states per button and determine current state by the higher score.
Toggling is verified by re-detection and by mean-diff on the button area.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

import cv2
import numpy as np

from module.base.button import ClickButton
from module.logger import logger


Box = Tuple[int, int, int, int]

PANEL_X, PANEL_Y, PANEL_W, PANEL_H = 1207, 191, 32, 78
PANEL_AREA: Box = (PANEL_X, PANEL_Y, PANEL_X + PANEL_W, PANEL_Y + PANEL_H)

# Whole panel crop (32x78) where both buttons live
PANEL_RECT: Box = (PANEL_X, PANEL_Y, PANEL_X + PANEL_W, PANEL_Y + PANEL_H)

ASSET_DIR = (Path(__file__).parent / "assets" / "status").resolve()

# Toast overlay detection (黑框提示检测)
# 弃置/锁定后会显示半透明黑色提示框，需要等待其消失后再继续
TOAST_ROI: Box = (282, 138, 999, 179)
TOAST_BRIGHTNESS_THRESHOLD = 88  # 低于此值认为有黑框（有黑框时约51，无黑框时约125）


def _load_gray(path: Path) -> Optional[np.ndarray]:
    if not path.exists():
        logger.warning("Status template missing: %s", path)
        return None
    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        logger.warning("Failed to load status template: %s", path)
    return img


@dataclass
class MatchResult:
    state: Optional[str]
    score: float
    score_on: float
    score_off: float


class RelicStatusController:
    def __init__(self, device):
        self.device = device
        # Load templates strictly from the canonical assets directory
        self.tpl_trash_off = _load_gray(ASSET_DIR / "trash_off.png")
        self.tpl_trash_on = _load_gray(ASSET_DIR / "trash_on.png")
        self.tpl_lock_off = _load_gray(ASSET_DIR / "lock_off.png")
        self.tpl_lock_on = _load_gray(ASSET_DIR / "lock_on.png")
        # Cached last detected button rectangles (screen coords)
        self._trash_rect: Optional[Box] = None
        self._lock_rect: Optional[Box] = None

    # ----------------------------- Public detection -----------------------------
    def detect_discard(self, threshold: float = 0.75) -> MatchResult:
        area = self._locate_button("trash") or PANEL_RECT
        return self._detect_state(area, off=self.tpl_trash_off, on=self.tpl_trash_on, threshold=threshold)

    def detect_lock(self, threshold: float = 0.75) -> MatchResult:
        area = self._locate_button("lock") or PANEL_RECT
        return self._detect_state(area, off=self.tpl_lock_off, on=self.tpl_lock_on, threshold=threshold)

    def read_states(self) -> tuple[Optional[bool], Optional[bool]]:
        """Return (discard_on, lock_on) with None for unknown."""
        d = self.detect_discard(threshold=0.7)
        l = self.detect_lock(threshold=0.7)
        d_on = None if d.state is None else (d.state == "on")
        l_on = None if l.state is None else (l.state == "on")
        logger.info(
            "Status summary -> discard: %s (on=%.3f off=%.3f), lock: %s (on=%.3f off=%.3f)",
            d.state,
            d.score_on,
            d.score_off,
            l.state,
            l.score_on,
            l.score_off,
        )
        return d_on, l_on

    def get_button_rect(self, kind: str) -> Optional[Box]:
        """Public accessor for current button rectangle on screen.

        Will attempt to locate via template match if not cached.
        kind: 'trash' or 'lock'
        """
        return self._locate_button(kind)

    def is_discarded(self) -> Optional[bool]:
        res = self.detect_discard()
        if res.state is None:
            return None
        return res.state == "on"

    def is_locked(self) -> Optional[bool]:
        res = self.detect_lock()
        if res.state is None:
            return None
        return res.state == "on"

    # ------------------------------ Public togglers -----------------------------
    def ensure_discarded(self, target_on: bool, verify_diff: bool = True) -> bool:
        area = self._locate_button("trash") or PANEL_RECT
        return self._ensure_state(
            area,
            target_on,
            off=self.tpl_trash_off,
            on=self.tpl_trash_on,
            threshold=0.72,
        )

    def ensure_locked(self, target_on: bool, verify_diff: bool = True) -> bool:
        area = self._locate_button("lock") or PANEL_RECT
        return self._ensure_state(
            area,
            target_on,
            off=self.tpl_lock_off,
            on=self.tpl_lock_on,
            threshold=0.72,
        )

    # ------------------------------ Toast overlay detection ------------------------------
    def _has_toast_overlay(self, threshold: float = TOAST_BRIGHTNESS_THRESHOLD) -> bool:
        """检测是否有半透明黑框提示（弃置/锁定后的提示框）"""
        x1, y1, x2, y2 = TOAST_ROI
        crop = self.device.image[y1:y2, x1:x2]
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        mean_brightness = gray.mean()
        return mean_brightness < threshold

    def wait_for_toast_disappear(self, timeout: float = 2.0) -> bool:
        """等待黑框提示消失

        Args:
            timeout: 最大等待时间（秒）

        Returns:
            True 表示黑框已消失，False 表示超时
        """
        import time
        end_time = time.time() + timeout

        while time.time() < end_time:
            self.device.screenshot()
            if not self._has_toast_overlay():
                logger.debug("Toast overlay disappeared")
                return True
            time.sleep(0.1)

        logger.warning("Toast overlay did not disappear within %.1fs", timeout)
        return False

    # --------------------------------- Internals --------------------------------
    def _detect_state(
        self,
        area: Box,
        *,
        off: Optional[np.ndarray],
        on: Optional[np.ndarray],
        threshold: float,
    ) -> MatchResult:
        self.device.screenshot()
        img = self.device.image
        x1, y1, x2, y2 = map(int, area)
        crop = img[y1:y2, x1:x2]
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)

        def _score(tpl: Optional[np.ndarray]) -> float:
            if tpl is None or tpl.size == 0:
                return 0.0
            if gray.shape[0] < tpl.shape[0] or gray.shape[1] < tpl.shape[1]:
                return 0.0
            res = cv2.matchTemplate(gray, tpl, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(res)
            return float(max_val or 0.0)

        score_off = _score(off)
        score_on = _score(on)
        state: Optional[str]
        best = max(score_off, score_on)
        if best < threshold:
            state = None
        else:
            state = "on" if score_on >= score_off else "off"
        logger.debug(
            "Status detect @%s -> state=%s on=%.3f off=%.3f",
            (x1, y1, x2, y2),
            state,
            score_on,
            score_off,
        )
        return MatchResult(state=state, score=best, score_on=score_on, score_off=score_off)

    def _ensure_state(
        self,
        area: Box,
        target_on: bool,
        *,
        off: Optional[np.ndarray],
        on: Optional[np.ndarray],
        threshold: float = 0.72,
        diff_threshold: float = 2.0,
    ) -> bool:
        # Detect before with actual templates
        before = self._detect_state(area, off=off, on=on, threshold=threshold)
        state_before = before.state
        if state_before is not None and (state_before == "on") == target_on:
            return True

        # Capture pre-click crop
        self.device.screenshot()
        x1, y1, x2, y2 = map(int, area)
        pre = self.device.image[y1:y2, x1:x2].copy()

        # Click center
        cx = (area[0] + area[2]) // 2
        cy = (area[1] + area[3]) // 2
        self.device.click(ClickButton(area=(cx - 4, cy - 4, cx + 4, cy + 4), name="STATUS_TOGGLE"))
        self.device.sleep(0.28)

        # Verify by template detection
        after = self._detect_state(area, off=off, on=on, threshold=threshold)
        state_after = after.state
        if state_after is not None and (state_after == "on") == target_on:
            # 等待黑框提示消失（仅在设置弃置/锁定时）
            if target_on:
                self.wait_for_toast_disappear(timeout=2.0)
            return True

        # Fallback: mean-diff between pre and post crop
        try:
            self.device.screenshot()
            post = self.device.image[y1:y2, x1:x2]
            if pre.size and post.size and pre.shape == post.shape:
                diff = np.abs(pre.astype(np.int16) - post.astype(np.int16)).mean()
                logger.info("Status area mean-diff: %.2f", diff)
                if diff >= diff_threshold:
                    # 等待黑框提示消失（仅在设置弃置/锁定时）
                    if target_on:
                        self.wait_for_toast_disappear(timeout=2.0)
                    return True
        except Exception:
            pass
        return False

    # ------------------------------ Button location ------------------------------
    def _panel_gray(self):
        self.device.screenshot()
        img = self.device.image
        x1, y1, x2, y2 = PANEL_RECT
        crop = img[y1:y2, x1:x2]
        if crop.size == 0:
            return None, (x1, y1)
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        return gray, (x1, y1)

    def _match_in_panel(self, template: Optional[np.ndarray]):
        if template is None:
            return 0.0, None
        gray, origin = self._panel_gray()
        if gray is None or gray.shape[0] < template.shape[0] or gray.shape[1] < template.shape[1]:
            return 0.0, None
        res = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        x1 = origin[0] + max_loc[0]
        y1 = origin[1] + max_loc[1]
        h, w = template.shape[:2]
        rect = (x1, y1, x1 + w, y1 + h)
        return float(max_val or 0.0), rect

    def _locate_button(self, kind: str) -> Optional[Box]:
        if kind == "trash":
            s_on, r_on = self._match_in_panel(self.tpl_trash_on)
            s_off, r_off = self._match_in_panel(self.tpl_trash_off)
            best = (s_on, r_on) if s_on >= s_off else (s_off, r_off)
            rect = best[1]
            self._trash_rect = rect
            logger.debug("Locate trash button: on=%.3f off=%.3f rect=%s", s_on, s_off, rect)
            return rect
        if kind == "lock":
            s_on, r_on = self._match_in_panel(self.tpl_lock_on)
            s_off, r_off = self._match_in_panel(self.tpl_lock_off)
            best = (s_on, r_on) if s_on >= s_off else (s_off, r_off)
            rect = best[1]
            self._lock_rect = rect
            logger.debug("Locate lock button: on=%.3f off=%.3f rect=%s", s_on, s_off, rect)
            return rect
        return None
