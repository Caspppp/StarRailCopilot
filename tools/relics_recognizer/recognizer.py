"""
Relic recognizer helper that now focuses on reading the relic filter panel.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import cv2

from module.logger import logger

from .filter_reader import FilterPanelReader, FilterRow
from .grid import GridSnapshot, RelicGridDetector
from .models import RelicData
from .navigation import FILTER_LIST_AREA, FILTER_SCROLL_STRIP, RelicNavigator
from tasks.item.assets.assets_item_ui import RELICS_CLICK
from tasks.relics.assets.assets_relics_ui import ENHANCE_FILTER, FILTER_CONFIRM

ASSETS_DIR = (Path(__file__).parent / "assets").resolve()
BASELINE_FILE = ASSETS_DIR / "relic_order_baseline.json"
CONFIRM_OVERRIDE_FILE = ASSETS_DIR / "filter_confirm_override.png"
FILTER_SWIPE_BOX = (245, 260, 1035, 480)
FUZZY_MATCH_THRESHOLD = 0.9


class RelicRecognizer(RelicNavigator):
    def __init__(self, config_name: str, output_dir: Optional[Path] = None):
        super().__init__(config_name)
        self.lang = self.config.Emulator_GameLanguage or self.config.LANG or "cn"
        self.output_dir = Path(output_dir or Path("log") / "relics_recognizer")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.checkbox_reader = FilterPanelReader(
            panel_area=FILTER_LIST_AREA,
            checkbox_template=self._load_template("checkbox_empty.png"),
        )
        self.relic_order_baseline = self._load_order_baseline()
        self.confirm_override = self._load_override_template()
        self.grid_detector = RelicGridDetector()

    def scan(
        self,
        limit: Optional[int] = None,
        tab: str = "relic",
        target_name: Optional[str] = None,
        part_after_select: Optional[str] = None,
    ) -> List[RelicData]:
        """
        Scan the relic filter panel, OCR every row, and keep scrolling until all
        entries are collected (or `limit` names have been read).
        """
        logger.info("RelicRecognizer scan start (tab=%s, limit=%s)", tab, limit)
        self.goto_enhance()
        self.select_filter_tab(tab)
        initial_rows = self._capture_current_rows()
        if not initial_rows:
            logger.warning("Failed to capture any rows on the first page; aborting scan")
            return []

        mismatch = self._check_first_entry(initial_rows, tab)
        if mismatch:
            rows = self._read_filter_rows(limit_rows=limit, initial_rows=initial_rows)
        else:
            rows = initial_rows
            if target_name:
                self._select_target_name(
                    target_name,
                    initial_rows,
                    tab=tab,
                    part_after_select=part_after_select,
                )
        data = RelicData(slot=tab)
        data.raw_ocr["filter_rows"] = [row.to_serializable() for row in rows]
        return [data]

    # Internal helpers -------------------------------------------------
    def _read_filter_rows(
        self,
        *,
        limit_rows: Optional[int] = None,
        max_pages: int = 20,
        initial_rows: Optional[List[FilterRow]] = None,
    ) -> List[FilterRow]:
        collected: List[FilterRow] = []
        seen_names: set[str] = set()
        stagnant_pages = 0
        repeat_pages = 0
        last_page_names: Optional[Sequence[str]] = None

        page_idx = 0
        while page_idx < max_pages:
            if page_idx == 0 and initial_rows is not None:
                page_rows = initial_rows
            else:
                self.wait_until_stable(FILTER_LIST_AREA)
                image = self.device.screenshot()
                detected_rows = self.checkbox_reader.extract_rows(image)
                if not detected_rows:
                    logger.warning("No checkbox rows detected on page %s", page_idx)
                    break

                page_rows = self._order_rows(detected_rows)

            page_names = [row.name for row in page_rows]
            if last_page_names is not None and page_names == last_page_names:
                repeat_pages += 1
                logger.info("Filter panel repeated the same rows (%s)", repeat_pages)
            else:
                repeat_pages = 0
            last_page_names = page_names
            if repeat_pages >= 3:
                logger.info("Repeated the same page 3 times, aborting scan")
                break

            new_name_found = False
            for row in page_rows:
                normalized = row.name.strip() if row.name else ""
                if normalized and normalized not in seen_names:
                    seen_names.add(normalized)
                    new_name_found = True
                    collected.append(row)
                    logger.info("Filter row #%s: %s (score=%.2f)", len(collected), normalized, row.score)
                    if limit_rows and len(collected) >= limit_rows:
                        return collected

            if not new_name_found:
                stagnant_pages += 1
            else:
                stagnant_pages = 0

            if stagnant_pages >= 2:
                logger.info("No new relic names after two pages; aborting scan")
                break

            if not self._scroll_filter_panel():
                logger.info("Scroll failed; stop scanning")
                break

            page_idx += 1

        return collected

    def _capture_current_rows(self) -> List[FilterRow]:
        self.wait_until_stable(FILTER_LIST_AREA)
        image = self.device.screenshot()
        detected_rows = self.checkbox_reader.extract_rows(image)
        if not detected_rows:
            return []
        return self._order_rows(detected_rows)

    def _order_rows(self, rows: Sequence[FilterRow], row_tolerance: int = 25) -> List[FilterRow]:
        """Group rows by y so we enumerate them left→right within each row."""
        if not rows:
            return []
        sorted_rows = sorted(rows, key=lambda r: (r.checkbox[1], r.checkbox[0]))
        grouped: List[Tuple[int, List[FilterRow]]] = []
        for row in sorted_rows:
            y_center = (row.checkbox[1] + row.checkbox[3]) // 2
            for idx, (gy, bucket) in enumerate(grouped):
                if abs(gy - y_center) <= row_tolerance:
                    bucket.append(row)
                    break
            else:
                grouped.append((y_center, [row]))

        ordered: List[FilterRow] = []
        for _, bucket in sorted(grouped, key=lambda item: item[0]):
            bucket.sort(key=lambda r: r.checkbox[0])
            ordered.extend(bucket)
        return ordered

    def _scroll_filter_panel(self) -> bool:
        """
        Swipe within the filter panel scroll area. Returns False if swipe
        cannot be executed (e.g., MaaTouch not ready), True otherwise.
        """
        try:
            self.device.swipe_vector(
                (0, -140),
                box=FILTER_SWIPE_BOX,
                random_range=(0, 0, 0, 0),
                padding=20,
                duration=(0.9, 1.1),
                name="FILTER_SCROLL",
            )
            self.device.long_click(FILTER_SCROLL_STRIP, duration=0.5)
            self.wait_until_stable(FILTER_LIST_AREA)
            return True
        except Exception as exc:  # pragma: no cover - swipe may fail on misconfigured devices
            logger.warning("Failed to scroll relic filter panel: %s", exc)
            return False

    def capture_grid_snapshot(self) -> GridSnapshot:
        """
        Capture the relic grid (outside of the filter overlay) and detect the
        current highlight ring so we can keep track of the selected slot.
        """
        self.wait_until_stable(self.grid_detector.roi)
        image = self.device.screenshot()
        snapshot = self.grid_detector.detect(image)
        return snapshot

    def _check_first_entry(self, rows: Sequence[FilterRow], tab: str) -> bool:
        """Compare first detected relic with local baseline to detect new sets."""
        if not rows:
            logger.warning("No rows detected; skip baseline comparison")
            return False
        baseline = self.relic_order_baseline.get(self.lang, {})
        tab_config = baseline.get(tab)
        if not tab_config:
            logger.info("No relic order baseline for lang=%s tab=%s; skip comparison", self.lang, tab)
            return False
        expected = tab_config.get("first", "").strip()
        actual = rows[0].name.strip()
        if expected and actual and not self._is_fuzzy_match(actual, expected):
            logger.warning(
                "First relic does not match baseline (expected '%s', got '%s'). "
                "Dumping current order for review.",
                expected,
                actual,
            )
            self._dump_current_order(rows, reason="first_mismatch")
            return True
        return False

    def _dump_current_order(self, rows: Sequence[FilterRow], reason: str) -> None:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = self.output_dir / f"relic_order_{reason}_{timestamp}.json"
        payload = {
            "lang": self.lang,
            "reason": reason,
            "timestamp": timestamp,
            "names": [row.name for row in rows],
            "raw": [row.to_serializable() for row in rows],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        logger.info("Relic order dump saved to %s", path)

    def _load_order_baseline(self) -> dict:
        if not BASELINE_FILE.exists():
            logger.warning("Baseline file %s not found; relic order comparison disabled", BASELINE_FILE)
            return {}
        try:
            with open(BASELINE_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception as exc:  # pragma: no cover
            logger.warning("Failed to parse baseline file %s: %s", BASELINE_FILE, exc)
            return {}

        normalized: dict = {}
        for lang, info in raw.items():
            if "first" in info:
                normalized[lang] = {"relic": {"first": info["first"]}}
            else:
                normalized[lang] = info
        return normalized

    def _is_fuzzy_match(self, actual: str, expected: str) -> bool:
        if not actual or not expected:
            return False
        try:
            from difflib import SequenceMatcher

            ratio = SequenceMatcher(None, actual, expected).ratio()
            logger.attr("baseline_fuzzy_ratio", f"{ratio:.3f}")
            return ratio >= FUZZY_MATCH_THRESHOLD
        except Exception as exc:  # pragma: no cover
            logger.warning("Fuzzy match failed: %s", exc)
            return actual == expected

    def _select_target_name(
        self,
        target_name: str,
        initial_rows: Sequence[FilterRow],
        tab: str,
        max_pages: int = 20,
        part_after_select: Optional[str] = None,
    ) -> bool:
        logger.info("Selecting target '%s' on tab %s", target_name, tab)
        target = self._match_row_by_name(target_name, initial_rows)
        if target:
            self._click_row(target)
            self._confirm_selection()
            self._maybe_click_slot(part_after_select)
            return True

        for page_idx in range(1, max_pages):
            if not self._scroll_filter_panel():
                break
            page_rows = self._capture_current_rows()
            target = self._match_row_by_name(target_name, page_rows)
            if target:
                self._click_row(target)
                self._confirm_selection()
                self._maybe_click_slot(part_after_select)
                return True

        logger.warning("Target '%s' not found within %s pages on tab %s", target_name, max_pages, tab)
        return False

    def _match_row_by_name(self, target_name: str, rows: Sequence[FilterRow]) -> Optional[FilterRow]:
        for row in rows:
            if self._is_fuzzy_match(row.name.strip(), target_name.strip()):
                return row
        return None

    def _click_row(self, row: FilterRow) -> None:
        from module.base.button import ClickButton

        button = ClickButton(area=row.checkbox, name=f"SELECT_{row.name}")
        self.device.click(button)
        logger.info("Clicked checkbox for '%s'", row.name)

    def _confirm_selection(self) -> None:
        logger.info("Confirming filter selection via override template")
        if self._click_confirm_override():
            logger.info("Filter selection confirmed via override template")
        else:
            logger.warning("Failed to confirm selection using override template")
        self._return_to_relic_inventory()

    def _return_to_relic_inventory(self) -> None:
        """Leave the filter overlay by tapping the left relic tab button."""
        try:
            logger.info("Returning to relic main panel via RELICS_CLICK")
            self.device.click(RELICS_CLICK)
            self.wait_until_stable(ENHANCE_FILTER)
        except Exception as exc:  # pragma: no cover - defensive fallback
            logger.warning("Failed to return to relic panel via RELICS_CLICK: %s", exc)

    def _maybe_click_slot(self, part_after_select: Optional[str]) -> None:
        if not part_after_select:
            return
        try:
            if self.click_slot_button(part_after_select):
                logger.info("Slot '%s' selected after filter confirmation", part_after_select)
            else:
                logger.warning("Slot '%s' click did not register highlight change", part_after_select)
        except Exception as exc:  # pragma: no cover - defensive fallback
            logger.warning("Failed to click slot '%s': %s", part_after_select, exc)

    def _load_override_template(self):
        if CONFIRM_OVERRIDE_FILE.exists():
            image = cv2.imread(str(CONFIRM_OVERRIDE_FILE), cv2.IMREAD_GRAYSCALE)
            if image is None:
                logger.warning("Failed to load confirm override template %s", CONFIRM_OVERRIDE_FILE)
            return image
        return None

    def _load_template(self, filename: str):
        path = ASSETS_DIR / filename
        image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if image is None:
            logger.warning("Failed to load template %s", path)
        return image

    def _click_confirm_override(self) -> bool:
        if self.confirm_override is None:
            return False
        self.device.screenshot()
        image = cv2.cvtColor(self.device.image, cv2.COLOR_BGR2GRAY)
        h, w = self.confirm_override.shape[:2]
        res = cv2.matchTemplate(image, self.confirm_override, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        logger.info("Confirm override match score %.3f", max_val)
        x1, y1 = max_loc
        x2 = x1 + w
        y2 = y1 + h
        if max_val < 0.8:
            return False
        click_x = max_loc[0] + w // 2
        click_y = max_loc[1] + h // 2
        from module.base.button import ClickButton

        button = ClickButton(area=(click_x - 5, click_y - 5, click_x + 5, click_y + 5), name="FILTER_CONFIRM_OVERRIDE")
        self.device.click(button)
        self.device.sleep(0.3)
        return True
