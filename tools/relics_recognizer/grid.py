"""
Grid-level helpers: detect relic slots via the + icon and mark which slot is
currently highlighted (white outline).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import cv2
import numpy as np

from module.logger import logger

Box = Tuple[int, int, int, int]
Point = Tuple[int, int]

ASSETS_DIR = (Path(__file__).parent / "assets").resolve()
PLUS_TEMPLATE = ASSETS_DIR / "plus_symbol.png"
STATUS_DIR = ASSETS_DIR / "status"
TRASH_ON_TEMPLATE = STATUS_DIR / "trash_on.png"
LOCK_ON_TEMPLATE = STATUS_DIR / "lock_on.png"

GRID_ROI = (150, 145, 770, 625)  # (x1, y1, x2, y2) slightly extended bottom to include lower-row ring
HIGHLIGHT_S_MAX = 60
HIGHLIGHT_V_MIN = 215
HIGHLIGHT_MIN_AREA = 160
HIGHLIGHT_MAX_AREA = 6000
HIGHLIGHT_MIN_SIZE = 34
HIGHLIGHT_MAX_SIZE = 150
HIGHLIGHT_ASPECT_RANGE = (0.75, 1.3)


@dataclass
class GridItem:
    index: int
    row: int
    col: int
    center: Point
    plus_box: Box
    level_box: Box


@dataclass
class HighlightBox:
    box: Box
    area: float
    mask_ratio: float
    center: Point


@dataclass
class GridSnapshot:
    items: List[GridItem]
    highlight: Optional[HighlightBox] = None
    selected: Optional[GridItem] = None


class RelicGridDetector:
    def __init__(
        self,
        *,
        roi: Box = GRID_ROI,
        plus_threshold: float = 0.8,
        highlight_kernel: Tuple[int, int] = (3, 3),
    ):
        self.roi = roi
        self.plus_threshold = plus_threshold
        self.kernel = cv2.getStructuringElement(cv2.MORPH_RECT, highlight_kernel)
        self.plus_template = cv2.imread(str(PLUS_TEMPLATE), cv2.IMREAD_GRAYSCALE)
        if self.plus_template is None:
            raise FileNotFoundError(f"Missing template: {PLUS_TEMPLATE}")
        self.template_w = self.plus_template.shape[1]
        self.template_h = self.plus_template.shape[0]
        # Optional discard mark template (trash_on) for per-slot skip
        try:
            self.trash_on_template = cv2.imread(str(TRASH_ON_TEMPLATE), cv2.IMREAD_GRAYSCALE)
            if self.trash_on_template is None:
                logger.warning("Missing discard template: %s", TRASH_ON_TEMPLATE)
        except Exception:
            self.trash_on_template = None
        # Optional lock mark template (lock_on) for per-slot skip
        try:
            self.lock_on_template = cv2.imread(str(LOCK_ON_TEMPLATE), cv2.IMREAD_GRAYSCALE)
            if self.lock_on_template is None:
                logger.warning("Missing lock template: %s", LOCK_ON_TEMPLATE)
        except Exception:
            self.lock_on_template = None
        # Debug caches for last detection
        self.last_mask = None  # kept for backward-compat (final pass mask)
        self.last_mask_base = None  # type: Optional[np.ndarray]
        self.last_mask_relaxed = None  # type: Optional[np.ndarray]
        self.last_highlight = None  # type: Optional[HighlightBox]
        self.last_contours = []  # type: list[tuple[Box, float]]  # (abs box, area)

    # Public API -------------------------------------------------------
    def detect(self, image) -> GridSnapshot:
        plus_boxes = self._detect_plus_boxes(image)
        items = self._build_grid_items(plus_boxes)
        # base pass
        highlight = self._detect_highlight(image, items, relaxed=False)
        # relaxed second pass if initial attempt fails (skin/brightness variations)
        if highlight is None:
            logger.info("Highlight: base pass none -> try relaxed")
            highlight = self._detect_highlight(image, items, relaxed=True)
        selected = self._match_highlight(highlight, items) if highlight else None
        if items:
            logger.info("RelicGridDetector: detected %s slots", len(items))
        else:
            logger.warning("RelicGridDetector: no + icons detected inside ROI")
        if selected:
            logger.info(
                "Current selection -> row=%s col=%s point=%s",
                selected.row,
                selected.col,
                selected.center,
            )
        elif highlight:
            logger.info("Highlight found at %s but no matching slot", highlight.box)
        else:
            logger.info("No highlight ring detected in ROI")
        return GridSnapshot(items=items, highlight=highlight, selected=selected)

    # Internal helpers -------------------------------------------------
    def _detect_plus_boxes(self, image) -> List[Box]:
        x1, y1, x2, y2 = self.roi
        crop = image[y1:y2, x1:x2]
        crop_gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        res = cv2.matchTemplate(crop_gray, self.plus_template, cv2.TM_CCOEFF_NORMED)
        loc = np.where(res >= self.plus_threshold)
        boxes: List[Box] = []
        for px, py in zip(*loc[::-1]):
            left = px + x1
            top = py + y1
            boxes.append((left, top, left + self.template_w, top + self.template_h))
        boxes = self._suppress_duplicates(boxes, radius=18)
        return boxes

    def _build_grid_items(self, boxes: Sequence[Box]) -> List[GridItem]:
        if not boxes:
            return []
        entries = []
        for box in boxes:
            cx = (box[0] + box[2]) // 2
            cy = (box[1] + box[3]) // 2
            entries.append((cy, cx, box))
        entries.sort()
        rows: List[Tuple[int, List[Tuple[int, int, Box]]]] = []
        for cy, cx, box in entries:
            for row in rows:
                if abs(row[0] - cy) <= 30:
                    row[1].append((cy, cx, box))
                    break
            else:
                rows.append((cy, [(cy, cx, box)]))
        rows.sort(key=lambda item: item[0])

        items: List[GridItem] = []
        index = 0
        for row_idx, (_, row_entries) in enumerate(rows):
            row_entries.sort(key=lambda entry: entry[1])
            for col_idx, (_, cx, box) in enumerate(row_entries):
                cy = (box[1] + box[3]) // 2
                items.append(
                    GridItem(
                        index=index,
                        row=row_idx,
                        col=col_idx,
                        center=(cx, cy),
                        plus_box=box,
                        level_box=self._build_level_box(box),
                    )
                )
                index += 1
        return items

    def _build_level_box(self, plus_box: Box) -> Box:
        px1, py1, px2, py2 = plus_box
        cy = (py1 + py2) // 2
        width = 26
        height = 18
        padding = 0
        x1, y1, x2, y2 = self.roi
        left = px2 + padding
        right = left + width
        if right > x2:
            right = x2
            left = right - width
        top = cy - height // 2
        bottom = top + height
        if bottom > y2:
            bottom = y2
            top = bottom - height
        if top < y1:
            top = y1
            bottom = top + height
        left = max(left, x1)
        right = min(right, x2)
        top = max(top, y1)
        bottom = min(bottom, y2)
        return (int(left), int(top), int(right), int(bottom))

    def _detect_highlight(self, image, items: Sequence[GridItem], relaxed: bool = False) -> Optional[HighlightBox]:
        if not items:
            return None
        x1, y1, x2, y2 = self.roi
        roi = image[y1:y2, x1:x2]
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        s_max = HIGHLIGHT_S_MAX if not relaxed else min(100, HIGHLIGHT_S_MAX + 40)
        v_min = HIGHLIGHT_V_MIN if not relaxed else max(180, HIGHLIGHT_V_MIN - 25)
        lower = (0, 0, v_min)
        upper = (180, s_max, 255)
        mask = cv2.inRange(hsv, lower, upper)
        iters = 1 if not relaxed else 2
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, self.kernel, iterations=iters)
        # cache mask for debug overlay（相对于 ROI 的二值图）
        try:
            if relaxed:
                self.last_mask_relaxed = mask.copy()
                self.last_mask = mask.copy()
            else:
                self.last_mask_base = mask.copy()
                self.last_mask = mask.copy()
        except Exception:
            self.last_mask = None

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        # mask stats for debugging
        try:
            nz = int(cv2.countNonZero(mask))
            total = int(mask.size)
            ratio = (nz / float(total)) if total else 0.0
            logger.debug(
                "Highlight pass(%s): S_max=%s V_min=%s iters=%s mask_nz=%s(%.3f)",
                "relaxed" if relaxed else "base",
                s_max,
                v_min,
                iters,
                nz,
                ratio,
            )
        except Exception:
            pass
        candidates: List[HighlightBox] = []
        # collect contour boxes for debug
        self.last_contours = []
        for cnt in contours:
            area = cv2.contourArea(cnt)
            # 移除面积限制（不再以 [HIGHLIGHT_MIN_AREA, HIGHLIGHT_MAX_AREA] 过滤）
            x, y, w, h = cv2.boundingRect(cnt)
            if not (HIGHLIGHT_MIN_SIZE <= w <= HIGHLIGHT_MAX_SIZE and HIGHLIGHT_MIN_SIZE <= h <= HIGHLIGHT_MAX_SIZE):
                continue
            aspect = w / max(h, 1)
            if not (HIGHLIGHT_ASPECT_RANGE[0] <= aspect <= HIGHLIGHT_ASPECT_RANGE[1]):
                continue
            region = mask[y : y + h, x : x + w]
            mask_ratio = float(region.sum()) / (255.0 * w * h)
            global_box = (x + x1, y + y1, x + x1 + w, y + y1 + h)
            center = (global_box[0] + w // 2, global_box[1] + h // 2)
            candidates.append(HighlightBox(box=global_box, area=float(area), mask_ratio=mask_ratio, center=center))
            try:
                self.last_contours.append((global_box, float(area)))
            except Exception:
                pass

        if not candidates:
            logger.debug("Highlight pass(%s): no valid contours", "relaxed" if relaxed else "base")
            self.last_highlight = None
            return None
        candidates.sort(key=lambda item: item.area, reverse=True)

        def contains_plus(candidate: HighlightBox) -> bool:
            hx1, hy1, hx2, hy2 = candidate.box
            # Allow a bit more slack so rounding/scroll jitter do not drop matches.
            slack = 8
            for item in items:
                cx, cy = item.center
                if hx1 - slack <= cx <= hx2 + slack and hy1 - slack <= cy <= hy2 + slack:
                    return True
            return False

        for candidate in candidates:
            if contains_plus(candidate):
                # store absolute highlight for debug
                self.last_highlight = candidate
                # Reduce verbosity: keep chosen highlight at debug level
                try:
                    bx1, by1, bx2, by2 = candidate.box
                    logger.debug(
                        "Highlight chosen(%s): box=%s area=%.1f mask_ratio=%.3f",
                        "relaxed" if relaxed else "base",
                        (bx1, by1, bx2, by2),
                        candidate.area,
                        candidate.mask_ratio,
                    )
                except Exception:
                    pass
                return candidate
        self.last_highlight = None
        return None

    def _match_highlight(self, highlight: HighlightBox, items: Sequence[GridItem]) -> Optional[GridItem]:
        if highlight is None:
            return None
        hx1, hy1, hx2, hy2 = highlight.box
        matches: List[Tuple[float, GridItem]] = []
        for item in items:
            cx, cy = item.center
            if hx1 <= cx <= hx2 and hy1 <= cy <= hy2:
                dist = (cx - highlight.center[0]) ** 2 + (cy - highlight.center[1]) ** 2
                matches.append((dist, item))
        if not matches:
            return None
        matches.sort(key=lambda entry: entry[0])
        return matches[0][1]

    @staticmethod
    def _suppress_duplicates(boxes: Sequence[Box], radius: int = 18) -> List[Box]:
        filtered: List[Box] = []
        centers: List[Point] = []
        for box in boxes:
            cx = (box[0] + box[2]) // 2
            cy = (box[1] + box[3]) // 2
            if any(abs(cx - px) <= radius and abs(cy - py) <= radius for px, py in centers):
                continue
            filtered.append(box)
            centers.append((cx, cy))
        return filtered

    # ------------------------ Per-slot discard mark ------------------------
    def has_discard_mark(self, image, item: GridItem, *, threshold: float = 0.78) -> bool:
        """Check if a slot has the discard mark in the 65x53 window to the right of the plus icon.

        The window's bottom aligns with the plus icon's bottom.
        Returns True if match score >= threshold.
        """
        tpl = getattr(self, "trash_on_template", None)
        if tpl is None:
            return False
        px1, py1, px2, py2 = item.plus_box
        win_w, win_h = 65, 53
        left = px2
        right = left + win_w
        bottom = py2
        top = bottom - win_h
        h_img, w_img = image.shape[:2]
        left = max(0, min(left, w_img))
        right = max(0, min(right, w_img))
        top = max(0, min(top, h_img))
        bottom = max(0, min(bottom, h_img))
        if right - left < 10 or bottom - top < 10:
            return False
        region = image[top:bottom, left:right]
        gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
        if gray.shape[0] < tpl.shape[0] or gray.shape[1] < tpl.shape[1]:
            return False
        res = cv2.matchTemplate(gray, tpl, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, _ = cv2.minMaxLoc(res)
        if max_val >= float(threshold):
            logger.info("Slot discard mark detected row=%s col=%s score=%.3f", item.row, item.col, max_val)
            return True
        return False

    def has_lock_mark(self, image, item: GridItem, *, threshold: float = 0.78) -> bool:
        """Check if a slot has the lock mark in the 65x53 window to the right of the plus icon.

        The window's bottom aligns with the plus icon's bottom.
        Returns True if match score >= threshold.
        """
        tpl = getattr(self, "lock_on_template", None)
        if tpl is None:
            return False
        px1, py1, px2, py2 = item.plus_box
        win_w, win_h = 65, 53
        left = px2
        right = left + win_w
        bottom = py2
        top = bottom - win_h
        h_img, w_img = image.shape[:2]
        left = max(0, min(left, w_img))
        right = max(0, min(right, w_img))
        top = max(0, min(top, h_img))
        bottom = max(0, min(bottom, h_img))
        if right - left < 10 or bottom - top < 10:
            return False
        region = image[top:bottom, left:right]
        gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
        if gray.shape[0] < tpl.shape[0] or gray.shape[1] < tpl.shape[1]:
            return False
        res = cv2.matchTemplate(gray, tpl, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, _ = cv2.minMaxLoc(res)
        if max_val >= float(threshold):
            logger.info("Slot lock mark detected row=%s col=%s score=%.3f", item.row, item.col, max_val)
            return True
        return False

    # ----------------------------- Debug helpers -----------------------------
    def get_last_mask(self) -> Optional[np.ndarray]:
        return self.last_mask

    def get_last_highlight(self) -> Optional[HighlightBox]:
        return self.last_highlight

    def get_last_masks(self) -> tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        return self.last_mask_base, self.last_mask_relaxed

    def get_last_contours(self) -> list:
        return self.last_contours
