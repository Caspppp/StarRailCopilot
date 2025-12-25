"""
Relic enhancement manager: centralizes pre-check, enhancement loop, and
post-actions (lock/discard) so callers don't duplicate logic.

Intended to be imported by tasks or tools; avoids hard-coding discard/lock
flows in ad-hoc testers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from module.logger import logger

from .upgrade_executor import EnhanceOutcome, RelicUpgradeExecutor
from .status_controls import RelicStatusController


@dataclass
class EnhanceResult:
    outcome: Optional[EnhanceOutcome]
    good: bool
    enhanced: bool
    total_hits: float = 0.0  # 最终加权命中数


class RelicEnhanceManager:
    def __init__(
        self,
        *,
        executor: RelicUpgradeExecutor,
        status: RelicStatusController,
        strategy_id: str = "default_3init_2valid",
        auto_discard_unqualified: bool = True,
        keep_crit_combo: bool = True,
        entry_precheck: Optional[dict] = None,
        params: Optional[dict] = None,
        save_threshold: Optional[float] = None,
    ) -> None:
        self.executor = executor
        self.status = status
        self.strategy_id = strategy_id
        self.profile = getattr(executor, "strategy_profile", None)
        self.auto_discard_unqualified = auto_discard_unqualified
        self.keep_crit_combo = keep_crit_combo
        # Extra precheck passed from caller (used when profile lacks it)
        self.entry_precheck = entry_precheck or {}
        # 方案参数（用于高级功能）
        self.params = params or {}
        # 保存阈值（仅 +15 时生效）
        self.save_threshold = save_threshold

    # -------------------------- Entry checks --------------------------
    def should_enhance(self, stats: dict) -> bool:
        level = stats.get("level")
        if level is None or level >= 15:
            return False
        # Use precheck from profile if available
        pre: dict = getattr(self.profile, "precheck", {}) if self.profile else {}
        # Fallback to external precheck when profile doesn't define init_subs
        if "init_subs" not in pre and self.entry_precheck.get("init_subs"):
            pre = dict(pre)
            pre["init_subs"] = self.entry_precheck.get("init_subs")
        require_any = set(pre.get("require_any", []))
        aliases = getattr(self.profile, "aliases", {}) if self.profile else {}
        # Control initial substats count: '3_only' or '4_only'
        mode = pre.get("init_subs")
        if mode in {"3_only", "4_only"}:
            subs_cnt = len(stats.get("subs") or [])
            try:
                logger.info("Entry precheck: init_subs=%s subs_cnt=%s strategy=%s", mode, subs_cnt, self.strategy_id)
            except Exception:
                pass
            if mode == "3_only" and subs_cnt != 3:
                try:
                    logger.info("Skip item: require 3 init subs, got %s", subs_cnt)
                except Exception:
                    pass
                return False
            if mode == "4_only" and subs_cnt < 4:
                try:
                    logger.info("Skip item: require 4 init subs, got %s", subs_cnt)
                except Exception:
                    pass
                return False
        if require_any:
            if not self._has_any(stats, require_any, aliases):
                return False
        elif self.strategy_id == "speed_priority":
            # Backward-compatible default for speed_priority
            if not self._has_sub(stats, {"spd", "速度"}):
                try:
                    logger.info("Skip item: speed_priority requires SPD substat")
                except Exception:
                    pass
                return False
        return True

    def pre_discard_if_unqualified(self, stats: dict) -> bool:
        if not self.auto_discard_unqualified:
            return False
        if self.should_enhance(stats):
            return False
        pre: dict = getattr(self.profile, "precheck", {}) if self.profile else {}
        aliases = getattr(self.profile, "aliases", {}) if self.profile else {}
        keep_combo = self.keep_crit_combo or pre.get("keep_crit_combo", False)
        if keep_combo and self._has_crit_combo(stats):
            logger.info("Pre-check: keep item (crit+crit_dmg combo)")
            return False
        if not (pre.get("discard_if_fail", True) or self.auto_discard_unqualified):
            return False
        # Avoid discarding locked ones
        locked = self.status.is_locked()
        discarded = self.status.is_discarded()
        if discarded or locked:
            return False
        ok = self.status.ensure_discarded(True)
        if ok:
            logger.info("Pre-check: item discarded (unqualified)")
        else:
            logger.warning("Pre-check: failed to discard unqualified item")
        return ok

    # ------------------------- Helpers (subs) -------------------------
    @staticmethod
    def _has_sub(stats: dict, keys: set[str]) -> bool:
        subs = stats.get("subs") or []
        for sub in subs:
            slug = (sub.get("slug") or "").strip()
            name = (sub.get("name") or "").strip()
            if slug in keys:
                return True
            if any(k in name for k in keys if k not in {"crit_rate", "crit_dmg", "spd"}):
                return True
            if "crit_rate" in keys and (slug == "crit_rate" or "暴击率" in name):
                return True
            if "crit_dmg" in keys and (slug == "crit_dmg" or "暴击伤害" in name or "暴伤" in name):
                return True
            if "spd" in keys and (slug == "spd" or "速度" in name):
                return True
        return False

    @staticmethod
    def _has_any(stats: dict, keys: set[str], aliases: dict) -> bool:
        canon = set(keys)
        for k in list(canon):
            for alias in aliases.get(k, []):
                canon.add(alias)
        subs = stats.get("subs") or []
        for sub in subs:
            slug = (sub.get("slug") or "").strip()
            name = (sub.get("name") or "").strip()
            if slug in canon or name in canon:
                return True
        return False

    def _has_crit_combo(self, stats: dict) -> bool:
        return self._has_sub(stats, {"crit_rate"}) and self._has_sub(stats, {"crit_dmg"})

    # ----------------------- 3初始词条探索模式 -----------------------
    def handle_three_init_exploration(self, stats: dict, slot: str) -> Tuple[str, bool]:
        """处理3初始词条探索模式

        Args:
            stats: 遗器属性字典
            slot: 当前部位

        Returns:
            (action, should_continue)
            - action: "explore" | "skip" | "discard" | "normal"
            - should_continue: 是否继续正常强化流程
        """
        advanced = self.params.get("advanced", {})
        explore_config = advanced.get("three_init_explore", {})

        if not explore_config.get("enabled"):
            return ("normal", True)

        subs = stats.get("subs", [])

        # 只对3初始遗器生效
        if len(subs) != 3 or stats.get("level", 0) > 0:
            return ("normal", True)

        logger.info(f"3初始探索模式: 检测到3初始遗器")

        # 计算初始加权命中
        weighted_sum = 0.0
        for sub in subs:
            weight = self.executor._get_substat_weight(sub, slot=slot)
            if weight > 0:
                weighted_sum += weight

        min_weighted = float(explore_config.get("min_weighted_hits", 1.0))
        logger.info(f"3初始探索模式: 加权命中 {weighted_sum:.1f}，阈值 {min_weighted:.1f}")

        if weighted_sum < min_weighted:
            # 不值得探索
            if explore_config.get("discard_if_miss"):
                logger.info(f"决策: 不值得探索（{weighted_sum:.1f} < {min_weighted:.1f}），标记弃置")
                return ("discard", False)
            logger.info(f"决策: 不值得探索（{weighted_sum:.1f} < {min_weighted:.1f}），跳过")
            return ("skip", False)

        # 值得探索 - 强化到+3看第4条
        logger.info(f"决策: 值得探索（{weighted_sum:.1f} ≥ {min_weighted:.1f}），强化到+3检查第4条")
        return ("explore", True)

    def check_fourth_stat(self, stats: dict, slot: str) -> Tuple[str, bool]:
        """检查第4条词条是否满足条件

        Args:
            stats: 遗器属性字典（应已强化到+3）
            slot: 当前部位

        Returns:
            (action, should_continue)
            - action: "continue" | "stop" | "discard" | "normal"
            - should_continue: 是否继续后续强化流程
        """
        advanced = self.params.get("advanced", {})
        explore_config = advanced.get("three_init_explore", {})

        if not explore_config.get("enabled"):
            return ("normal", True)

        subs = stats.get("subs", [])
        if len(subs) < 4:
            logger.warning("3初始探索: 期望有4条副词条，但只找到 %d 条", len(subs))
            return ("normal", True)

        # 第4条是最后添加的
        fourth_stat = subs[-1]
        fourth_slug = fourth_stat.get("slug", "")

        whitelist = set(explore_config.get("fourth_stat_whitelist", []))

        if not whitelist:
            # 白名单为空，接受任何第4条
            logger.info("3初始探索: 第4条白名单为空，接受所有词条")
            return ("continue", True)

        if fourth_slug in whitelist:
            logger.info(f"3初始探索: 第4条 '{fourth_slug}' 在白名单中，继续强化")
            return ("continue", True)
        else:
            logger.info(f"3初始探索: 第4条 '{fourth_slug}' 不在白名单 {whitelist} 中")
            if explore_config.get("discard_if_miss"):
                logger.info("3初始探索: 标记弃置")
                return ("discard", False)
            logger.info("3初始探索: 停止强化")
            return ("stop", False)

    # --------------------------- Enhance loop -------------------------
    def enhance_until_stop(self, stats: dict) -> EnhanceResult:
        outcome: Optional[EnhanceOutcome] = None
        did_any = False

        # 【初始化策略上下文】确保 total_hits 包含初始已有的有效词条
        try:
            self.executor.check_current_rule(stats)
        except Exception:
            pass  # 初始化失败不影响流程

        while True:
            step = self.executor.run(stats)
            if not step:
                break
            did_any = True
            outcome = step
            good = bool(step.rule_passed) if step.rule_id is not None else bool(step.is_desired)
            if not good:
                logger.info("Strategy not satisfied; stop further enhancement for this item")
                final_hits = float(stats.get("strategy", {}).get("total_hits", 0))
                return EnhanceResult(outcome=outcome, good=False, enhanced=did_any, total_hits=final_hits)
            if (stats.get("level") or 0) >= 15:
                logger.info("Item reached +15; stop enhancing")
                final_hits = float(stats.get("strategy", {}).get("total_hits", 0))
                return EnhanceResult(outcome=outcome, good=True, enhanced=did_any, total_hits=final_hits)
        final_hits = float(stats.get("strategy", {}).get("total_hits", 0))
        return EnhanceResult(outcome=outcome, good=bool(outcome and outcome.is_desired), enhanced=did_any, total_hits=final_hits)

    # -------------------------- Post decision -------------------------
    def apply_post_action(self, result: EnhanceResult) -> bool:
        """Apply post-enhancement action based on result and save_threshold.

        For +15 items (three-tier logic):
        - total_hits < global_threshold: Discard (handled by result.good=False)
        - global_threshold <= total_hits < save_threshold: No action
        - total_hits >= save_threshold: Lock

        For items not at +15:
        - good=True: No action (still enhancing)
        - good=False: Discard
        """
        if not result.outcome:
            return False

        good = result.good
        level = getattr(result.outcome, "level", None) or 0

        # 未到 +15：原有逻辑
        if level < 15:
            if not good:
                return self.status.ensure_discarded(True)
            return True  # good but not +15: no-op

        # +15 满级：三档逻辑
        if not good:
            # 低于全局阈值 → 弃置
            return self.status.ensure_discarded(True)

        # good=True 表示通过了全局阈值，检查保存阈值
        if self.save_threshold is not None:
            total_hits = result.total_hits
            if total_hits >= self.save_threshold:
                logger.info(f"Post-action: total_hits={total_hits:.1f} >= save_threshold={self.save_threshold}, 锁定")
                return self.status.ensure_locked(True)
            else:
                # 介于全局阈值和保存阈值之间 → 无操作
                logger.info(f"Post-action: total_hits={total_hits:.1f} < save_threshold={self.save_threshold}, 无操作")
                return True
        else:
            # 无保存阈值 → 原有行为（+15 达标即锁定）
            return self.status.ensure_locked(True)

    # -------------------------- Pre-evaluate on enter --------------------------
    def pre_evaluate_and_maybe_discard(
        self,
        stats: dict,
        detector,
        *,
        expected_item=None,
        respect_expected: bool = False,
    ) -> bool:
        """在进入强化前评估当前等级阈值，不满足则直接弃置。

        返回 True 表示已执行弃置（或已是弃置状态），上层应视为"本轮已做状态动作"。
        返回 False 表示通过或流程失败未处理。
        """
        try:
            ok_now, reason = self.executor.check_current_rule(stats)
        except Exception:
            ok_now, reason = True, None
        if ok_now:
            return False
        # 直接弃置（不预重锚 expected，除非调用方要求）
        try:
            nav = getattr(self.executor, "navigator", None)
            if nav is None:
                return False
            ok = nav.ensure_discarded_and_reanchor(
                self.status,
                detector,
                expected_item=expected_item,
                respect_expected=respect_expected,
            )
            return bool(ok)
        except Exception:
            return False
