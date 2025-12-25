"""
Reusable relic enhancement executor.

This module centralizes the enhancement workflow (auto-fill, material tweaks,
result OCR, etc.) so that higher-level scripts only need to provide the relic
stats and slot selection logic once.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import cv2
import numpy as np

from module.base.button import ClickButton
from module.base.utils import crop
from module.logger import logger

from .stat_rolls import RollEstimate, estimate_rolls
from .upgrade_strategies import StrategyManager, STRATEGY_FILE

ASSETS_DIR = (Path(__file__).parent / "assets").resolve()
SUBSTAT_ICON_DIR = (Path(__file__).parent / "substat_icons").resolve()

ENHANCE_TEMPLATE = ASSETS_DIR / "enhance_button.png"
ENHANCE_AUTO_FILL_TEMPLATE = ASSETS_DIR / "enhance_auto_fill.png"
ENHANCE_TOGGLE_TEMPLATE = ASSETS_DIR / "enhance_materials_toggle.png"
ENHANCE_PLUS_THREE_TEMPLATE = ASSETS_DIR / "enhance_plus_three.png"
ENHANCE_NEXT_NODE_TEMPLATE = ASSETS_DIR / "enhance_next_node.png"
ENHANCE_CONFIRM_TEMPLATE = ASSETS_DIR / "enhance_confirm.png"
ENHANCE_RETURN_TEMPLATE = ASSETS_DIR / "enhance_material_return.png"

PLUS_THREE_BOX = (955, 83, 68, 35)
ENHANCE_RESULT_ICON_AREA = (671, 439, 691, 457)
ENHANCE_RESULT_VALUE_BOX = (1034, 437, 81, 22)
MAIN_RESULT_VALUE_BOX = (1041, 403, 75, 21)

# 遗器详情面板坐标 (右侧面板，选中遗器后显示)
# 用户提供的坐标 (1920x1080 分辨率)
PANEL_MAIN_STAT_ICON_BOX = (879, 312, 35, 33)    # 主词条图标
PANEL_MAIN_STAT_VALUE_BOX = (1146, 312, 100, 33) # 主词条数值
PANEL_SUBSTAT_ICON_BOXES = [                      # 副词条图标
    (879, 345, 35, 33),  # 第1条
    (879, 378, 35, 33),  # 第2条
    (879, 411, 35, 33),  # 第3条
    (879, 444, 35, 33),  # 第4条
]
PANEL_SUBSTAT_VALUE_BOXES = [                     # 副词条数值
    (1146, 345, 100, 33),  # 第1条
    (1146, 378, 100, 33),  # 第2条
    (1146, 411, 100, 33),  # 第3条
    (1146, 444, 100, 33),  # 第4条
]
ENHANCE_EXECUTE_BUTTON = ClickButton(area=(1063, 653, 1107, 673), name="ENHANCE_EXECUTE")
ENHANCE_SUCCESS_DISMISS = ClickButton(area=(540, 600, 740, 700), name="ENHANCE_SUCCESS_DISMISS")
AUTO_FILL_DIFF_THRESHOLD = 1.0


def to_xyxy(box):
    x, y, w, h = box
    return (x, y, x + w, y + h)


@dataclass
class RelicStatSnapshot:
    level: int
    subs: Sequence[dict]
    total_hits: int = 0
    speed_value: Optional[float] = None
    speed_rolls: int = 0


@dataclass
class EnhanceOutcome:
    level: int
    slug: Optional[str]
    stat_name: str
    normalized_value: str
    raw_value: str
    rolls: Optional[int]
    delta_rolls: int
    delta_hits: float  # 权重值（0.0, 0.5, 1.0, 1.5, 2.0 等）
    is_desired: bool
    numeric_value: Optional[float] = None
    rule_id: Optional[str] = None
    rule_passed: Optional[bool] = None
    rule_reason: Optional[str] = None


class RelicUpgradeExecutor:
    """Encapsulates the UI interactions for a single relic enhancement."""

    def __init__(
        self,
        navigator,
        ocr_model,
        *,
        strategy_id: str = "default_3init_2valid",
        strategy_path: Optional[Path] = None,
        runtime_profile=None,
        desired_overrides: Optional[Sequence[str]] = None,
        weight_config: Optional[Dict] = None,
    ):
        self.navigator = navigator
        self.device = navigator.device
        self.ocr = ocr_model
        self._result_snapshot = None
        self._current_slot = None  # 当前处理的部位，用于权重查找

        self.strategy_manager = StrategyManager(path=strategy_path or STRATEGY_FILE)
        self.strategy_id = strategy_id
        self.strategy_profile = runtime_profile or self.strategy_manager.get(strategy_id)
        if not self.strategy_profile:
            logger.warning("Strategy '%s' not found; proceeding without thresholds", strategy_id)
        # Desired substat overrides (canonical slugs). Examples: 'spd','crit_rate','crit_dmg','eer','res','break','hp','hp_pct','hp_flat'
        # None = 使用内置启发式；空集 = 无限制；非空集 = 只保留指定词条
        if desired_overrides is None:
            self.desired_overrides = None
        else:
            self.desired_overrides = set(map(str.strip, desired_overrides))

        # 权重配置（高级功能）
        # 格式: {"enabled": bool, "global": {slug: weight}, "slot_overrides": {slot: {slug: weight}}}
        self.weight_config = weight_config

        self.enhance_template = self._load_template(ENHANCE_TEMPLATE)
        self.auto_fill_template = self._load_template(ENHANCE_AUTO_FILL_TEMPLATE)
        self.toggle_template = self._load_template(ENHANCE_TOGGLE_TEMPLATE)
        self.plus_three_template = self._load_template(ENHANCE_PLUS_THREE_TEMPLATE)
        self.next_node_template = self._load_template(ENHANCE_NEXT_NODE_TEMPLATE)
        self.confirm_template = self._load_template(ENHANCE_CONFIRM_TEMPLATE)
        self.material_return_template = self._load_template(ENHANCE_RETURN_TEMPLATE)
        self.substat_icon_templates = self._load_substat_templates()

    # ------------------------------------------------------------------ API
    def run(self, stats: dict) -> Optional[EnhanceOutcome]:
        if not self._click_enhance_button():
            return None
        if not self._wait_for_enhance_overlay():
            return None
        auto_area = self._click_auto_fill_button()
        if auto_area is None:
            return None
        plus_ok = self._check_plus_three()
        if not plus_ok:
            logger.info("Plus three not detected, adjusting materials")
            self._click_area(auto_area)
            if not self._click_material_toggle():
                return None
            if not self._click_next_node_flow():
                return None
            self._click_area(auto_area)
            self.device.sleep(0.4)
            plus_ok = self._check_plus_three()
            if not plus_ok:
                logger.warning("Adjustments did not produce +3 materials")
                return None
        if not self._click_enhance_execute():
            return None
        self.device.sleep(1.0)
        outcome = self._detect_enhance_result(stats)
        if not outcome:
            return None
        self._increment_level(stats)
        self._update_strategy_context(stats, outcome)
        self._evaluate_strategy_rule(stats, outcome)
        return outcome

    def read_relic_panel(self) -> dict:
        """读取当前选中遗器的主词条和副词条（使用图标匹配）。

        Returns:
            dict: {
                "main": {"name": str, "value": str, "slug": str},
                "subs": [{"name": str, "value": str, "slug": str, "rolls": int, "desired": bool}, ...],
                "level": int (如果能识别)
            }
        """
        self.device.screenshot()
        result = {"main": {}, "subs": [], "level": 0}

        # 读取主词条（图标匹配 + OCR数值）
        main_slug, main_score = self._match_icon_in_box(PANEL_MAIN_STAT_ICON_BOX)
        main_value = self._ocr_value_box(PANEL_MAIN_STAT_VALUE_BOX, "panel_main_value")
        logger.info("Panel main: slug='%s' (score=%.2f), value='%s'", main_slug, main_score, main_value)
        if main_slug:
            result["main"]["slug"] = main_slug
            result["main"]["name"] = self._cn_from_slug(main_slug) or main_slug
        if main_value:
            result["main"]["value"] = self._normalize_value(main_value)

        # 读取副词条（图标匹配 + OCR数值）
        for idx in range(4):
            icon_box = PANEL_SUBSTAT_ICON_BOXES[idx]
            value_box = PANEL_SUBSTAT_VALUE_BOXES[idx]

            slug, score = self._match_icon_in_box(icon_box)
            raw_value = self._ocr_value_box(value_box, f"panel_sub_value_{idx}")
            value = self._normalize_value(raw_value) if raw_value else ""

            logger.info("Panel sub %d: slug='%s' (score=%.2f), value='%s'", idx, slug, score, value)

            if not slug or score < 0.5:
                continue

            name = self._cn_from_slug(slug) or slug
            entry = {"name": name, "value": value, "slug": slug, "score": score}

            # 估算 rolls
            from .stat_rolls import estimate_rolls
            roll_est = estimate_rolls(name, value)
            entry["rolls"] = roll_est.rolls if roll_est else 1
            # 判断是否有效词条
            entry["desired"] = self._is_desired_substat(entry)
            result["subs"].append(entry)

        return result

    def _match_icon_in_box(self, box: tuple) -> tuple:
        """在指定区域匹配图标模板，返回 (slug, score)"""
        if not self.substat_icon_templates:
            return None, 0.0

        xyxy = to_xyxy(box)
        roi = crop(self.device.image, xyxy)
        if roi is None:
            return None, 0.0

        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        best_slug = None
        best_score = 0.0

        for slug, template in self.substat_icon_templates.items():
            # 直接使用模板匹配（模板比 ROI 小，可以滑动匹配）
            if template.shape[0] > binary.shape[0] or template.shape[1] > binary.shape[1]:
                # 模板比 ROI 大，需要缩放
                scale = min(binary.shape[0] / template.shape[0], binary.shape[1] / template.shape[1]) * 0.9
                new_size = (int(template.shape[1] * scale), int(template.shape[0] * scale))
                resized_tpl = cv2.resize(template, new_size, interpolation=cv2.INTER_AREA)
            else:
                resized_tpl = template

            res = cv2.matchTemplate(binary, resized_tpl, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(res)

            if max_val > best_score:
                best_score = max_val
                best_slug = slug

        return best_slug, best_score

    def _parse_substat_line(self, text: str) -> Optional[dict]:
        """解析副词条行文本，如 '生命值 38' 或 '暴击率 5.1%'"""
        import re
        text = text.strip()
        # 匹配: 词条名 + 空格/符号 + 数值(可能带%)
        match = re.match(r'^([^\d]+?)\s*[:\s]*([+\-]?\d+\.?\d*%?)$', text)
        if match:
            name = match.group(1).strip()
            value = match.group(2).strip()
            slug = self._cn_to_slug(name)
            return {"name": name, "value": value, "slug": slug}
        return None

    # ------------------------------------------------------------------ helpers
    def _load_template(self, path: Path):
        if not path.exists():
            logger.warning("Template %s not found", path)
            return None
        image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if image is None:
            logger.warning("Failed to load template %s", path)
        return image

    def _load_substat_templates(self) -> dict:
        templates: dict[str, np.ndarray] = {}
        if not SUBSTAT_ICON_DIR.exists():
            logger.warning("Substat icon directory %s missing", SUBSTAT_ICON_DIR)
            return templates
        for path in SUBSTAT_ICON_DIR.glob("*.png"):
            image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
            if image is None:
                logger.warning("Failed to load substat icon %s", path)
                continue
            parts = path.stem.split("_")
            slug = "_".join(parts[1:]) if len(parts) > 1 else parts[0]
            _, binary = cv2.threshold(image, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            templates[slug] = binary
        return templates

    def _click_enhance_button(self) -> bool:
        # If overlay already open, allow proceeding without clicking the button.
        if self.toggle_template is not None:
            self.device.screenshot()
            area = self._match_template(self.toggle_template, threshold=0.75)
            if area:
                logger.info("Enhance overlay already open; skipping button click")
                return True
        if self.enhance_template is None:
            return False
        self.device.screenshot()
        gray = cv2.cvtColor(self.device.image, cv2.COLOR_BGR2GRAY)
        res = cv2.matchTemplate(gray, self.enhance_template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        logger.info("Enhance button match score %.3f", max_val)
        if max_val < 0.8:
            return False
        h, w = self.enhance_template.shape
        button = ClickButton(area=(max_loc[0], max_loc[1], max_loc[0] + w, max_loc[1] + h), name="ENHANCE_ACTION")
        self.device.click(button)
        self.device.sleep(0.5)
        return True

    def _wait_for_enhance_overlay(self, timeout: float = 5.0) -> bool:
        if self.toggle_template is None:
            return False
        end = time.time() + timeout
        while time.time() < end:
            self.device.screenshot()
            area = self._match_template(self.toggle_template, threshold=0.75)
            if area:
                logger.info("Enhance overlay detected")
                return True
            self.device.sleep(0.3)
        return False

    def _click_auto_fill_button(self):
        if self.auto_fill_template is None:
            return None
        self.device.screenshot()
        area = self._match_template(self.auto_fill_template, threshold=0.8)
        if not area:
            return None
        before = self._crop_gray(area)
        self._click_area(area, name="AUTO_FILL")
        self.device.sleep(0.4)
        after = self._crop_gray(area, refresh=True)
        diff = self._mean_abs_diff(before, after)
        logger.info("Auto fill diff %.2f", diff)
        if diff < AUTO_FILL_DIFF_THRESHOLD:
            logger.warning("Auto fill button change too small (%.2f)", diff)
        return area

    def _check_plus_three(self) -> bool:
        if self.plus_three_template is None:
            return False
        self.device.screenshot()
        x, y, w, h = PLUS_THREE_BOX
        roi = crop(self.device.image, (x, y, x + w, y + h))
        if roi is None:
            return False
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        res = cv2.matchTemplate(gray, self.plus_three_template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, _ = cv2.minMaxLoc(res)
        logger.info("Plus three match score %.3f", max_val)
        if max_val >= 0.82:
            return True
        value = self._ocr_value_box(PLUS_THREE_BOX, "plus_area")
        if not value:
            logger.warning("Plus area OCR empty; assume acceptable")
            return True
        digits = re.findall(r"\d+", value)
        if not digits:
            return True
        try:
            num = int(digits[0])
        except ValueError:
            return False
        logger.info("Plus area OCR -> %s", num)
        return num <= 3

    def _click_material_toggle(self) -> bool:
        if self.toggle_template is None:
            return False
        self.device.screenshot()
        area = self._match_template(self.toggle_template, threshold=0.75)
        if not area:
            logger.warning("Material toggle button not found")
            return False
        before = self._crop_gray(area)
        self._click_area(area, name="MATERIAL_TOGGLE")
        self.device.sleep(0.3)
        after = self._crop_gray(area, refresh=True)
        diff = self._mean_abs_diff(before, after)
        logger.info("Material toggle diff %.2f", diff)
        return diff >= 0.5

    def _click_next_node_flow(self) -> bool:
        if self.next_node_template is None:
            return False
        self.device.screenshot()
        area = self._match_template(self.next_node_template, threshold=0.8)
        if not area:
            logger.warning("Next-node button not found")
            return False
        before = self._crop_gray(area)
        self._click_area(area, name="NEXT_NODE")
        self.device.sleep(0.3)
        after = self._crop_gray(area, refresh=True)
        diff = self._mean_abs_diff(before, after)
        logger.info("Next-node diff %.2f", diff)
        if diff < 0.8:
            logger.warning("Next-node button did not change enough")
            return False
        return self._click_enhance_confirm()

    def _click_enhance_confirm(self) -> bool:
        if self.confirm_template is None:
            return False
        self.device.screenshot()
        area = self._match_template(self.confirm_template, threshold=0.75)
        if not area:
            logger.warning("Enhance confirm button not found")
            return False
        self._click_area(area, name="ENHANCE_CONFIRM")
        self.device.sleep(0.3)
        return True

    def _click_enhance_execute(self) -> bool:
        self.device.click(ENHANCE_EXECUTE_BUTTON)
        self.device.sleep(0.8)
        return True

    def _detect_enhance_result(self, stats: dict) -> Optional[EnhanceOutcome]:
        ready = self._wait_for_result_ready()
        snapshot = self._result_snapshot if self._result_snapshot is not None else self.device.image
        if not ready:
            logger.warning("Enhance result overlay did not stabilize in time")
            return None
        self._update_main_stat_from_result(stats, snapshot)
        slug = self._match_substat_icon(snapshot)
        if not slug:
            logger.warning("Unable to determine which substat was upgraded")
            return None
        slug = self._canonicalize_slug(slug)
        raw_value = self._ocr_value_box(ENHANCE_RESULT_VALUE_BOX, "substat_result", snapshot)
        value = self._normalize_value(raw_value)
        if not value:
            logger.warning("Failed to OCR enhanced substat value")
            return None
        cn_name = self._cn_from_slug(slug) or slug
        prior = self._find_substat_entry(stats, slug, cn_name)
        prior_rolls = self._safe_rolls(prior)
        entry, roll_estimate = self._update_substat_entry(stats, slug, cn_name, raw_value, value)
        new_rolls = self._safe_rolls(entry)
        delta_rolls = max(1, new_rolls - prior_rolls)
        # 获取词条权重（支持高级权重系统）
        weight = self._get_substat_weight(entry, slot=self._current_slot)
        is_desired = weight > 0
        numeric_value = roll_estimate.value if roll_estimate else self._parse_numeric_value(value)
        # 对于"策略命中次数"，使用权重值而非简单的 0/1
        # 这样可以支持 0.5, 1.0, 1.5, 2.0 等不同权重
        delta_hits = weight
        self._dismiss_enhance_popup()
        self._result_snapshot = None
        outcome = EnhanceOutcome(
            level=min(15, (stats.get("level") or 0) + 3),
            slug=slug,
            stat_name=cn_name,
            normalized_value=value,
            raw_value=raw_value,
            rolls=new_rolls or None,
            delta_rolls=delta_rolls,
            delta_hits=delta_hits,
            is_desired=is_desired,
            numeric_value=numeric_value,
        )
        history = stats.setdefault("history", [])
        history.append({
            "level": outcome.level,
            "slug": slug,
            "name": cn_name,
            "value": value,
            "delta_rolls": delta_rolls,
            "desired": is_desired,
        })
        return outcome

    def _match_substat_icon(self, image=None) -> Optional[str]:
        if not self.substat_icon_templates:
            return None
        source = image if image is not None else self.device.image
        roi = crop(source, ENHANCE_RESULT_ICON_AREA)
        if roi is None:
            return None
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        best_slug = None
        best_score = 0.0
        target_h, target_w = binary.shape
        for slug, template in self.substat_icon_templates.items():
            resized = cv2.resize(template, (target_w, target_h), interpolation=cv2.INTER_AREA)
            res = cv2.matchTemplate(binary, resized, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(res)
            if max_val > best_score:
                best_score = max_val
                best_slug = slug
        logger.info("Enhanced substat match %s score %.3f", best_slug, best_score)
        if best_score < 0.5:
            return None
        return best_slug

    def _update_substat_entry(
        self,
        stats: dict,
        slug: Optional[str],
        cn_name: str,
        raw_value: str,
        normalized: str,
    ) -> tuple[dict, Optional["RollEstimate"]]:
        slug = self._canonicalize_slug(slug)
        cn_name = self._cn_from_slug(slug) or cn_name
        entry = self._find_substat_entry(stats, slug, cn_name)
        if entry is None:
            entry = {"name": cn_name, "slug": slug}
            stats.setdefault("subs", []).append(entry)
        rolls = estimate_rolls(cn_name, raw_value)
        entry["slug"] = slug
        entry["name"] = cn_name
        entry["value"] = normalized
        entry["raw_value"] = raw_value
        entry["rolls"] = rolls.rolls if rolls and rolls.rolls is not None else entry.get("rolls")
        logger.info("Substat '%s' updated to %s", cn_name, normalized)
        return entry, rolls

    def _update_main_stat_from_result(self, stats: dict, snapshot=None) -> None:
        raw = self._ocr_value_box(MAIN_RESULT_VALUE_BOX, "main_result", snapshot)
        value = self._normalize_value(raw)
        if not value:
            logger.warning("Failed to OCR enhanced main stat value")
            return
        stats.setdefault("main", {})
        stats["main"]["value"] = value
        logger.info("Main stat refreshed to %s", value)

    def _dismiss_enhance_popup(self) -> None:
        try:
            self.device.click(ENHANCE_SUCCESS_DISMISS)
            self.device.sleep(0.3)
        except Exception as exc:
            logger.warning("Failed to dismiss enhance popup: %s", exc)
        if self.material_return_template is not None:
            self.device.screenshot()
            area = self._match_template(self.material_return_template, threshold=0.7)
            if area:
                logger.info("Clicking material return button")
                self._click_area(area, name="MATERIAL_RETURN")
                self.device.sleep(0.3)

    def _wait_for_result_ready(self, timeout: float = 5.0, required_frames: int = 2) -> bool:
        end = time.time() + timeout
        consecutive = 0
        while time.time() < end:
            self.device.screenshot()
            self._result_snapshot = self.device.image.copy()
            slug = self._match_substat_icon(self._result_snapshot)
            if slug:
                consecutive += 1
                if consecutive >= required_frames:
                    return True
            else:
                consecutive = 0
            self.device.sleep(0.2)
        self._result_snapshot = self.device.image.copy()
        return False

    def _ocr_value_box(self, box, label: str, image=None) -> str:
        source = image if image is not None else self.device.image
        if len(box) == 4 and box[2] > box[0] and box[3] > box[1]:
            xyxy = box
        else:
            xyxy = to_xyxy(box)
        region = crop(source, xyxy)
        if region is None:
            return ""
        gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        binary_bgr = cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)
        try:
            # 使用 direct_ocr=True 因为图像已经预先裁剪
            text = self.ocr.ocr_single_line(binary_bgr, direct_ocr=True)
        except Exception as exc:  # pragma: no cover
            logger.warning("OCR failed on result box %s: %s", box, exc)
            return ""
        return (text or "").strip()

    @staticmethod
    def _normalize_value(value: str) -> str:
        if not value:
            return ""
        return re.sub(r"[^0-9.+%-]", "", value)

    def _cn_from_slug(self, slug: Optional[str]) -> Optional[str]:
        mapping = {
            "hp": "生命值",
            "atk": "攻击力",
            "def": "防御力",
            "spd": "速度",
            "crit_rate": "暴击率",
            "crit_dmg": "暴击伤害",
            "eer": "能量恢复效率",
            "res": "效果抵抗",
            "break": "击破特攻",
            "eff_hit": "效果命中",
            "heal": "治疗量加成",
            "physical_dmg": "物理属性伤害提高",
            "fire_dmg": "火属性伤害提高",
            "ice_dmg": "冰属性伤害提高",
            "thunder_dmg": "雷属性伤害提高",
            "wind_dmg": "风属性伤害提高",
            "quantum_dmg": "量子属性伤害提高",
            "imaginary_dmg": "虚数属性伤害提高",
        }
        return mapping.get(slug, slug)

    def _cn_to_slug(self, name: Optional[str]) -> Optional[str]:
        mapping = {
            "生命值": "hp",
            "攻击力": "atk",
            "防御力": "def",
            "速度": "spd",
            "暴击率": "crit_rate",
            "暴击伤害": "crit_dmg",
            "能量恢复效率": "eer",
            "效果命中": "eff_hit",
            "效果抵抗": "res",
            "击破特攻": "break",
            "治疗量加成": "heal",
            "物理属性伤害提高": "physical_dmg",
            "火属性伤害提高": "fire_dmg",
            "冰属性伤害提高": "ice_dmg",
            "雷属性伤害提高": "thunder_dmg",
            "风属性伤害提高": "wind_dmg",
            "量子属性伤害提高": "quantum_dmg",
            "虚数属性伤害提高": "imaginary_dmg",
        }
        return mapping.get(name)

    def _find_substat_entry(self, stats: dict, slug: Optional[str], cn_name: str) -> Optional[dict]:
        for sub in stats.get("subs", []):
            sub_slug = sub.get("slug") or self._cn_to_slug(sub.get("name"))
            if slug and sub_slug == slug:
                return sub
            if not slug and sub.get("name") == cn_name:
                return sub
        return None

    def _is_desired_substat(self, entry: Optional[dict]) -> bool:
        if not entry:
            return False
        if entry.get("desired") is not None:
            return bool(entry["desired"])
        slug = entry.get("slug") or self._cn_to_slug(entry.get("name"))
        slug = self._canonicalize_slug(slug)
        value = entry.get("value") or ""
        # Runtime overrides take precedence
        # None = 使用内置启发式；空集 = 无限制（返回 True）；非空集 = 只保留指定词条
        if self.desired_overrides is not None:
            # 空集表示"无限制"，所有词条都接受
            if not self.desired_overrides:
                logger.debug(f"  {slug}={value}: ✓ 有效 (无限制模式)")
                return True
            # 非空集，只接受指定词条
            s = (slug or "").strip()
            if s in self.desired_overrides:
                logger.debug(f"  {slug}={value}: ✓ 有效 (在期望列表中)")
                return True
            if s in {"hp", "atk", "def"}:
                # Support both half-width (%) and full-width (％) percent signs from OCR
                is_pct = "%" in value or "％" in value
                if is_pct and f"{s}_pct" in self.desired_overrides:
                    logger.debug(f"  {slug}={value}: ✓ 有效 ({s}_pct 在期望列表中)")
                    return True
                if (not is_pct) and f"{s}_flat" in self.desired_overrides:
                    logger.debug(f"  {slug}={value}: ✓ 有效 ({s}_flat 在期望列表中)")
                    return True
                # If user wrote hp (without suffix), accept both
                if s in self.desired_overrides:
                    logger.debug(f"  {slug}={value}: ✓ 有效 ({s} 在期望列表中)")
                    return True
                # 如果都不在，记录原因
                expected = f"{s}_pct" if is_pct else f"{s}_flat"
                logger.debug(f"  {slug}={value}: ✗ 无效 ({expected} 不在期望列表中)")
            else:
                logger.debug(f"  {slug}={value}: ✗ 无效 (不在期望列表中)")
            return False
        # self.desired_overrides is None，使用内置启发式
        if slug in {"crit_rate", "crit_dmg", "spd", "eer", "res", "break"}:
            logger.debug(f"  {slug}={value}: ✓ 有效 (默认有效词条)")
            return True
        if slug in {"hp", "atk", "def"}:
            # Support both half-width (%) and full-width (％) percent signs from OCR
            is_pct = "%" in value or "％" in value
            if is_pct:
                logger.debug(f"  {slug}={value}: ✓ 有效 (百分比词条)")
                return True
            else:
                logger.debug(f"  {slug}={value}: ✗ 无效 (固定值词条)")
                return False
        logger.debug(f"  {slug}={value}: ✗ 无效 (未知词条类型)")
        return False

    def _get_substat_weight(self, entry: Optional[dict], slot: str = None) -> float:
        """获取词条权重（0.0 表示无效词条）

        当启用权重系统时，返回配置的权重值。
        当未启用时，返回 1.0（有效）或 0.0（无效），保持向后兼容。

        Args:
            entry: 词条数据字典
            slot: 当前部位（用于部位特定权重覆盖）

        Returns:
            权重值（0.0, 0.5, 1.0, 1.5, 2.0 等）
        """
        if not entry:
            return 0.0

        slug = entry.get("slug") or self._cn_to_slug(entry.get("name"))
        slug = self._canonicalize_slug(slug)
        value = entry.get("value", "")

        # 根据值类型映射 slug (hp -> hp_pct/hp_flat)
        slug = self._map_slug_by_value(slug, value)

        # 处理 slug 别名（eer -> eff_hit, res -> eff_res）
        slug_aliases = {"eer": "eff_hit", "res": "eff_res"}
        slug = slug_aliases.get(slug, slug)

        if not slug:
            return 0.0

        # 【核心逻辑】先检查是否在期望词条列表中
        # 如果不在期望列表中，直接返回 0.0（不计入加权命中）
        if self.desired_overrides is not None and len(self.desired_overrides) > 0:
            if slug not in self.desired_overrides:
                # 特殊处理: hp_pct/atk_pct/def_pct 可能用户只写了 hp/atk/def
                base_slug = slug.replace("_pct", "").replace("_flat", "")
                if base_slug not in self.desired_overrides:
                    logger.debug(f"    权重: {slug}={value} → 0.0 (不在期望列表中)")
                    return 0.0

        # 检查权重系统是否启用
        if self.weight_config and self.weight_config.get("enabled"):
            global_weights = self.weight_config.get("global", {})
            slot_overrides = self.weight_config.get("slot_overrides", {})

            # 获取全局权重
            weight = global_weights.get(slug, 0.0)

            # 应用部位覆盖（如果有）
            if slot and slot in slot_overrides:
                slot_weight = slot_overrides[slot].get(slug)
                if slot_weight is not None:
                    logger.debug(f"    权重: {slug}={value} → {slot_weight} (部位 {slot} 覆盖，原全局={weight})")
                    return float(slot_weight)

            logger.debug(f"    权重: {slug}={value} → {weight} (全局配置)")
            return float(weight)

        # 未启用权重系统，使用现有布尔逻辑（有效=1.0，无效=0.0）
        is_desired = self._is_desired_substat(entry)
        weight = 1.0 if is_desired else 0.0
        logger.debug(f"    权重: {slug}={value} → {weight} (未启用权重系统)")
        return weight

    def set_current_slot(self, slot: str) -> None:
        """设置当前处理的部位"""
        self._current_slot = slot

    @staticmethod
    def _canonicalize_slug(slug: Optional[str]) -> Optional[str]:
        if slug is None:
            return None
        s = slug.strip().lower()
        if s == "rate":
            return "crit_rate"
        if s in {"dmg", "critdmg", "cd"}:
            return "crit_dmg"
        return s  # Return lowercase normalized slug

    @staticmethod
    def _map_slug_by_value(slug: Optional[str], value: str) -> Optional[str]:
        """根据值类型将 slug 映射到 _pct 或 _flat 形式

        OCR 返回的 slug 可能是 'hp', 'def', 'atk'，但权重配置使用
        'hp_pct', 'def_pct', 'atk_pct'（百分比）或
        'hp_flat', 'def_flat', 'atk_flat'（固定值）。

        Args:
            slug: 基础 slug (如 'hp', 'def', 'atk')
            value: 词条值字符串 (如 '3.4%' 或 '42')

        Returns:
            映射后的 slug (如 'hp_pct' 或 'hp_flat')
        """
        if not slug:
            return slug

        # 需要映射的基础 slug
        base_slugs = {"hp", "def", "atk"}

        if slug in base_slugs:
            is_percentage = "%" in str(value)
            if is_percentage:
                return f"{slug}_pct"
            else:
                return f"{slug}_flat"

        return slug

    @staticmethod
    def _safe_rolls(entry: Optional[dict]) -> int:
        if not entry:
            return 0
        rolls = entry.get("rolls")
        if rolls is None:
            return 0
        try:
            return int(round(float(rolls)))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _parse_numeric_value(text: Optional[str]) -> Optional[float]:
        if not text:
            return None
        cleaned = text.replace("%", "").replace("+", "").strip()
        cleaned = ''.join(ch for ch in cleaned if ch.isdigit() or ch in ".-")
        if not cleaned:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None

    def _increment_level(self, stats: dict) -> None:
        current = stats.get("level") or 0
        stats["level"] = min(15, current + 3)

    def _update_strategy_context(self, stats: dict, outcome: EnhanceOutcome) -> None:
        context: Dict[str, object] = stats.setdefault("strategy", {})
        total_hits = int(context.get("total_hits", 0)) + outcome.delta_hits
        context["total_hits"] = total_hits
        # Update speed from the popup first if this roll hit speed
        if outcome.slug == "spd":
            if outcome.numeric_value is not None:
                context["speed_value"] = outcome.numeric_value
            if outcome.rolls is not None:
                context["speed_rolls"] = outcome.rolls

        # Always reflect current speed state from stats as a fallback, so that
        # non-speed rolls keep the previous speed value consistent and later
        # speed rolls can be captured even if popup parsing changes.
        try:
            subs = stats.get("subs") or []
            speed_entry = None
            for sub in subs:
                slug = (sub.get("slug") or "").strip()
                name = (sub.get("name") or "").strip()
                if slug == "spd" or "速度" in name:
                    speed_entry = sub
                    break
            if speed_entry is not None:
                # Value
                sv_text = speed_entry.get("value") or ""
                sv_num = self._parse_numeric_value(self._normalize_value(str(sv_text)))
                if sv_num is not None:
                    context["speed_value"] = sv_num
                # Rolls
                rolls = speed_entry.get("rolls")
                if rolls is not None:
                    try:
                        context["speed_rolls"] = int(rolls)
                    except Exception:
                        pass
        except Exception:
            pass
        history: List[dict] = context.setdefault("history", [])  # type: ignore[assignment]
        history.append(
            {
                "level": outcome.level,
                "slug": outcome.slug,
                "name": outcome.stat_name,
                "delta_rolls": outcome.delta_rolls,
                "delta_hits": outcome.delta_hits,
                "desired": outcome.is_desired,
            }
        )

    def _evaluate_strategy_rule(self, stats: dict, outcome: EnhanceOutcome) -> None:
        if not self.strategy_profile:
            return
        level = stats.get("level")
        if level is None:
            return
        rule = self.strategy_profile.rules.get(level)
        if not rule:
            return
        context = stats.get("strategy", {})
        total_hits = int(context.get("total_hits", 0))
        speed_rolls = int(context.get("speed_rolls", 0))
        speed_value = context.get("speed_value")
        passed = True
        reasons: List[str] = []
        if rule.min_hits is not None and outcome.delta_hits < rule.min_hits:
            passed = False
            reasons.append(f"期待本次命中≥{rule.min_hits}, 实际 {outcome.delta_hits}")
        if rule.min_total_hits is not None and total_hits < rule.min_total_hits:
            passed = False
            reasons.append(f"累计命中需≥{rule.min_total_hits}, 实际 {total_hits}")
        if rule.min_speed_rolls is not None and speed_rolls < rule.min_speed_rolls:
            passed = False
            reasons.append(f"速度 Rolls 需≥{rule.min_speed_rolls}, 实际 {speed_rolls}")
        if rule.min_speed_value is not None:
            value = float(speed_value or 0)
            if value < rule.min_speed_value:
                passed = False
                reasons.append(f"速度值需≥{rule.min_speed_value}, 实际 {value}")
        # Extended: min_stat_values on current stats
        if getattr(rule, "min_stat_values", None):
            for key, min_val in rule.min_stat_values.items():
                current = self._current_stat_value(stats, key)
                if current is None or current < float(min_val):
                    passed = False
                    reasons.append(f"{key} 需≥{min_val}, 实际 {current if current is not None else 'None'}")
        outcome.rule_id = f"{self.strategy_profile.id}@+{level}"
        outcome.rule_passed = passed
        outcome.rule_reason = " ; ".join(reasons) if reasons else None
        if passed:
            logger.info("Strategy %s level +%s passed", self.strategy_profile.id, level)
        else:
            logger.warning(
                "Strategy %s level +%s failed: %s",
                self.strategy_profile.id,
                level,
                outcome.rule_reason or "unknown",
            )

    # ---------------------- Public: pre-evaluate on enter ----------------------
    def check_current_rule(self, stats: dict) -> tuple[bool, Optional[str]]:
        """Evaluate current stats against the rule for its current level without rolling.

        Only enforces persistent thresholds like speed rolls/value and min_stat_values;
        it does NOT enforce per-roll expectations (min_hits), since no new roll occurs yet.

        Returns (passed, reason_if_failed).
        """
        if not self.strategy_profile:
            return True, None
        level = stats.get("level")
        if level is None:
            return True, None
        rule = self.strategy_profile.rules.get(level)
        if not rule:
            return True, None
        # Build context from current stats (subs) to get speed info
        context = stats.setdefault("strategy", {})
        # 若当前还没有 total_hits，则依据现有面板的大致“命中次数”做一次估算：
        # - 使用 _is_desired_substat 判定是否为目标词条；
        # - 若有 rolls 字段，则按 rolls 计；否则至少按 1 次命中计。
        try:
            if context.get("total_hits") in (None, 0):
                subs = stats.get("subs") or []
                approx_hits = 0
                for sub in subs:
                    if not self._is_desired_substat(sub):
                        continue
                    rolls = sub.get("rolls")
                    try:
                        rolls_i = int(rolls) if rolls is not None else 1
                    except Exception:
                        rolls_i = 1
                    approx_hits += max(rolls_i, 1)
                context["total_hits"] = approx_hits
        except Exception:
            pass
        try:
            subs = stats.get("subs") or []
            speed_entry = None
            for sub in subs:
                slug = (sub.get("slug") or "").strip()
                name = (sub.get("name") or "").strip()
                if slug == "spd" or "速度" in name:
                    speed_entry = sub
                    break
            if speed_entry is not None:
                # Value
                sv_text = speed_entry.get("value") or ""
                sv_num = self._parse_numeric_value(self._normalize_value(str(sv_text)))
                if sv_num is not None:
                    context["speed_value"] = sv_num
                # Rolls
                rolls = speed_entry.get("rolls")
                if rolls is not None:
                    try:
                        context["speed_rolls"] = int(rolls)
                    except Exception:
                        pass
        except Exception:
            pass
        total_hits = int(context.get("total_hits", 0))
        speed_rolls = int(context.get("speed_rolls", 0))
        speed_value = context.get("speed_value")
        # Evaluate only persistent thresholds
        reasons = []
        passed = True
        if rule.min_total_hits is not None and total_hits < rule.min_total_hits:
            passed = False
            reasons.append(f"累计命中需≥{rule.min_total_hits}, 实际 {total_hits}")
        if rule.min_speed_rolls is not None and speed_rolls < rule.min_speed_rolls:
            passed = False
            reasons.append(f"速度 Rolls 需≥{rule.min_speed_rolls}, 实际 {speed_rolls}")
        if rule.min_speed_value is not None:
            value = float(speed_value or 0)
            if value < rule.min_speed_value:
                passed = False
                reasons.append(f"速度值需≥{rule.min_speed_value}, 实际 {value}")
        if getattr(rule, "min_stat_values", None):
            for key, min_val in rule.min_stat_values.items():
                current = self._current_stat_value(stats, key)
                if current is None or current < float(min_val):
                    passed = False
                    reasons.append(f"{key} 需≥{min_val}, 实际 {current if current is not None else 'None'}")
        if not passed:
            return False, "; ".join(reasons) if reasons else "thresholds not met"
        return True, None

    def _current_stat_value(self, stats: dict, key: str) -> Optional[float]:
        # Normalize key via aliases if provided
        aliases = getattr(self.strategy_profile, "aliases", {}) if self.strategy_profile else {}
        targets = {key}
        for k, arr in aliases.items():
            if k == key:
                targets.update(arr)
        subs = stats.get("subs") or []
        for sub in subs:
            name = (sub.get("name") or "").strip()
            slug = (sub.get("slug") or "").strip()
            if slug == key or name == key or slug in targets or name in targets:
                val = self._parse_numeric_value(sub.get("value"))
                if val is not None:
                    return val
        # Special handling for speed
        if key in {"spd", "速度"}:
            val = stats.get("strategy", {}).get("speed_value")
            try:
                return float(val) if val is not None else None
            except Exception:
                return None
        return None

    def _match_template(self, template, threshold=0.8):
        if template is None:
            return None
        gray = cv2.cvtColor(self.device.image, cv2.COLOR_BGR2GRAY)
        res = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        if max_val < threshold:
            return None
        h, w = template.shape
        return (max_loc[0], max_loc[1], max_loc[0] + w, max_loc[1] + h)

    def _click_area(self, area, name="GENERIC_CLICK"):
        button = ClickButton(area=tuple(map(int, area)), name=name)
        self.device.click(button)

    def _crop_gray(self, area, refresh: bool = False):
        if refresh:
            self.device.screenshot()
        x1, y1, x2, y2 = map(int, area)
        gray = cv2.cvtColor(self.device.image, cv2.COLOR_BGR2GRAY)
        return gray[y1:y2, x1:x2].copy()

    @staticmethod
    def _mean_abs_diff(before, after) -> float:
        if before is None or after is None or before.shape != after.shape:
            return 0.0
        return float(np.mean(np.abs(after.astype(np.int16) - before.astype(np.int16))))
