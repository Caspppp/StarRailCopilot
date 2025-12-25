"""
Navigation helpers for relic pages.

Keeping navigation in a standalone module makes it easy to dry-run UI
flows without touching recognition logic.
"""

from __future__ import annotations

import numpy as np

from module.base.button import ClickButton
from module.logger import logger
from tasks.relics.ui import RelicsUI
from tasks.relics.assets.assets_relics_ui import ENHANCE_FILTER, SALVAGE_FILTER, FILTER_CONFIRM

ENHANCE_STABLE_AREA = (843, 163, 918, 182)
FILTER_LIST_AREA = (245, 255, 1035, 495)
# 将滚动手势限定在右侧竖条区域，避免影响列表内容区域的识别
FILTER_SCROLL_STRIP = ClickButton(area=(1033, 262, 1104, 483), name='FILTER_SCROLL_STRIP')
FILTER_TAB_RELIC = ClickButton(area=(450, 183, 610, 221), name='FILTER_TAB_RELIC')
FILTER_TAB_ORNAMENT = ClickButton(area=(657, 183, 817, 221), name='FILTER_TAB_ORNAMENT')
ENHANCE_STABLE_TAP = ClickButton(area=ENHANCE_STABLE_AREA, name='ENHANCE_STABLE_TAP')
FILTER_LIST_CHECK = ClickButton(area=FILTER_LIST_AREA, name='FILTER_LIST_CHECK')
SLOT_BAR_AREA = (246, 85, 645, 117)
# 槽位顺序按实际 UI：头 -> 手 -> 衣服 -> 脚
SLOT_PARTS = ("head", "hands", "body", "feet")
ORNAMENT_BAR_AREA = (653, 86, 847, 116)
ORNAMENT_PARTS = ("sphere", "rope")

# Grid scrollbar (x1,y1,x2,y2). Adjust if UI skin changes slightly.
GRID_SCROLLBAR_ROI = (836, 131, 847, 617)


class RelicNavigator(RelicsUI):
    """Utility class to reach specific relic sub-pages and coordinate grid navigation."""

    FILTER_TABS = {
        "relic": FILTER_TAB_RELIC,
        "ornament": FILTER_TAB_ORNAMENT,
    }
    SLOT_INDEX = {name: idx for idx, name in enumerate(SLOT_PARTS)}
    ORNAMENT_INDEX = {name: idx for idx, name in enumerate(ORNAMENT_PARTS)}

    def __init__(self, config_name: str):
        super().__init__(config_name)
        self._last_drag_down: bool = False
        self._resume_after_item = None  # store GridItem to continue after actions

    def goto_enhance(self) -> None:
        """Ensure the relic enhance page is active."""
        logger.info("Navigator: goto relic enhance")
        self.ui_goto_relics()
        self.relics_goto_enhance()
        self._ensure_enhance_loaded()

    def goto_salvage(self) -> None:
        """Ensure the relic salvage page is active."""
        logger.info("Navigator: goto relic salvage")
        self.ui_goto_relics()
        self.relics_goto_salvage()
        self.wait_until_stable(SALVAGE_FILTER)

    def _ensure_enhance_loaded(self) -> None:
        """
        Tap the enhance filter icon to bring up the panel, then wait on a fixed
        rectangle so we only continue once the page UI has fully stabilized.
        """
        if not self.appear(ENHANCE_FILTER):
            logger.warning("ENHANCE_FILTER not found; skipping filter tap")
            return

        self.device.click(ENHANCE_FILTER)
        self.wait_until_stable(ENHANCE_STABLE_TAP)
        self.device.click(ENHANCE_STABLE_TAP)
        self.wait_until_stable(FILTER_LIST_CHECK)

    def select_filter_tab(self, tab: str) -> None:
        """Force the filter panel to a specific tab (e.g., relic or ornament)."""
        button = self.FILTER_TABS.get(tab)
        if button is None:
            raise ValueError(f"Unknown filter tab '{tab}'")
        logger.info("Switching filter tab to %s", tab)
        self.device.click(button)
        self.wait_until_stable(FILTER_LIST_AREA)

    # ---------------- Filter selection by set name ----------------
    def apply_filter_by_set_name(self, name: str, tab: str = "relic", *, max_pages: int = 12) -> bool:
        """Open enhance filter overlay, switch tab, select a set by name, confirm and return.

        Returns True on success.
        """
        import cv2
        from pathlib import Path
        from difflib import SequenceMatcher
        from .filter_reader import FilterPanelReader
        from module.base.button import ClickButton

        def fuzzy_match(a: str, b: str, threshold: float = 0.90) -> bool:
            try:
                return SequenceMatcher(None, (a or '').strip(), (b or '').strip()).ratio() >= threshold
            except Exception:
                return (a or '').strip() == (b or '').strip()

        try:
            self._ensure_enhance_loaded()
        except Exception:
            # Fallback: rely on current state
            pass
        try:
            self.select_filter_tab(tab)
        except Exception:
            pass

        # Prepare checkbox template
        tpl = None
        try:
            tpl_path = Path(__file__).parent / 'assets' / 'checkbox_empty.png'
            tpl = cv2.imread(str(tpl_path), cv2.IMREAD_GRAYSCALE)
        except Exception:
            tpl = None

        reader = FilterPanelReader(panel_area=FILTER_LIST_AREA, checkbox_template=tpl)

        for _ in range(max_pages):
            try:
                self.wait_until_stable(FILTER_LIST_AREA)
            except Exception:
                pass
            self.device.screenshot()
            rows = reader.extract_rows(self.device.image) if reader else []
            try:
                from module.logger import logger as _logger
                _logger.info("Filter rows detected: %s", len(rows))
                for r in rows[:8]:
                    _logger.info("Row OCR: '%s' (score=%.3f)", r.name, r.score)
            except Exception:
                pass
            # Prefer exact match then fuzzy
            target = None
            for r in rows:
                if r.name and r.name.strip() == name.strip():
                    target = r
                    break
            if target is None:
                for r in rows:
                    if r.name and fuzzy_match(r.name, name):
                        target = r
                        break
            if target is not None:
                self.device.click(ClickButton(area=target.checkbox, name=f'SELECT_{name}'))
                # Confirm with override template fallback
                confirmed = False
                try:
                    # Try override template first
                    ov_path = Path(__file__).parent / 'assets' / 'filter_confirm_override.png'
                    if ov_path.exists():
                        import numpy as np
                        from module.base.utils import crop as _crop
                        self.device.screenshot()
                        gray = cv2.cvtColor(self.device.image, cv2.COLOR_BGR2GRAY)
                        tpl_ov = cv2.imread(str(ov_path), cv2.IMREAD_GRAYSCALE)
                        if tpl_ov is not None:
                            res = cv2.matchTemplate(gray, tpl_ov, cv2.TM_CCOEFF_NORMED)
                            _, max_val, _, max_loc = cv2.minMaxLoc(res)
                            _logger.info("Confirm override match score %.3f", max_val)
                            if max_val >= 0.80:
                                click_x = max_loc[0] + tpl_ov.shape[1] // 2
                                click_y = max_loc[1] + tpl_ov.shape[0] // 2
                                self.device.click(ClickButton(area=(click_x - 5, click_y - 5, click_x + 5, click_y + 5), name='FILTER_CONFIRM_OVERRIDE'))
                                self.device.sleep(0.3)
                                confirmed = True
                except Exception:
                    pass
                if not confirmed:
                    try:
                        self.device.click(FILTER_CONFIRM)
                        self.device.sleep(0.3)
                        confirmed = True
                    except Exception:
                        confirmed = False
                # Additionally tap relics main tab to ensure closing overlay
                try:
                    from tasks.item.assets.assets_item_ui import RELICS_CLICK
                    self.device.click(RELICS_CLICK)
                except Exception:
                    pass
                # Wait back to grid
                from tools.relics_recognizer.grid import GRID_ROI as _GRID_ROI
                try:
                    self.wait_until_stable(_GRID_ROI)
                except Exception:
                    pass
                return True
            # Scroll next page
            if not self.right_panel_scroll_once(FILTER_SCROLL_STRIP.area, dy=-140):
                break
        return False

    # ---------------- Grid scrollbar helpers (no-swipe paging) ----------------
    def _get_scroll_thumb(self, image, roi: tuple) -> tuple:
        """Detect the scrollbar thumb within ROI.

        Returns (valid, y_top, y_bottom, track_top, track_bottom)
        """
        try:
            import cv2
            x1, y1, x2, y2 = roi
            crop = image[y1:y2, x1:x2]
            if crop.size == 0:
                return (False, 0, 0, y1, y2)
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            # Binary threshold; thumb is bright（放宽阈值以适配较暗皮肤）
            _, bin_ = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)
            # Sum over rows to find longest bright segment
            row_sum = bin_.sum(axis=1)  # shape (h,)
            h = row_sum.shape[0]
            max_len = 0
            best = (0, 0)
            run_len = 0
            run_start = 0
            for i in range(h):
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
                best = (run_start, h - 1)
            if max_len < 6:
                return (False, 0, 0, y1, y2)
            y_top = y1 + best[0]
            y_bottom = y1 + best[1]
            return (True, y_top, y_bottom, y1, y2)
        except Exception:
            return (False, 0, 0, roi[1], roi[3])

    def _grid_scroll_state(self) -> tuple:
        """Compute scroll state from thumb: (valid, y_norm, h_norm, total_rows, top_row)

        Uses your provided geometry: view 486px; row=112px; gap=12px; pad=18px; pitch=124px.
        """
        try:
            self.device.screenshot()
            valid, y_top, y_bot, t_top, t_bot = self._get_scroll_thumb(self.device.image, GRID_SCROLLBAR_ROI)
            if not valid:
                return (False, 0.0, 1.0, 0, 0)
            H_track = float(t_bot - t_top)
            h = float(y_bot - y_top + 1)
            y_norm = (y_top - t_top) / max(H_track - h, 1.0)
            h_norm = h / max(H_track, 1.0)
            # Geometry constants
            H_view = 486.0
            rh = 112.0
            gap = 12.0
            pad = 18.0
            pitch = rh + gap  # 124
            H_total = H_view / max(h_norm, 1e-3)
            # Solve rows: H_total = 2*pad + N*rh + (N-1)*gap = 2*pad + N*(rh+gap) - gap
            N_total = int(round((H_total - 2.0 * pad + gap) / pitch))
            scroll_max = max(H_total - H_view, 0.0)
            scroll_offset = y_norm * scroll_max
            k_top = int(round((scroll_offset - pad) / pitch))
            k_top = max(0, min(N_total - 1, k_top)) if N_total > 0 else 0
            try:
                from module.logger import logger as _logger
                _logger.info("Scrollbar state: y_norm=%.3f h_norm=%.3f rows=%s top=%s", y_norm, h_norm, N_total, k_top)
            except Exception:
                pass
            return (True, y_norm, h_norm, N_total, k_top)
        except Exception:
            return (False, 0.0, 1.0, 0, 0)

    def grid_is_at_bottom(self) -> bool:
        """Return True if scrollbar indicates bottom end."""
        ok, y_norm, h_norm, N_total, k_top = self._grid_scroll_state()
        if not ok:
            return False
        # Bottom by position
        if y_norm >= 0.98:
            return True
        # Or when top row already equals the last possible top (N-4)
        last_top = max(0, N_total - 4)
        return k_top >= last_top

    def grid_has_scrollbar(self) -> bool:
        """Return True if the grid shows a vertical scrollbar (single-page otherwise)."""
        try:
            self.device.screenshot()
            valid, *_ = self._get_scroll_thumb(self.device.image, GRID_SCROLLBAR_ROI)
            return bool(valid)
        except Exception:
            return False

    def grid_move_to_row(self, target_row: int) -> bool:
        """Move thumb to target top-row approximately.

        Returns True if movement likely occurred.
        """
        try:
            import cv2
            from module.base.button import ClickButton
            # Read initial
            ok, _, h_norm, N_total, k_top = self._grid_scroll_state()
            if not ok or N_total <= 0:
                return False
            target_row = max(0, min(N_total - 1, int(target_row)))
            if abs(target_row - k_top) < 1:
                return False
            # Compute target
            H_view = 486.0
            rh = 112.0
            gap = 12.0
            pad = 18.0
            pitch = rh + gap
            H_total = H_view / max(h_norm, 1e-3)
            scroll_max = max(H_total - H_view, 0.0)
            target_offset = max(0.0, min(scroll_max, pad + target_row * pitch))
            s_target = target_offset / max(scroll_max, 1e-3)
            # Measure thumb to get current center/height
            self.device.screenshot()
            valid, y_top, y_bot, t_top, t_bot = self._get_scroll_thumb(self.device.image, GRID_SCROLLBAR_ROI)
            if not valid:
                return False
            H_track = float(t_bot - t_top)
            h = float(y_bot - y_top + 1)
            y_target_top = t_top + s_target * (H_track - h)
            # Drag thumb center to target center
            x1, y1, x2, y2 = GRID_SCROLLBAR_ROI
            cx = (x1 + x2) // 2
            cy_now = int((y_top + y_bot) / 2)
            cy_target = int(y_target_top + h / 2.0)
            self.device.drag((cx, cy_now), (cx, cy_target), name="GRID_SCROLLBAR_DRAG", swipe_duration=0.45)
            # Friction to cancel inertia
            self.device.long_click(ClickButton(area=(cx - 3, cy_target - 3, cx + 3, cy_target + 3), name="GRID_SCROLLBAR_FRICTION"), duration=0.5)
            try:
                from tools.relics_recognizer.grid import GRID_ROI as _GRID_ROI
                self.wait_until_stable(_GRID_ROI)
            except Exception:
                pass
            # Verify
            ok2, _, _, _, k2 = self._grid_scroll_state()
            return bool(ok2 and (k2 != k_top))
        except Exception:
            return False

    def grid_page_down_by_thumb(self, rows: int = 4) -> bool:
        ok, _, _, N_total, k_top = self._grid_scroll_state()
        if not ok or N_total <= 0:
            return False
        target = min(N_total - 1, k_top + max(1, int(rows)))
        moved = self.grid_move_to_row(target)
        return moved

    def click_slot_button(
        self,
        slot: str,
        *,
        max_attempts: int = 2,
        diff_threshold: float = 4.0,
    ) -> bool:
        """Click relic part buttons (head/hands/feet/body)."""
        return self._click_segment_button(
            slot,
            area=SLOT_BAR_AREA,
            parts=SLOT_PARTS,
            index_map=self.SLOT_INDEX,
            label="slot",
            max_attempts=max_attempts,
            diff_threshold=diff_threshold,
        )

    def click_trinket_button(
        self,
        slot: str,
        *,
        max_attempts: int = 2,
        diff_threshold: float = 4.0,
    ) -> bool:
        """Click ornament part buttons (sphere/rope)."""
        return self._click_segment_button(
            slot,
            area=ORNAMENT_BAR_AREA,
            parts=ORNAMENT_PARTS,
            index_map=self.ORNAMENT_INDEX,
            label="trinket",
            max_attempts=max_attempts,
            diff_threshold=diff_threshold,
        )

    def select_part(self, slot: str) -> bool:
        """
        选择遗器或位面饰品部位

        Args:
            slot: 部位名称
                - 遗器: 'head', 'hands', 'body', 'feet'
                - 位面饰品: 'sphere', 'rope'

        Returns:
            bool: 选择成功返回 True，失败返回 False

        Raises:
            ValueError: 如果 slot 不是有效的部位名称
        """
        if slot in self.SLOT_INDEX:
            # 遗器部位
            return self.click_slot_button(slot)
        elif slot in self.ORNAMENT_INDEX:
            # 位面饰品部位
            return self.click_trinket_button(slot)
        else:
            valid_slots = list(self.SLOT_INDEX.keys()) + list(self.ORNAMENT_INDEX.keys())
            raise ValueError(
                f"Unknown part '{slot}'. Expected one of {valid_slots}"
            )

    # ---------------- Grid navigation helpers (resume after scroll) ----------------
    def plan_targets(self, snapshot, items):
        """Given a grid snapshot and a list of items (already sorted top->bottom,
        left->right), return an ordered list starting from the next row after
        the current highlight when resuming after a downward drag.

        If no highlight exists or last drag was not downward, return items.
        """
        # Reduce verbosity: plan targets debug only
        try:
            sel_desc = None
            if snapshot and getattr(snapshot, "selected", None):
                sel_desc = (snapshot.selected.row, snapshot.selected.col)
            ra_desc = None if self._resume_after_item is None else (self._resume_after_item.row, self._resume_after_item.col)
            logger.debug("PlanTargets: last_drag_down=%s selected=%s resume_after=%s items=%s", self._last_drag_down, sel_desc, ra_desc, len(items))
        except Exception:
            pass
        # 记录本次选中位置，用于下次拖动后的锚点校验
        if snapshot and getattr(snapshot, "selected", None):
            try:
                self._last_selected_center = snapshot.selected.center
            except Exception:
                self._last_selected_center = None

        if self._last_drag_down and snapshot and getattr(snapshot, "selected", None):
            # 若拖动后高亮与拖动前的高亮位置偏差过大，说明是“翻页到新区域”，不应从下一行开始，直接从顶部开始
            try:
                prev_center = getattr(self, "_last_selected_center", None)
                curr_center = snapshot.selected.center
                if prev_center and curr_center:
                    dx = curr_center[0] - prev_center[0]
                    dy = curr_center[1] - prev_center[1]
                    dist2 = dx * dx + dy * dy
                    # 阈值：像素距离 > 60 视为“不是同一锚点”
                    if dist2 > 60 * 60:
                        return items
            except Exception:
                pass

            base_row = snapshot.selected.row
            base_col = snapshot.selected.col
            # 基于“当前白框”为锚点，从其“下一件”开始（同一行优先右侧，其次后续行）
            filtered = [
                it
                for it in items
                if (it.row > base_row) or (it.row == base_row and it.col > base_col)
            ]
            try:
                if filtered:
                    n0 = filtered[0]
                    logger.debug("PlanTargets: start next-of-selected -> (%s,%s)", n0.row, n0.col)
            except Exception:
                pass
            return filtered if filtered else items
        # 若存在“从当前项的下一件继续”的指示，则应用并清空
        if self._resume_after_item is not None:
            ra = self._resume_after_item
            self._resume_after_item = None
            nxt = [it for it in items if (it.row > ra.row) or (it.row == ra.row and it.col > ra.col)] or items
            try:
                if nxt:
                    n0 = nxt[0]
                    logger.debug("PlanTargets: resume (%s,%s) -> start (%s,%s)", ra.row, ra.col, n0.row, n0.col)
            except Exception:
                pass
            # 若没有“下一件”，返回 items 但移除当前选中项，避免重复点击选中格
            if nxt:
                return nxt
            if getattr(snapshot, "selected", None):
                s = snapshot.selected
                return [it for it in items if not (it.row == s.row and it.col == s.col)]
            return items

        # Default: no special anchor logic, return given items order
        return items

    def drag_grid_with_anchor(self, detector, delta: int = -320) -> bool:
        """Drag the grid and try to keep a highlight anchor, with end-of-scroll check.

        - Negative delta drags upward (view moves down, revealing lower rows)
        - After drag, if no highlight is detected, perform a small opposite nudge
        - Returns True if the grid content changed (not at end), False if unchanged
        """
        from tools.relics_recognizer.grid import GRID_ROI
        x1, y1, x2, y2 = GRID_ROI
        mid_x = (x1 + x2) // 2
        start_y = y2 - 60
        end_y = start_y + delta
        # Snapshot before drag: collect quantized centers of plus boxes as signature
        try:
            self.wait_until_stable(GRID_ROI)
        except Exception:
            pass
        self.device.screenshot()
        try:
            base_snap = detector.detect(self.device.image)
            base_sig = self._grid_signature(base_snap)
        except Exception:
            base_sig = None
        self.device.drag((mid_x, start_y), (mid_x, end_y), name="GRID_DRAG", swipe_duration=0.65)
        self.device.sleep(0.5)
        self._last_drag_down = (delta < 0)
        try:
            self.device.screenshot()
            snap = detector.detect(self.device.image)
            if not snap.highlight:
                nudge = 80 if delta < 0 else -80
                end_y2 = end_y + nudge
                self.device.drag((mid_x, end_y), (mid_x, end_y2), name="GRID_NUDGE", swipe_duration=0.4)
                self.device.sleep(0.4)
            # Ensure grid settles before proceeding
            try:
                from tools.relics_recognizer.grid import GRID_ROI as _GRID_ROI
                self.wait_until_stable(_GRID_ROI)
            except Exception:
                pass
            # Snapshot after drag: compare signature
            self.device.screenshot()
            after_snap = detector.detect(self.device.image)
            after_sig = self._grid_signature(after_snap)
            moved = True
            if base_sig is not None and after_sig is not None:
                moved = (base_sig != after_sig)
                try:
                    from module.logger import logger as _logger
                    _logger.info("Grid move check: before=%s after=%s moved=%s", len(base_sig), len(after_sig), moved)
                except Exception:
                    pass
            return moved
        except Exception:
            return True

    def reset_drag_anchor(self) -> None:
        self._last_drag_down = False
        # 不清理 _resume_after_item，这个由 plan_targets 消费一次
        self._post_status_action = False

    def set_resume_after(self, item) -> None:
        """在本页规划目标前生效：从该 item 的下一件继续。"""
        self._resume_after_item = item

    @staticmethod
    def _grid_signature(snapshot) -> tuple:
        """Build a quantized signature of plus-box centers to detect movement.

        Returns a tuple of (qx, qy) sorted, where qx = x//4, qy = y//4 to suppress jitter.
        """
        try:
            items = getattr(snapshot, 'items', None) or []
            sig = []
            for it in items:
                px1, py1, px2, py2 = it.plus_box
                cx = (px1 + px2) // 2
                cy = (py1 + py2) // 2
                sig.append(((cx // 4), (cy // 4)))
            sig.sort(key=lambda t: (t[1], t[0]))
            return tuple(sig)
        except Exception:
            return tuple()

    # ----------------------- Level helpers (OCR) -----------------------
    def read_level_from_box(self, image, level_box: tuple, ocr_model) -> int | None:
        """OCR 读取等级数值（0..15）。

        - image: 当前截图
        - level_box: 绝对坐标 (x1,y1,x2,y2)
        - ocr_model: 提供 ocr_single_line(region) 的对象
        """
        try:
            from module.base.utils import crop as _crop
            region = _crop(image, level_box)
            if region is None or region.size == 0:
                return None
            text, _ = ocr_model.ocr_single_line(region)
            if not text:
                return None
            import re
            digits = re.findall(r"\d+", text)
            if not digits:
                return None
            val = int(digits[0])
            return max(0, min(15, val))
        except Exception:
            return None

    def filter_level_capped(self, image, items, ocr_model, *, cap: int = 15):
        """过滤已达 cap 级的格子，返回<cap 的列表。

        读取每个 item.level_box 做一次快速 OCR；失败则保留该项（避免误删）。
        """
        kept = []
        for it in items:
            lvl = self.read_level_from_box(image, it.level_box, ocr_model)
            if lvl is not None and lvl >= cap:
                continue
            kept.append(it)
        return kept

    # ----------------------- Grid ready / lifecycle flags -----------------------
    def ensure_grid_ready(self, detector, *, attempts: int = 3) -> bool:
        """确保回到遗器网格并稳定（不滚动）。"""
        from tools.relics_recognizer.grid import GRID_ROI as _GRID_ROI
        for _ in range(max(1, attempts)):
            try:
                # 关闭筛选面板等遮挡
                self.handle_filter_close()
            except Exception:
                pass
            try:
                self.wait_until_stable(_GRID_ROI)
            except Exception:
                self.device.sleep(0.3)
            self.device.screenshot()
            snap = detector.detect(self.device.image)
            if snap.items:
                return True
            # 导航回增强页左侧网格
            try:
                self.relics_goto_enhance(skip_first_screenshot=True)
            except Exception:
                pass
            self.device.sleep(0.4)
        return False

    def mark_post_status_action(self) -> None:
        self._post_status_action = True

    def consume_post_status_action(self) -> bool:
        flag = bool(getattr(self, "_post_status_action", False))
        self._post_status_action = False
        return flag

    # ----------------------- Right panel scroll helper -----------------------
    def right_panel_scroll_once(self, area: tuple, dy: int = -140) -> bool:
        """在给定区域内执行一次平滑滚动并抑制惯性，然后等待区域稳定。"""
        try:
            self.device.swipe_vector((0, dy), box=area, random_range=(0, 0, 0, 0), padding=20, duration=(0.9, 1.1), name="SET_LIST_SCROLL")
            # 长按中心以消惯性
            x1, y1, x2, y2 = area
            cx = (x1 + x2) // 2
            cy = (y1 + y2) // 2
            self.device.long_click(ClickButton(area=(cx - 6, cy - 6, cx + 6, cy + 6), name="SET_LIST_FRICTION"), duration=0.5)
            try:
                self.wait_until_stable(area)
            except Exception:
                pass
            return True
        except Exception as exc:
            logger.warning("Right panel scroll failed: %s", exc)
            return False

    # ----------------------- Re-anchor after screen shake -----------------------
    def reanchor_after_action(self, detector, expected=None, *, tolerance_px: int = 48, retries: int = 4):
        """在执行会引起抖动的点击（如弃置/上锁）后，重新确认高亮锚点。

        - 等待网格区域稳定
        - 若未检测到高亮，或高亮不在期望格子上，则尝试点击期望格子的小范围中心重选
        - 最多重试 retries 次；最终返回最新的 GridSnapshot
        """
        try:
            from tools.relics_recognizer.grid import GRID_ROI as _GRID_ROI
        except Exception:
            _GRID_ROI = None

        if _GRID_ROI is not None:
            try:
                self.wait_until_stable(_GRID_ROI)
            except Exception:
                pass
        self.device.screenshot()
        snap = detector.detect(self.device.image)
        # 若已有正确高亮，直接返回
        if expected and snap.selected:
            if snap.selected.row == expected.row and snap.selected.col == expected.col:
                return snap

        # 若无高亮或不在期望项上，先小等待/再次检测，仍不行则尝试重选
        wait_loops = 2
        for _ in range(wait_loops):
            if snap.selected and expected and snap.selected.row == expected.row and snap.selected.col == expected.col:
                return snap
            if _GRID_ROI is not None:
                try:
                    self.wait_until_stable(_GRID_ROI)
                except Exception:
                    pass
            self.device.sleep(0.2)
            self.device.screenshot()
            snap = detector.detect(self.device.image)

        if expected is not None:
            cx = (expected.plus_box[0] + expected.plus_box[2]) // 2
            cy = (expected.plus_box[1] + expected.plus_box[3]) // 2
            for i in range(retries):
                self.device.click(ClickButton(area=(cx - 8, cy - 8, cx + 8, cy + 8), name="REANCHOR_CLICK"))
                self.device.sleep(0.35)
                if _GRID_ROI is not None:
                    try:
                        self.wait_until_stable(_GRID_ROI)
                    except Exception:
                        pass
                self.device.screenshot()
                snap = detector.detect(self.device.image)
                if snap.selected and snap.selected.row == expected.row and snap.selected.col == expected.col:
                    return snap
        return snap

    # ----------------------- Status + reanchor helpers -----------------------
    def ensure_discarded_and_reanchor(self, status_controller, detector, expected_item=None, *, respect_expected: bool = False) -> bool:
        """Toggle discard ON and immediately re-anchor the current selection.

        - Calls status_controller.ensure_discarded(True)
        - Ensures grid is stable, then tries to re-select `expected_item`
        - Returns True if status toggled (by template/diff), regardless of reanchor result
        """
        ok = False
        try:
            # 强化失败的"目标性弃置"：先确保选中 expected，再执行弃置
            if respect_expected and expected_item is not None:
                try:
                    self.reanchor_after_action(detector, expected=expected_item)
                except Exception:
                    pass
            ok = bool(status_controller.ensure_discarded(True))
        finally:
            try:
                # 回到网格并稳定，再做一次高亮检测与重锚
                from tools.relics_recognizer.grid import GRID_ROI as _GRID_ROI
                try:
                    self.wait_until_stable(_GRID_ROI)
                except Exception:
                    pass
                # 弃置后页面可能发生位置跳变：以当前白框为准继续
                snap = self.reanchor_after_action(detector, expected=None)
                # 以“当前白框”为基准，从其下一件继续
                if snap and getattr(snap, "selected", None):
                    self.set_resume_after(snap.selected)
            except Exception:
                pass
            # 标记本轮已发生状态动作
            self.mark_post_status_action()
        return ok

    def ensure_locked_and_reanchor(self, status_controller, detector, expected_item=None, *, respect_expected: bool = False) -> bool:
        """Toggle lock ON and immediately re-anchor the current selection.

        See ensure_discarded_and_reanchor for details.
        """
        ok = False
        try:
            if respect_expected and expected_item is not None:
                try:
                    self.reanchor_after_action(detector, expected=expected_item)
                except Exception:
                    pass
            ok = bool(status_controller.ensure_locked(True))
        finally:
            try:
                from tools.relics_recognizer.grid import GRID_ROI as _GRID_ROI
                try:
                    self.wait_until_stable(_GRID_ROI)
                except Exception:
                    pass
                # 上锁后也不强制回到 expected，尊重当前白框，避免因轻微抖动重复点同一格
                snap = self.reanchor_after_action(detector, expected=None)
                if snap and getattr(snap, "selected", None):
                    self.set_resume_after(snap.selected)
            except Exception:
                pass
            self.mark_post_status_action()
        return ok

    # ------------------------- Click verify (base) -------------------------
    def click_slot_verified(self, detector, item, *, retries: int = 3) -> bool:
        """点击槽位并验证高亮或右侧面板是否切换。"""
        from tools.relics_recognizer.grid import GRID_ROI as _GRID_ROI
        try:
            self.wait_until_stable(_GRID_ROI)
        except Exception:
            pass
        center = ((item.plus_box[0] + item.plus_box[2]) // 2, (item.plus_box[1] + item.plus_box[3]) // 2)
        # 右侧信息面板区域（用于高亮缺失时的变化判定）
        info_roi = (880, 300, 1248, 500)
        try:
            self.device.screenshot()
            import cv2
            from module.base.utils import crop as _crop
            base_info = _crop(self.device.image, info_roi)
        except Exception:
            base_info = None
        for attempt in range(1, retries + 1):
            btn = ClickButton(area=(center[0] - 10, center[1] - 10, center[0] + 10, center[1] + 10), name=f"SLOT_{item.row}_{item.col}_TRY{attempt}")
            self.device.click(btn)
            self.device.sleep(0.45)
            self.device.screenshot()
            snap = detector.detect(self.device.image)
            sel = snap.selected
            if sel and sel.row == item.row and sel.col == item.col:
                return True
            # 面板变化判定（白框缺失兜底）
            if base_info is not None:
                try:
                    from module.base.utils import crop as _crop
                    import numpy as np
                    now = _crop(self.device.image, info_roi)
                    if now is not None and now.size and base_info.size and now.shape == base_info.shape:
                        diff = float(np.abs(now.astype(np.int16) - base_info.astype(np.int16)).mean())
                        if diff > 2.0:
                            # 若通过面板变化认定为已选中，但白框未识别，仍然将“从该项下一件继续”的意图记下
                            try:
                                self.set_resume_after(item)
                            except Exception:
                                pass
                            return True
                except Exception:
                    pass
            # 交替微偏移
            if attempt % 2 == 1:
                center = (center[0], max(center[1] - 14, _GRID_ROI[1] + 6))
            else:
                center = (center[0], min(center[1] + 12, _GRID_ROI[3] - 6))
        # 兜底：直接点加号矩形
        self.device.click(ClickButton(area=item.plus_box, name=f"SLOT_{item.row}_{item.col}_PLUS_FALLBACK"))
        self.device.sleep(0.5)
        self.device.screenshot()
        snap = detector.detect(self.device.image)
        sel = snap.selected
        return bool(sel and sel.row == item.row and sel.col == item.col)

    # --------------------- Filter discarded (base) ---------------------
    def filter_discarded_items(self, image, items, detector, *, threshold: float = 0.78):
        """从候选中移除右侧标记为弃置的格子（使用网格级探测）。"""
        kept = []
        for it in items:
            try:
                if detector.has_discard_mark(image, it, threshold=threshold):
                    continue
            except Exception:
                pass
            kept.append(it)
        return kept

    def filter_locked_items(self, image, items, detector, *, threshold: float = 0.78):
        """从候选中移除右侧标记为锁定的格子（使用网格级探测）。"""
        kept = []
        for it in items:
            try:
                if detector.has_lock_mark(image, it, threshold=threshold):
                    logger.info(f"跳过已锁定遗器: row={it.row} col={it.col}")
                    continue
            except Exception as e:
                logger.warning(f"锁定标记检测失败: {e}")
                pass
            kept.append(it)
        return kept

    def _click_segment_button(
        self,
        slot: str,
        *,
        area: tuple,
        parts: tuple,
        index_map: dict,
        label: str,
        max_attempts: int,
        diff_threshold: float,
    ) -> bool:
        slot_key = slot.lower()
        if slot_key not in index_map:
            raise ValueError(f"Unknown {label} '{slot}'. Expected one of {parts}")

        segment = self._segment_area(area, len(parts), index_map[slot_key])
        center_area = self._center_area(segment)
        self.wait_until_stable(segment)
        baseline = self.device.screenshot()

        for attempt in range(1, max_attempts + 1):
            logger.info("Clicking %s %s button (attempt %s)", slot_key, label, attempt)
            self.device.click(center_area)
            self.device.sleep(0.3)
            self.wait_until_stable(segment)
            updated = self.device.screenshot()
            diff = self._segment_diff(baseline, updated, segment)
            logger.info("%s %s highlight diff %.2f", label.capitalize(), slot_key, diff)
            if diff >= diff_threshold:
                return True
            baseline = updated
        logger.warning("Failed to verify highlight change for %s %s", label, slot_key)
        return False

    @staticmethod
    def _segment_area(area, part_count: int, index: int):
        x1, y1, x2, y2 = area
        width = x2 - x1
        step = width / part_count
        left = int(round(x1 + step * index))
        right = int(round(x1 + step * (index + 1)))
        return (left, y1, right, y2)

    @staticmethod
    def _center_area(area):
        x1, y1, x2, y2 = area
        cx = (x1 + x2) // 2
        cy = (y1 + y2) // 2
        padding = 8
        left = max(x1, cx - padding)
        right = min(x2, cx + padding)
        top = max(y1, cy - padding)
        bottom = min(y2, cy + padding)
        return ClickButton(area=(left, top, right, bottom), name="SLOT_CENTER_CLICK")

    @staticmethod
    def _segment_diff(before, after, area):
        x1, y1, x2, y2 = area
        crop_before = before[y1:y2, x1:x2]
        crop_after = after[y1:y2, x1:x2]
        if crop_before.size == 0 or crop_after.size == 0:
            return 0.0
        diff = np.abs(crop_after.astype(np.int16) - crop_before.astype(np.int16))
        return float(diff.mean())
