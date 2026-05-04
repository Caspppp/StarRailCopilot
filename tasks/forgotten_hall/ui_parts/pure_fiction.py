import cv2
import numpy as np
import os
import re
import time
from dataclasses import dataclass

from module.base.timer import Timer
from module.base.utils import crop, save_image
from module.logger.logger import logger, logger_debug
from tasks.base.assets.assets_base_page import CLOSE, FORGOTTEN_HALL_CHECK, MAP_EXIT
from tasks.base.page import page_guide
from tasks.dungeon.keywords import DungeonList, KEYWORDS_DUNGEON_LIST
from tasks.forgotten_hall.assets.assets_forgotten_hall_nav import *
from tasks.forgotten_hall.assets.assets_forgotten_hall_ui import *
from tasks.forgotten_hall.assets.assets_pure_fiction_ui import (
    PURE_FICTION_CLEAR_ICON,
    PURE_FICTION_ENTER_STORY,
    PURE_FICTION_PRESET_ICON,
    PURE_FICTION_PRESET_TAB_SELECTED,
    PURE_FICTION_PRESET_TAB_UNSELECTED,
    PURE_FICTION_RETURN,
    PURE_FICTION_ROW1_EMPTY,
    PURE_FICTION_ROW2_EMPTY,
)
from tasks.forgotten_hall.assets.assets_stage_selection_ui import STAGE_REWARD_BUTTON_LOWER
from tasks.forgotten_hall.keywords import ForgottenHallStage, KEYWORDS_FORGOTTEN_HALL_STAGE
from tasks.forgotten_hall.stage_ocr import STAGE_LIST, detect_unlocked_text
from tasks.map.control.joystick import JoystickContact

class ForgottenHallPureFictionMixin:
    PURE_FICTION_DETECTION_AREA = (505, 187, 1214, 568)
    PURE_FICTION_STAGE_STAR_AREAS: dict[int, tuple[int, int, int, int]] = {
        1: (548, 420, 622, 444),
        2: (805, 225, 879, 249),
        3: (933, 540, 1007, 564),
        4: (1136, 353, 1211, 377),
    }
    PURE_FICTION_STAGE_LOCKED_TEXT_AREAS: dict[int, tuple[int, int, int, int]] = {
        2: (827, 224, 895, 253),
        3: (954, 539, 1022, 568),
        4: (1158, 353, 1226, 382),
    }
    PURE_FICTION_STAR_SEGMENTS = 3
    PURE_FICTION_STAR_MIN_PIXELS = 8
    PURE_FICTION_BUFF_OPTION_AREA = (543, 106, 1253, 633)
    PURE_FICTION_BUFF_OPTION_COUNT = 3
    PURE_FICTION_BUFF_RING_COL_RATIO = 0.28  # Search left part of option area for rings
    PURE_FICTION_BUFF_RING_HSV_LOWER = (10, 35, 120)
    PURE_FICTION_BUFF_RING_HSV_UPPER = (35, 255, 255)
    PURE_FICTION_BUFF_BORDER_BGR = (124, 122, 116)  # rgb(116,122,124)
    PURE_FICTION_BUFF_BORDER_TOLERANCE = 20
    PURE_FICTION_BUFF_SCROLLBAR_ROI = (1256, 116, 1261, 609)
    PURE_FICTION_BUFF_SELECTED_ROI = (251, 148, 304, 196)
    PURE_FICTION_BUFF_SELECTED_LUMA_WHITE = 70.0
    PURE_FICTION_BUFF_SELECTED_LUMA_DELTA = 20.0
    FORGOTTEN_HALL_CLICK_BLANK_PROMPT_ROI = (565, 620, 713, 642)
    FORGOTTEN_HALL_CLICK_BLANK_PROMPT_ROI_LUMA_MIN = 90.0
    FORGOTTEN_HALL_CLICK_BLANK_PROMPT_ROI_BRIGHT_THRESHOLD = 220
    FORGOTTEN_HALL_CLICK_BLANK_PROMPT_ROI_BRIGHT_RATIO_MIN = 0.05
    # Click an area that is outside the info panel (avoid clicking on the card itself).
    # Bottom-right corner is usually empty and avoids UI elements like UID/back buttons.
    FORGOTTEN_HALL_CLICK_BLANK_SAFE_AREA = (1200, 680, 1270, 720)

    @staticmethod
    def _area_center(area: tuple[int, int, int, int]) -> tuple[int, int]:
        x1, y1, x2, y2 = area
        return ((x1 + x2) // 2, (y1 + y2) // 2)

    @staticmethod
    def _point_in_area(point: tuple[int, int], area: tuple[int, int, int, int]) -> bool:
        x, y = point
        x1, y1, x2, y2 = area
        return x1 <= x <= x2 and y1 <= y <= y2

    @staticmethod
    def _split_area_horizontally(area: tuple[int, int, int, int], segments: int) -> list[tuple[int, int, int, int]]:
        x1, y1, x2, y2 = area
        if segments <= 0:
            return []

        total_w = x2 - x1
        base_w = total_w // segments
        remainder = total_w % segments

        areas: list[tuple[int, int, int, int]] = []
        cur_x = x1
        for i in range(segments):
            seg_w = base_w + (1 if i < remainder else 0)
            seg_x1 = cur_x
            seg_x2 = cur_x + seg_w
            areas.append((seg_x1, y1, seg_x2, y2))
            cur_x = seg_x2
        return areas

    @staticmethod
    def _split_area_vertically(area: tuple[int, int, int, int], segments: int) -> list[tuple[int, int, int, int]]:
        x1, y1, x2, y2 = area
        if segments <= 0:
            return []

        total_h = y2 - y1
        base_h = total_h // segments
        remainder = total_h % segments

        areas: list[tuple[int, int, int, int]] = []
        cur_y = y1
        for i in range(segments):
            seg_h = base_h + (1 if i < remainder else 0)
            seg_y1 = cur_y
            seg_y2 = cur_y + seg_h
            areas.append((x1, seg_y1, x2, seg_y2))
            cur_y = seg_y2
        return areas

    @dataclass(frozen=True)
    class _PureFictionCard:
        area: tuple[int, int, int, int]
        bottom_closed: bool

        @property
        def center(self) -> tuple[int, int]:
            x1, y1, x2, y2 = self.area
            return ((x1 + x2) // 2, (y1 + y2) // 2)

    @dataclass(frozen=True)
    class _LineCluster:
        start: int
        end: int

        @property
        def center(self) -> int:
            return (self.start + self.end) // 2

        @property
        def thickness(self) -> int:
            return self.end - self.start + 1

    @staticmethod
    def _scale_from_image(image: np.ndarray, base_w: int = 1280, base_h: int = 720) -> float:
        h, w = image.shape[:2]
        if w <= 0 or h <= 0:
            return 1.0
        return min(w / base_w, h / base_h)

    @staticmethod
    def _scale_area(area: tuple[int, int, int, int], scale: float) -> tuple[int, int, int, int]:
        if scale == 1.0:
            return area
        x1, y1, x2, y2 = area
        return (
            int(round(x1 * scale)),
            int(round(y1 * scale)),
            int(round(x2 * scale)),
            int(round(y2 * scale)),
        )

    @staticmethod
    def _chebyshev_color_mask(image_bgr: np.ndarray, target_bgr: tuple[int, int, int], tolerance: int) -> np.ndarray:
        target = np.array(target_bgr, dtype=np.int16)
        diff = np.abs(image_bgr.astype(np.int16) - target)
        dist = diff.max(axis=2)
        return (dist <= tolerance).astype(np.uint8) * 255

    def _pure_fiction_selected_luma(self, image: np.ndarray) -> float:
        scale = self._scale_from_image(image)
        x1, y1, x2, y2 = self._scale_area(self.PURE_FICTION_BUFF_SELECTED_ROI, scale)
        h, w = image.shape[:2]
        x1, y1, x2, y2 = max(0, x1), max(0, y1), min(w, x2), min(h, y2)
        if x2 <= x1 or y2 <= y1:
            return 0.0
        crop_img = image[y1:y2, x1:x2]
        gray = cv2.cvtColor(crop_img, cv2.COLOR_BGR2GRAY)
        return float(gray.mean())

    def _pure_fiction_is_buff_selected(self, image: np.ndarray, before_luma: float | None = None) -> bool:
        after_luma = self._pure_fiction_selected_luma(image)
        if after_luma >= self.PURE_FICTION_BUFF_SELECTED_LUMA_WHITE:
            return True
        if before_luma is None:
            return False
        return after_luma >= before_luma + self.PURE_FICTION_BUFF_SELECTED_LUMA_DELTA

    def _luma_mean(self, image: np.ndarray, area: tuple[int, int, int, int] | None = None) -> float:
        if not isinstance(image, np.ndarray) or image.size == 0:
            return 0.0
        if area is None:
            crop_img = image
        else:
            x1, y1, x2, y2 = area
            h, w = image.shape[:2]
            x1, y1, x2, y2 = max(0, x1), max(0, y1), min(w, x2), min(h, y2)
            if x2 <= x1 or y2 <= y1:
                return 0.0
            crop_img = image[y1:y2, x1:x2]
        gray = cv2.cvtColor(crop_img, cv2.COLOR_BGR2GRAY)
        return float(gray.mean())

    def _has_forgotten_hall_click_blank_prompt(self, image: np.ndarray) -> bool:
        scale = self._scale_from_image(image)
        roi = self._scale_area(self.FORGOTTEN_HALL_CLICK_BLANK_PROMPT_ROI, scale)
        x1, y1, x2, y2 = roi
        h, w = image.shape[:2]
        x1, y1, x2, y2 = max(0, x1), max(0, y1), min(w, x2), min(h, y2)
        if x2 <= x1 or y2 <= y1:
            return False

        crop_img = image[y1:y2, x1:x2]
        gray = cv2.cvtColor(crop_img, cv2.COLOR_BGR2GRAY)
        roi_luma = float(gray.mean())
        bright_ratio = float((gray >= self.FORGOTTEN_HALL_CLICK_BLANK_PROMPT_ROI_BRIGHT_THRESHOLD).mean())
        return (
            roi_luma >= self.FORGOTTEN_HALL_CLICK_BLANK_PROMPT_ROI_LUMA_MIN
            and bright_ratio >= self.FORGOTTEN_HALL_CLICK_BLANK_PROMPT_ROI_BRIGHT_RATIO_MIN
        )

    def _handle_forgotten_hall_click_blank_prompt(self, interval: float = 0.8) -> bool:
        from module.base.button import ClickButton

        interval_key = "FORGOTTEN_HALL_CLICK_BLANK_PROMPT"
        if interval and not self.interval_is_reached(interval_key, interval=interval):
            return False

        image = getattr(self.device, "image", None)
        if not isinstance(image, np.ndarray) or image.size == 0:
            return False

        if not self._has_forgotten_hall_click_blank_prompt(image):
            return False

        scale = self._scale_from_image(image)
        blank_area = self._scale_area(self.FORGOTTEN_HALL_CLICK_BLANK_SAFE_AREA, scale)
        blank = ClickButton(area=blank_area, name="FORGOTTEN_HALL_CLICK_BLANK_PROMPT")
        logger.info("[ForgottenHall] Click blank to dismiss prompt")
        self.device.click(blank)

        if interval:
            self.interval_reset(interval_key, interval=interval)
        return True

    @classmethod
    def _find_clusters_1d(cls, indices: np.ndarray) -> list["_LineCluster"]:
        if indices.size == 0:
            return []
        indices = np.asarray(indices, dtype=np.int32)
        clusters: list[ForgottenHallPureFictionMixin._LineCluster] = []
        start = int(indices[0])
        prev = int(indices[0])
        for v in indices[1:]:
            v = int(v)
            if v == prev + 1:
                prev = v
                continue
            clusters.append(cls._LineCluster(start=start, end=prev))
            start = v
            prev = v
        clusters.append(cls._LineCluster(start=start, end=prev))
        return clusters

    def _detect_pure_fiction_buff_cards(self, image: np.ndarray) -> list["_PureFictionCard"]:
        """
        Detect buff option card rectangles using the grey border lines.

        Returns:
            list[_PureFictionCard]: Sorted by y from top to bottom.
        """
        scale = self._scale_from_image(image)
        x1, y1, x2, y2 = self.PURE_FICTION_BUFF_OPTION_AREA
        h, w = image.shape[:2]
        x1, y1, x2, y2 = max(0, x1), max(0, y1), min(w, x2), min(h, y2)
        if x2 <= x1 or y2 <= y1:
            return []

        crop_img = image[y1:y2, x1:x2]
        mask = self._chebyshev_color_mask(
            crop_img,
            target_bgr=self.PURE_FICTION_BUFF_BORDER_BGR,
            tolerance=self.PURE_FICTION_BUFF_BORDER_TOLERANCE,
        )

        k3 = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k3, iterations=1)

        horizontal_kernel_len = max(80, int(round(220 * scale)))
        vertical_kernel_len = max(60, int(round(120 * scale)))

        h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (horizontal_kernel_len, 1))
        v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, vertical_kernel_len))
        h_lines = cv2.morphologyEx(mask, cv2.MORPH_OPEN, h_kernel, iterations=1)
        v_lines = cv2.morphologyEx(mask, cv2.MORPH_OPEN, v_kernel, iterations=1)

        crop_h, crop_w = h_lines.shape[:2]
        row_counts = np.count_nonzero(h_lines, axis=1)
        rows = np.where(row_counts >= int(crop_w * 0.60))[0]
        horizontal_clusters = sorted(self._find_clusters_1d(rows), key=lambda c: c.center)

        col_counts = np.count_nonzero(v_lines, axis=0)
        cols = np.where(col_counts >= int(crop_h * 0.25))[0]
        vertical_clusters = sorted(self._find_clusters_1d(cols), key=lambda c: c.center)

        if len(horizontal_clusters) < 3:
            return []

        # Derive 3 card y ranges from horizontal lines.
        pair_gap_max = max(24, int(round(50 * scale)))
        expected_cards = self.PURE_FICTION_BUFF_OPTION_COUNT

        tops: list[int] = [horizontal_clusters[0].center]
        bottoms: list[int] = []
        i = 1
        while i < len(horizontal_clusters) and len(bottoms) < expected_cards:
            bottoms.append(horizontal_clusters[i].center)

            if len(tops) >= expected_cards:
                i += 1
                continue

            if i + 1 < len(horizontal_clusters) and (horizontal_clusters[i + 1].center - horizontal_clusters[i].center) <= pair_gap_max:
                tops.append(horizontal_clusters[i + 1].center)
                i += 2
            else:
                i += 1

        if len(tops) != expected_cards:
            return []

        left = 0
        right = crop_w - 1
        if len(vertical_clusters) >= 2:
            left = min(vertical_clusters[0].center, vertical_clusters[-1].center)
            right = max(vertical_clusters[0].center, vertical_clusters[-1].center)
            left = min(max(0, left + 2), crop_w - 1)
            right = min(max(0, right - 2), crop_w - 1)

        cards: list[ForgottenHallPureFictionMixin._PureFictionCard] = []
        for idx in range(expected_cards):
            top = tops[idx]
            if idx < len(bottoms):
                bottom = bottoms[idx]
                bottom_closed = True
            else:
                bottom = crop_h - 1
                bottom_closed = False

            if bottom <= top:
                return []

            area = (x1 + left, y1 + top, x1 + right, y1 + bottom)
            cards.append(self._PureFictionCard(area=area, bottom_closed=bottom_closed))

        cards.sort(key=lambda c: c.center[1])
        return cards

    def _detect_pure_fiction_buff_rings(self, image: np.ndarray) -> list[tuple[int, int, int]]:
        """
        Detect yellow rings (icon circles) for buff options.

        Returns:
            list[(x, y, r)]: Ring circles in global coordinates, sorted by y.
        """
        scale = self._scale_from_image(image)
        x1, y1, x2, y2 = self.PURE_FICTION_BUFF_OPTION_AREA
        h, w = image.shape[:2]
        x1, y1, x2, y2 = max(0, x1), max(0, y1), min(w, x2), min(h, y2)
        if x2 <= x1 or y2 <= y1:
            return []

        ring_col_w = int(round((x2 - x1) * self.PURE_FICTION_BUFF_RING_COL_RATIO))
        ring_x1 = x1
        ring_x2 = min(x2, x1 + max(120, ring_col_w))
        padding = max(12, int(round(24 * scale)))
        ring_x1 = max(0, ring_x1 - padding)
        ring_y1 = max(0, y1 - padding)
        ring_x2 = min(w, ring_x2 + padding)
        ring_y2 = min(h, y2 + padding)

        if ring_x2 <= ring_x1 or ring_y2 <= ring_y1:
            return []

        crop_img = image[ring_y1:ring_y2, ring_x1:ring_x2]
        hsv = cv2.cvtColor(crop_img, cv2.COLOR_BGR2HSV)
        lower = np.array(self.PURE_FICTION_BUFF_RING_HSV_LOWER, dtype=np.uint8)
        upper = np.array(self.PURE_FICTION_BUFF_RING_HSV_UPPER, dtype=np.uint8)
        mask = cv2.inRange(hsv, lower, upper)

        # Mild close/dilate to bridge anti-alias gaps but avoid breaking thin rings.
        k3 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        k5 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k5, iterations=1)
        mask = cv2.dilate(mask, k3, iterations=1)

        blurred = cv2.GaussianBlur(mask, (7, 7), 0)
        min_radius = max(8, int(round(22 * scale)))
        max_radius = max(min_radius + 2, int(round(40 * scale)))
        min_dist = max(16, int(round(90 * scale)))

        circles = cv2.HoughCircles(
            blurred,
            cv2.HOUGH_GRADIENT,
            dp=1.2,
            minDist=min_dist,
            param1=120,
            param2=14,
            minRadius=min_radius,
            maxRadius=max_radius,
        )

        detected: list[tuple[int, int, int]] = []
        if circles is not None and len(circles) > 0:
            circles = np.asarray(np.around(circles), dtype=np.int32).squeeze(0)
            for cx, cy, r in circles:
                detected.append((int(ring_x1 + cx), int(ring_y1 + cy), int(r)))

        detected.sort(key=lambda t: t[1])
        return detected

    def _get_pure_fiction_buff_scroll_thumb(self, image) -> tuple[bool, int, int, int, int]:
        """
        检测虚构叙事 Buff 选择面板的滚动条滑块位置。

        Returns:
            (valid, y_top, y_bottom, track_top, track_bottom)
        """
        x1, y1, x2, y2 = self.PURE_FICTION_BUFF_SCROLLBAR_ROI
        crop_img = image[y1:y2, x1:x2]
        if crop_img.size == 0:
            return (False, 0, 0, y1, y2)

        gray = cv2.cvtColor(crop_img, cv2.COLOR_BGR2GRAY)
        _, bin_img = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)

        row_sum = bin_img.sum(axis=1)
        height = row_sum.shape[0]

        max_len = 0
        best = (0, 0)
        run_len = 0
        run_start = 0
        for i in range(height):
            if row_sum[i] > 0:
                if run_len == 0:
                    run_start = i
                run_len += 1
            else:
                if run_len > max_len:
                    max_len = run_len
                    best = (run_start, i - 1)
                run_len = 0

        if run_len > max_len:
            max_len = run_len
            best = (run_start, height - 1)

        if max_len < 6:
            return (False, 0, 0, y1, y2)

        y_top = y1 + best[0]
        y_bottom = y1 + best[1]
        return (True, y_top, y_bottom, y1, y2)

    def _drag_pure_fiction_buff_scroll_to_bottom(self, timeout: float = 2.0) -> bool:
        """
        当 buff 卡片超出可见范围时，将滚动条拖动到最底部。

        Returns:
            bool: 是否执行了拖动（有滚动条才会拖动）
        """
        self.device.screenshot()
        valid, y_top, y_bot, t_top, t_bot = self._get_pure_fiction_buff_scroll_thumb(self.device.image)
        x1, y1, x2, y2 = self.PURE_FICTION_BUFF_SCROLLBAR_ROI
        cx = (x1 + x2) // 2

        if not valid:
            # 若未能检测到滑块，仍尝试在轨道区域做一次拖动（兼容极端皮肤/亮度差异）
            logger.warning('[PureFiction] No scrollbar thumb detected, try fallback drag')
            self.device.drag((cx, y1 + 8), (cx, y2 - 8), name='PURE_FICTION_BUFF_SCROLL_FALLBACK')
            return True

        thumb_h = float(y_bot - y_top + 1)
        cy_now = int((y_top + y_bot) / 2)
        cy_target = int(t_bot - thumb_h / 2.0 - 2)
        cy_target = max(t_top + 2, min(t_bot - 2, cy_target))

        logger.info(f'[PureFiction] Drag buff scrollbar to bottom: {cy_now} -> {cy_target}')
        self.device.drag((cx, cy_now), (cx, cy_target), name='PURE_FICTION_BUFF_SCROLL_TO_BOTTOM')

        stable_timer = Timer(timeout).start()
        last_pos = None
        stable_count = 0
        while not stable_timer.reached():
            self.device.screenshot()
            valid_now, y_top_now, y_bot_now, _, _ = self._get_pure_fiction_buff_scroll_thumb(self.device.image)
            if not valid_now:
                continue
            pos = (y_top_now, y_bot_now)
            if pos == last_pos:
                stable_count += 1
                if stable_count >= 2:
                    break
            else:
                stable_count = 0
                last_pos = pos

        return True

    @staticmethod
    def _pure_fiction_split_keywords(value) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return []
            parts = [p.strip() for p in re.split(r"[|,，;；]+", text) if p.strip()]
            return parts if parts else [text]
        if isinstance(value, list):
            return [str(v).strip() for v in value if str(v).strip()]
        return [str(value).strip()] if str(value).strip() else []

    def _pure_fiction_ocr_text(self, image: np.ndarray, area: tuple[int, int, int, int]) -> str:
        from module.ocr.models import OCR_MODEL
        from module.ocr.utils import merge_buttons
        from module.base.utils import corner2area
        import module.config.server as server

        x1, y1, x2, y2 = area
        h, w = image.shape[:2]
        x1 = max(0, min(w, x1))
        x2 = max(0, min(w, x2))
        y1 = max(0, min(h, y1))
        y2 = max(0, min(h, y2))
        if x2 <= x1 or y2 <= y1:
            return ""

        crop_img = image[y1:y2, x1:x2]
        try:
            model = OCR_MODEL.get_by_lang(server.lang)
            results = model.detect_and_ocr(crop_img)
        except Exception as e:
            logger.warning(f'[PureFiction] OCR failed: {e}')
            return ""
        for result in results:
            result.box = tuple(corner2area(result.box))
        results = merge_buttons(results, thres_x=20, thres_y=20)
        results.sort(key=lambda r: (r.box[1], r.box[0]))
        return "\n".join([r.ocr_text for r in results]).strip()

    def _select_pure_fiction_buff_option_by_keyword(self, keyword) -> bool:
        """
        在 Buff 三选一面板中，根据 OCR 文本关键字选择对应 Buff。

        Args:
            keyword: str | list[str]

        Returns:
            bool: 是否已点击一个 Buff 选项
        """
        keywords = self._pure_fiction_split_keywords(keyword)
        if not keywords:
            logger.info('[PureFiction] No keyword provided, fallback to random selection')
            return self._select_pure_fiction_buff_option(1)

        self.device.screenshot()
        image = self.device.image

        cards = self._detect_pure_fiction_buff_cards(image)
        if len(cards) == self.PURE_FICTION_BUFF_OPTION_COUNT and any(not c.bottom_closed for c in cards):
            self._drag_pure_fiction_buff_scroll_to_bottom()
            self.device.screenshot()
            image = self.device.image
            cards = self._detect_pure_fiction_buff_cards(image)

        rings = self._detect_pure_fiction_buff_rings(image)
        scale = self._scale_from_image(image)
        click_radius = max(6, int(round(6 * scale)))
        click_dx = max(40, int(round(120 * scale)))

        candidates: list[tuple[int, tuple[int, int, int, int], str]] = []
        if len(cards) == self.PURE_FICTION_BUFF_OPTION_COUNT:
            for idx, card in enumerate(sorted(cards, key=lambda c: c.center[1]), start=1):
                card_x1, card_y1, card_x2, card_y2 = card.area
                ring_in_card = [r for r in rings if card_x1 <= r[0] <= card_x2 and card_y1 <= r[1] <= card_y2]

                pad_x = max(6, int(round(12 * scale)))
                pad_y = max(6, int(round(10 * scale)))
                if len(ring_in_card) == 1:
                    ring_x, ring_y, ring_r = ring_in_card[0]
                    ocr_x1 = ring_x + ring_r + max(10, int(round(16 * scale)))
                    click_x = min(card_x2 - click_radius, max(card_x1 + click_radius, ring_x + click_dx))
                    click_y = min(card_y2 - click_radius, max(card_y1 + click_radius, ring_y))
                else:
                    # Fallback: exclude left ~25% area
                    ocr_x1 = card_x1 + int(round((card_x2 - card_x1) * 0.25))
                    click_x, click_y = card.center

                ocr_area = (
                    int(min(card_x2 - pad_x, max(card_x1 + pad_x, ocr_x1))),
                    int(card_y1 + pad_y),
                    int(card_x2 - pad_x),
                    int(card_y2 - pad_y),
                )
                text = self._pure_fiction_ocr_text(image, ocr_area)
                click_area = (
                    int(click_x - click_radius),
                    int(click_y - click_radius),
                    int(click_x + click_radius),
                    int(click_y + click_radius),
                )
                candidates.append((idx, click_area, text))
        else:
            # Fallback: fixed split (may be less robust when card heights change)
            raw_areas = self._split_area_vertically(self.PURE_FICTION_BUFF_OPTION_AREA, self.PURE_FICTION_BUFF_OPTION_COUNT)
            for idx, (ax1, ay1, ax2, ay2) in enumerate(raw_areas, start=1):
                pad_x = max(6, int(round(12 * scale)))
                pad_y = max(6, int(round(10 * scale)))
                ocr_x1 = ax1 + int(round((ax2 - ax1) * 0.25))
                ocr_area = (ocr_x1, ay1 + pad_y, ax2 - pad_x, ay2 - pad_y)
                text = self._pure_fiction_ocr_text(image, ocr_area)
                cx, cy = self._area_center((ax1, ay1, ax2, ay2))
                click_area = (cx - click_radius, cy - click_radius, cx + click_radius, cy + click_radius)
                candidates.append((idx, click_area, text))

        normalized_candidates: list[tuple[int, str]] = []
        for idx, _, text in candidates:
            normalized_candidates.append((idx, re.sub(r"\\s+", "", text)))
            logger.attr(f'[PureFiction] Buff option #{idx} OCR', text=text)

        chosen_idx = 1
        if keywords:
            normalized_keywords = [re.sub(r"\\s+", "", k) for k in keywords if k.strip()]
            for idx, text in normalized_candidates:
                if any(k and k in text for k in normalized_keywords):
                    chosen_idx = idx
                    break

        from module.base.button import ClickButton

        click_area = None
        for idx, area, _ in candidates:
            if idx == chosen_idx:
                click_area = area
                break
        if click_area is None:
            return False

        click_button = ClickButton(area=click_area, name=f'PureFictionBuffKw_{chosen_idx}')
        logger.info(f'[PureFiction] Select buff option {chosen_idx} by keyword')
        self.device.click(click_button)
        return True

    def _get_pure_fiction_buff_option_areas(self) -> dict[int, tuple[int, int, int, int]]:
        """
        Get clickable areas for the 3 buff options.

        Prefer dynamic detection using rectangle borders + ring validation. Fallback to the
        legacy fixed split when detection fails.
        """
        image = getattr(self.device, "image", None)
        if isinstance(image, np.ndarray) and image.size > 0:
            cards = self._detect_pure_fiction_buff_cards(image)
            if len(cards) == self.PURE_FICTION_BUFF_OPTION_COUNT:
                if any(not c.bottom_closed for c in cards):
                    self._drag_pure_fiction_buff_scroll_to_bottom()
                    self.device.screenshot()
                    image = self.device.image
                    cards = self._detect_pure_fiction_buff_cards(image)
                    if len(cards) != self.PURE_FICTION_BUFF_OPTION_COUNT:
                        cards = []

                rings = self._detect_pure_fiction_buff_rings(image)
                scale = self._scale_from_image(image)
                click_radius = max(6, int(round(6 * scale)))
                click_dx = max(40, int(round(120 * scale)))

                areas: dict[int, tuple[int, int, int, int]] = {}
                for idx, card in enumerate(sorted(cards, key=lambda c: c.center[1]), start=1):
                    card_x1, card_y1, card_x2, card_y2 = card.area
                    ring_in_card = [r for r in rings if card_x1 <= r[0] <= card_x2 and card_y1 <= r[1] <= card_y2]
                    if len(ring_in_card) == 1:
                        ring_x, ring_y, _ = ring_in_card[0]
                        click_x = min(card_x2 - click_radius, max(card_x1 + click_radius, ring_x + click_dx))
                        click_y = min(card_y2 - click_radius, max(card_y1 + click_radius, ring_y))
                    else:
                        # Fallback: click the card center if ring validation fails.
                        click_x, click_y = card.center

                    areas[idx] = (
                        int(click_x - click_radius),
                        int(click_y - click_radius),
                        int(click_x + click_radius),
                        int(click_y + click_radius),
                    )

                if any(not c.bottom_closed for c in cards):
                    logger.debug('[PureFiction] Buff options may require scroll (missing bottom border)')

                if len(areas) == self.PURE_FICTION_BUFF_OPTION_COUNT:
                    return areas

        # Legacy fallback: fixed split
        raw_areas = self._split_area_vertically(
            self.PURE_FICTION_BUFF_OPTION_AREA,
            self.PURE_FICTION_BUFF_OPTION_COUNT,
        )
        padded: dict[int, tuple[int, int, int, int]] = {}
        for idx, (x1, y1, x2, y2) in enumerate(raw_areas, start=1):
            pad_x = min(16, max(0, (x2 - x1) // 10))
            pad_y = min(16, max(0, (y2 - y1) // 10))
            padded[idx] = (x1 + pad_x, y1 + pad_y, x2 - pad_x, y2 - pad_y)
        return padded

    @staticmethod
    def _count_star_segments(mask: np.ndarray, segments: int, min_pixels: int) -> int:
        if mask.size == 0 or segments <= 0:
            return 0

        height, width = mask.shape[:2]
        if width <= 0 or height <= 0:
            return 0

        seg_w = max(1, width // segments)
        count = 0
        for idx in range(segments):
            seg_x1 = idx * seg_w
            seg_x2 = width if idx == segments - 1 else min(width, (idx + 1) * seg_w)
            if cv2.countNonZero(mask[:, seg_x1:seg_x2]) >= min_pixels:
                count += 1

        return min(count, segments)

    def pure_fiction_scan_stage_stars(self, image=None) -> dict[int, int]:
        """
        扫描虚构叙事（Pure Fiction）固定页面的四关黄星数量。

        仅在给定区域内检测黄星，并按每关固定星星区域统计。
        固定星位时不做连通域过滤，直接分三段统计黄星像素。
        """
        if image is None:
            self.device.screenshot()
            image = self.device.image

        lower_yellow = np.array([239, 184, 97], dtype=np.uint8)
        upper_yellow = np.array([255, 214, 127], dtype=np.uint8)

        x1, y1, x2, y2 = self.PURE_FICTION_DETECTION_AREA
        h, w = image.shape[:2]
        x1 = max(0, x1)
        y1 = max(0, y1)
        x2 = min(w, x2)
        y2 = min(h, y2)

        if x2 <= x1 or y2 <= y1:
            logger.warning('[PureFiction] Invalid detection area, falling back to 0 stars')
            return {stage_num: 0 for stage_num in self.PURE_FICTION_STAGE_STAR_AREAS}

        crop_img = image[y1:y2, x1:x2]
        yellow_mask = cv2.inRange(crop_img, lower_yellow, upper_yellow)
        stage_stars: dict[int, int] = {}

        for stage_num, area in self.PURE_FICTION_STAGE_STAR_AREAS.items():
            ax1, ay1, ax2, ay2 = area
            rx1 = max(0, ax1 - x1)
            ry1 = max(0, ay1 - y1)
            rx2 = min(yellow_mask.shape[1], ax2 - x1)
            ry2 = min(yellow_mask.shape[0], ay2 - y1)

            if rx2 <= rx1 or ry2 <= ry1:
                stage_stars[stage_num] = 0
                continue

            area_mask = yellow_mask[ry1:ry2, rx1:rx2]
            count = self._count_star_segments(
                area_mask,
                self.PURE_FICTION_STAR_SEGMENTS,
                self.PURE_FICTION_STAR_MIN_PIXELS,
            )
            stage_stars[stage_num] = count

        logger.info(f'[PureFiction] Stage stars: {stage_stars}')
        return stage_stars

    def pure_fiction_detect_locked_stages(self, image=None) -> set[int]:
        """
        检测虚构叙事各关卡是否显示“未解锁”（固定坐标）。

        Returns:
            set[int]: 被检测为锁定的关卡编号集合（2-4）
        """
        from module.ocr.models import TextSystem

        if image is None:
            self.device.screenshot()
            image = self.device.image

        ocr_model = TextSystem('zhs')
        locked: set[int] = set()
        for stage_num, area in self.PURE_FICTION_STAGE_LOCKED_TEXT_AREAS.items():
            if detect_unlocked_text(
                image,
                area,
                ocr_model=ocr_model,
                save_debug=logger_debug,
                debug_index=stage_num,
            ):
                locked.add(stage_num)

        if locked:
            logger.info(f'[PureFiction] Locked stages: {sorted(locked)}')
        return locked

    def pure_fiction_resolve_stage_num(self, prefer_stage_num: int, image=None) -> int:
        """
        从 prefer_stage_num 开始向下回退，返回当前可挑战的最高关卡编号（4→3→2→1）。
        """
        prefer_stage_num = int(prefer_stage_num)
        prefer_stage_num = min(max(prefer_stage_num, 1), 4)

        locked = self.pure_fiction_detect_locked_stages(image=image)
        for stage_num in range(prefer_stage_num, 1, -1):
            if stage_num not in locked:
                return stage_num
        return 1

    def pure_fiction_next_stage_to_challenge(self, image=None) -> tuple[int, dict[int, int]]:
        """
        选择虚构叙事下一关要挑战的关卡。

        规则（最高可挑战难度）：
        - 优先挑战第4关；若检测到“未解锁”，则回退到第3关
        - 依次类推回退到第2关/第1关
        """
        if image is None:
            self.device.screenshot()
            image = self.device.image

        stage_stars = self.pure_fiction_scan_stage_stars(image=image)
        locked = self.pure_fiction_detect_locked_stages(image=image)
        for stage_num in locked:
            stage_stars[stage_num] = -1

        if stage_stars.get(4, 0) > 0:
            return -1, stage_stars

        stage_num = self.pure_fiction_resolve_stage_num(4, image=image)
        return stage_num, stage_stars

    def pure_fiction_get_stage_star_count(self, stage_num: int, image=None) -> int:
        stage_stars = self.pure_fiction_scan_stage_stars(image=image)
        return stage_stars.get(stage_num, 0)

    def pure_fiction_select_stage(self, stage_num: int, skip_first_screenshot=True, timeout: float = 8.0) -> bool:
        """
        在虚构叙事固定页面点击指定关卡。

        当前使用每关星星区域中心点作为点击坐标，并等待页面稳定标识（如“进入故事”按钮）。
        """
        from module.base.button import ClickButton

        if stage_num not in self.PURE_FICTION_STAGE_STAR_AREAS:
            logger.error(f'[PureFiction] Invalid stage: {stage_num}')
            return False

        x, y = self._area_center(self.PURE_FICTION_STAGE_STAR_AREAS[stage_num])
        click_button = ClickButton(
            area=(x - 4, y - 4, x + 4, y + 4),
            name=f'PureFictionStage_{stage_num}',
        )

        for attempt in range(1, 4):
            logger.info(f'[PureFiction] Select stage {stage_num} (attempt {attempt}/3)')

            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.handle_forgotten_hall_buff():
                continue

            self.device.click(click_button)

            wait = Timer(timeout).start()
            title_seen = False
            while not wait.reached():
                self.device.screenshot()
                if self.handle_forgotten_hall_buff():
                    continue
                if self.match_template_color(PURE_FICTION_ENTER_STORY, interval=0.2):
                    logger.info(f'[PureFiction] Stage {stage_num} selected (enter story detected)')
                    return True
                if self.appear(PURE_FICTION_TEAM_BUTTON, interval=0.2):
                    logger.info(f'[PureFiction] Stage {stage_num} selected (team button detected)')
                    return True
                if self.appear(PURE_FICTION_TEAM_TITLE, interval=0.2):
                    title_seen = True
                    continue

            if title_seen:
                logger.info(f'[PureFiction] Stage {stage_num} selected (title detected)')
                return True

        logger.error(f'[PureFiction] Failed to select stage {stage_num}')
        return False

    def _enter_pure_fiction_team_selection(self, skip_first_screenshot=True, timeout: float = 10.0) -> bool:
        """
        进入虚构叙事编队界面（点击“队伍”按钮），确保可见“预设编队/清除”图标。
        """
        from module.base.button import ClickButton

        logger.info('[PureFiction] Enter team selection')
        timer = Timer(timeout).start()
        interval = Timer(1.2)
        clicked_team_button = False

        # Avoid relying on template-match offsets for clicking: offsets may be updated even on failed matches.
        team_button_click = ClickButton(
            area=PURE_FICTION_TEAM_BUTTON.buttons[0]._button,
            name='PURE_FICTION_TEAM_BUTTON',
        )

        while not timer.reached():
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.handle_forgotten_hall_buff():
                continue

            if self._pure_fiction_team_selection_ready():
                if clicked_team_button:
                    logger.info('[PureFiction] Team selection ready')
                else:
                    logger.info('[PureFiction] Team selection already open')
                return True

            # Stage selection page is stable when "进入故事" is visible; at this point we must open team selection.
            if self.match_template_color(PURE_FICTION_ENTER_STORY, interval=0):
                if interval.reached():
                    logger.info('[PureFiction] Clicking team button')
                    self.device.click(team_button_click)
                    interval.reset()
                    clicked_team_button = True
                continue

            if self.appear(PURE_FICTION_TEAM_BUTTON, interval=0):
                if interval.reached():
                    logger.info('[PureFiction] Clicking team button')
                    self.device.click(team_button_click)
                    interval.reset()
                    clicked_team_button = True
                continue

            _ = self.appear(PURE_FICTION_TEAM_TITLE, interval=0)

        logger.warning('[PureFiction] Enter team selection timeout')
        return False

    def _pure_fiction_team_selection_ready(self) -> bool:
        """Return True only when the actual Pure Fiction team screen is loaded."""
        if not self.appear(PURE_FICTION_TEAM_TITLE, interval=0):
            return False

        return (
            self.appear(PURE_FICTION_PRESET_ICON, interval=0)
            or self.appear(PURE_FICTION_CLEAR_ICON, interval=0)
            or self.appear(PURE_FICTION_TEAM1_BUFF, interval=0)
            or self.appear(PURE_FICTION_TEAM2_BUFF, interval=0)
        )

    PURE_FICTION_TEAM_ROW_SELECT_AREAS = {
        # Row-number diamond areas (虚构叙事-编队) — used to set active row before applying preset teams.
        1: (520, 450, 590, 515),
        2: (520, 543, 590, 608),
    }

    def _click_pure_fiction_team_row(self, team_index: int) -> bool:
        """Select row 1/2 on Pure Fiction team screen."""
        from module.base.button import ClickButton

        area = self.PURE_FICTION_TEAM_ROW_SELECT_AREAS.get(team_index)
        if area is None:
            logger.error(f'[PureFiction] Invalid team index: {team_index}')
            return False

        self.device.click(ClickButton(area=area, name=f'PureFictionTeamRow_{team_index}'))
        return True

    PURE_FICTION_ROW_EMPTY_TEMPLATES = {
        1: PURE_FICTION_ROW1_EMPTY,
        2: PURE_FICTION_ROW2_EMPTY,
    }

    def _pure_fiction_row_is_empty(self, team_index: int) -> bool:
        button = self.PURE_FICTION_ROW_EMPTY_TEMPLATES.get(team_index)
        if button is None:
            return False
        return self.appear(button, interval=0, similarity=0.8)

    def _wait_for_pure_fiction_row_filled(
        self,
        team_index: int,
        skip_first_screenshot=True,
        timeout: float = 3.0,
    ) -> bool:
        timer = Timer(timeout).start()
        while not timer.reached():
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.handle_forgotten_hall_buff():
                continue

            if not self._pure_fiction_row_is_empty(team_index):
                logger.info(f'[PureFiction] Team {team_index} selection applied')
                return True

        logger.warning(f'[PureFiction] Team {team_index} still empty after selection')
        return False

    def _apply_pure_fiction_preset_team(self, team_index: int, preset_index: int) -> bool:
        for attempt in range(1, 3):
            logger.info(
                f'[PureFiction] Applying preset team {preset_index} to team {team_index} '
                f'(attempt {attempt}/2)'
            )
            self._click_pure_fiction_team_row(team_index)
            if not self._click_preset_team(skip_first_screenshot=True, timeout=15):
                logger.warning(
                    f'[PureFiction] Failed to open preset team panel for team {team_index}, retrying...'
                )
                continue
            if not self.select_preset_team(preset_index):
                logger.warning(
                    f'[PureFiction] Failed to select preset team for team {team_index}, retrying...'
                )
                continue

            if self._wait_for_pure_fiction_row_filled(team_index, skip_first_screenshot=True, timeout=3.0):
                return True

        return False

    def _click_pure_fiction_clear_team(self, team_index: int, skip_first_screenshot=True, timeout: float = 4.0) -> bool:
        """Click the trash icon to clear team selection and verify the given row becomes empty.

        Note: In current Pure Fiction UI, the trash icon may clear both upper/lower rows, so we
        do not rely on selecting the row before clearing.
        """
        if self._pure_fiction_row_is_empty(team_index):
            logger.info(f'[PureFiction] Team {team_index} already empty, skip clear')
            return True

        timer = Timer(timeout).start()
        clicked = False
        while not timer.reached():
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.handle_forgotten_hall_buff():
                continue

            # If cleared by other actions/animations, stop early.
            if self._pure_fiction_row_is_empty(team_index):
                logger.info(f'[PureFiction] Team {team_index} cleared')
                return True

            if not clicked and self.appear(PURE_FICTION_CLEAR_ICON, interval=0.2):
                self.device.click(PURE_FICTION_CLEAR_ICON)
                clicked = True
                continue

        if clicked:
            logger.warning(f'[PureFiction] Team {team_index} clear verification timeout')
        else:
            logger.warning('[PureFiction] Clear icon not found')
        return False

    def _configure_pure_fiction_preset_teams(self, team1_preset: int = None, team2_preset: int = None) -> bool:
        """Configure Pure Fiction preset teams (row 1 & row 2)."""
        return self._configure_preset_teams_flow(
            team1_preset=team1_preset,
            team2_preset=team2_preset,
            mode_label='PureFiction',
            team_label='team',
            verify_method='seat',
            ensure_entry=lambda: self._enter_pure_fiction_team_selection(timeout=12),
            clear_team=lambda team_index: self._click_pure_fiction_clear_team(
                team_index,
                skip_first_screenshot=True,
            ),
            apply_team=self._apply_pure_fiction_preset_team,
        )

    def _wait_for_pure_fiction_buff_panel(self, skip_first_screenshot=True, timeout: float = 6.0) -> bool:
        timer = Timer(timeout).start()
        while not timer.reached():
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(PURE_FICTION_BUFF_APPLY, interval=0.2):
                return True

        return False

    def _select_pure_fiction_buff_option(self, buff_index: int) -> bool:
        from module.base.button import ClickButton

        areas = self._get_pure_fiction_buff_option_areas()
        area = areas.get(buff_index)
        if area is None:
            logger.error(f'[PureFiction] Invalid buff index: {buff_index}')
            return False

        x, y = self._area_center(area)
        click_button = ClickButton(
            area=(x - 6, y - 6, x + 6, y + 6),
            name=f'PureFictionBuff_{buff_index}',
        )
        logger.info(f'[PureFiction] Select buff option {buff_index}')
        self.device.click(click_button)
        return True

    def _click_pure_fiction_buff_apply(self, skip_first_screenshot=True, timeout: float = 6.0) -> bool:
        timer = Timer(timeout).start()
        while not timer.reached():
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(PURE_FICTION_BUFF_APPLY, interval=0.2):
                logger.info('[PureFiction] Click buff apply')
                self.device.click(PURE_FICTION_BUFF_APPLY)
                return True

        logger.warning('[PureFiction] Buff apply button not found')
        return False

    def _exit_pure_fiction_buff_panel(self, skip_first_screenshot=True, timeout: float = 6.0) -> bool:
        logger.info('[PureFiction] Exit buff panel')
        timer = Timer(timeout).start()
        while not timer.reached():
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if not self.appear(PURE_FICTION_BUFF_APPLY, interval=0.2):
                return True

            self.device.click(CLOSE)

            if (self.appear(PURE_FICTION_TEAM1_BUFF, interval=0.2)
                    or self.appear(PURE_FICTION_TEAM2_BUFF, interval=0.2)
                    or self.appear(PRESET_TEAM, interval=0.2)):
                return True

        logger.warning('[PureFiction] Exit buff panel timeout')
        return False

    def _select_pure_fiction_team_buff(self, team_index: int, buff, timeout: float = 8.0) -> bool:
        if buff is None:
            return True

        if isinstance(buff, str):
            buff = buff.strip()
            if not buff:
                return True
            if buff.isdigit():
                buff = int(buff)
        elif isinstance(buff, list):
            buff = [str(v).strip() for v in buff if str(v).strip()]
            if not buff:
                return True

        if isinstance(buff, int) and buff <= 0:
            return True

        if team_index not in (1, 2):
            logger.error(f'[PureFiction] Invalid team index: {team_index}')
            return False

        if not self._enter_pure_fiction_team_selection(timeout=8.0):
            logger.warning('[PureFiction] Team selection not ready for buff selection')
            return False

        button = PURE_FICTION_TEAM1_BUFF if team_index == 1 else PURE_FICTION_TEAM2_BUFF
        logger.info(f'[PureFiction] Open buff panel for team {team_index}')

        panel_opened = False
        timer = Timer(timeout).start()
        interval = Timer(1.2)
        while not timer.reached():
            self.device.screenshot()

            if self.handle_forgotten_hall_buff():
                continue

            if self.appear(PURE_FICTION_BUFF_APPLY, interval=0.2):
                panel_opened = True
                break

            if self.appear(button, interval=0.2) and interval.reached():
                self.device.click(button)
                interval.reset()
                continue

        if not panel_opened:
            logger.warning(f'[PureFiction] Buff panel not opened for team {team_index}')
            return False

        selected_confirmed = False
        for attempt in range(1, 4):
            self.device.screenshot()
            before_luma = self._pure_fiction_selected_luma(self.device.image)

            if isinstance(buff, int):
                selected = self._select_pure_fiction_buff_option(buff)
            else:
                selected = self._select_pure_fiction_buff_option_by_keyword(buff)

            if not selected:
                continue

            timer = Timer(2.0).start()
            last_luma = None
            while not timer.reached():
                self.device.screenshot()
                last_luma = self._pure_fiction_selected_luma(self.device.image)
                if last_luma >= self.PURE_FICTION_BUFF_SELECTED_LUMA_WHITE or last_luma >= before_luma + self.PURE_FICTION_BUFF_SELECTED_LUMA_DELTA:
                    selected_confirmed = True
                    logger.debug(f'[PureFiction] Buff selected luma: {before_luma:.1f} -> {last_luma:.1f}')
                    break

            if selected_confirmed:
                break

            if last_luma is not None:
                logger.warning(
                    f'[PureFiction] Buff selection not confirmed (attempt {attempt}/3), '
                    f'luma: {before_luma:.1f} -> {last_luma:.1f}, retrying...'
                )
            else:
                logger.warning(f'[PureFiction] Buff selection not confirmed (attempt {attempt}/3), retrying...')

        if not selected_confirmed:
            logger.warning('[PureFiction] Buff selection failed after retries')
            self._exit_pure_fiction_buff_panel(skip_first_screenshot=False, timeout=6.0)
            return False

        if not self._click_pure_fiction_buff_apply(skip_first_screenshot=True, timeout=6.0):
            self._exit_pure_fiction_buff_panel(skip_first_screenshot=False, timeout=6.0)
            return False
        self._exit_pure_fiction_buff_panel()
        return True

    def _configure_pure_fiction_buffs(self, team1_buff: int | str | list[str] | None = None, team2_buff: int | str | list[str] | None = None) -> bool:
        success = True
        if team1_buff:
            if not self._select_pure_fiction_team_buff(team_index=1, buff=team1_buff):
                success = False
        if team2_buff:
            if not self._select_pure_fiction_team_buff(team_index=2, buff=team2_buff):
                success = False
        return success
