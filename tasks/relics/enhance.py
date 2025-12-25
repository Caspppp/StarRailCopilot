"""
遗器自动强化任务

集成到主项目 WebUI 的遗器强化功能。
复用 tools/relics_recognizer 模块的核心逻辑。
"""

import fcntl
import time
from datetime import timedelta
from pathlib import Path
from typing import List, Optional

from module.base.button import ClickButton
from module.logger import logger
from tasks.relics.ui import RelicsUI

# 遗器任务锁文件路径
RELIC_LOCK_FILE = Path(__file__).parent.parent.parent / "config" / ".relic_task.lock"

# 词条中英文映射（支持双向转换）
SUBSTAT_CN_TO_SLUG = {
    "速度": "spd",
    "暴击率": "crit_rate",
    "暴击伤害": "crit_dmg",
    "击破特攻": "break",
    "攻击力": "atk_pct",
    "攻击%": "atk_pct",
    "生命值": "hp_pct",
    "生命%": "hp_pct",
    "防御力": "def_pct",
    "防御%": "def_pct",
    "效果命中": "eff_hit",
    "效果抵抗": "eff_res",
    "治疗量加成": "heal",
    "能量恢复效率": "eer",
    "物理属性伤害提高": "physical_dmg",
    "火属性伤害提高": "fire_dmg",
    "冰属性伤害提高": "ice_dmg",
    "雷属性伤害提高": "thunder_dmg",
    "风属性伤害提高": "wind_dmg",
    "量子属性伤害提高": "quantum_dmg",
    "虚数属性伤害提高": "imaginary_dmg",
}

SUBSTAT_SLUG_TO_CN = {v: k for k, v in SUBSTAT_CN_TO_SLUG.items()}

# 有效的 slug 列表
VALID_SLUGS = {
    "spd", "crit_rate", "crit_dmg", "break",
    "atk_pct", "hp_pct", "def_pct", "eff_hit", "eff_res", "heal",
    "eer",  # 能量恢复效率
    "physical_dmg", "fire_dmg", "ice_dmg", "thunder_dmg",
    "wind_dmg", "quantum_dmg", "imaginary_dmg",
}


def get_relic_set_tab(filter_name: str) -> str:
    """根据套装名称判断应该使用哪个筛选标签页

    Args:
        filter_name: 套装中文名称

    Returns:
        "relic" (外圈/隧洞遗器) 或 "ornament" (内圈/位面饰品)
    """
    if not filter_name:
        return "relic"  # 默认外圈

    try:
        from tasks.relics.keywords import relicset as relicset_mod
        for obj in relicset_mod.RelicSet.instances.values():
            if getattr(obj, 'cn', '') == filter_name:
                if getattr(obj, 'is_inner', False):
                    return "ornament"
                return "relic"
    except Exception:
        pass

    return "relic"  # 默认外圈


def get_threshold_for_slot(slot: str, level: int, params: dict) -> float:
    """获取指定部位和等级的阈值（支持部位独立阈值）

    Args:
        slot: 部位名称 (head, hands, body, feet, sphere, rope)
        level: 等级检查点 (0, 3, 6, 9)
        params: 方案参数

    Returns:
        阈值（浮点数，支持加权和模式）
    """
    advanced = params.get("advanced", {})
    slot_thresholds = advanced.get("slot_thresholds", {})

    if not slot_thresholds.get("enabled"):
        # 未启用部位独立阈值，使用全局阈值
        return float(params.get(f"min_hits_{level}", 0))

    # 查找部位所属的组
    groups = slot_thresholds.get("groups", {})
    slot_group = None
    for group_name, slots in groups.items():
        if slot in slots:
            slot_group = group_name
            break

    # 获取组的覆盖值
    if slot_group:
        overrides = slot_thresholds.get("overrides", {}).get(slot_group, {})
        level_key = f"min_hits_{level}"
        if level_key in overrides:
            return float(overrides[level_key])

    # 回退到全局阈值
    return float(params.get(f"min_hits_{level}", 0))


def get_weighted_hits(subs: List[dict], executor, slot: str = None) -> float:
    """计算副词条的加权命中总和

    Args:
        subs: 副词条列表
        executor: RelicUpgradeExecutor 实例
        slot: 当前部位（用于部位权重覆盖）

    Returns:
        加权命中总和
    """
    total = 0.0
    for sub in subs:
        weight = executor._get_substat_weight(sub, slot=slot)
        if weight > 0:
            total += weight
    return total


class RelicEnhance(RelicsUI):
    """遗器自动强化任务"""

    @staticmethod
    def _parse_list(value: str) -> List[str]:
        """解析逗号分隔的字符串为列表"""
        if not value:
            return []
        return [s.strip() for s in value.split(',') if s.strip()]

    @staticmethod
    def _normalize_stats(stats: List[str]) -> List[str]:
        """将词条统一转换为 slug 格式"""
        result = []
        for s in stats:
            if s in VALID_SLUGS:
                result.append(s)
            elif s in SUBSTAT_CN_TO_SLUG:
                result.append(SUBSTAT_CN_TO_SLUG[s])
            else:
                # 未知格式，保留原样
                result.append(s)
        return result

    def run(self):
        """执行遗器强化任务 - 使用方案模式"""
        from module.config.utils import alas_instance, get_server_next_update

        # 尝试获取文件锁（非阻塞）
        RELIC_LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        lock_file = open(RELIC_LOCK_FILE, 'w')
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            logger.info(f"获取遗器任务锁成功，开始执行")
        except BlockingIOError:
            # 其他任务正在运行，延迟重试
            logger.info(f"检测到其他遗器任务正在运行，5 分钟后重试")
            lock_file.close()
            self.config.task_delay(minute=5)
            return

        try:
            # 执行任务
            self._run_with_plans()

            # 计算下次执行时间（带账号延迟）
            all_configs = sorted(alas_instance())
            account_index = all_configs.index(self.config.config_name) if self.config.config_name in all_configs else 0
            delay_minutes = account_index * 10

            server_update_time = get_server_next_update(self.config.Scheduler_ServerUpdate)
            next_run = server_update_time + timedelta(minutes=delay_minutes)

            logger.info(f"账号 {self.config.config_name} (索引 {account_index}) 下次执行: {next_run}")
            self.config.task_delay(target=next_run)

        finally:
            # 释放锁
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            lock_file.close()
            logger.info(f"释放遗器任务锁")

    def _run_with_plans(self):
        """方案模式：遍历执行所有启用的方案"""
        from module.webui import relic_plans

        plans = relic_plans.get_enabled_plans(self.config.config_name)

        if not plans:
            logger.warning("没有启用的方案，跳过执行")
            return

        logger.info(f"方案模式：共 {len(plans)} 个启用的方案待执行")

        # 导入遗器识别模块
        try:
            from tools.relics_recognizer.grid import RelicGridDetector
            from tools.relics_recognizer.manager import RelicEnhanceManager
            from tools.relics_recognizer.navigation import RelicNavigator
            from tools.relics_recognizer.status_controls import RelicStatusController
            from tools.relics_recognizer.upgrade_executor import RelicUpgradeExecutor
            from tools.relics_recognizer.upgrade_strategies import StrategyProfile, StrategyRule
        except ImportError as e:
            logger.error(f"导入遗器识别模块失败: {e}")
            return

        # 初始化共用组件
        navigator = RelicNavigator(self.config.config_name)
        navigator.device = self.device
        grid_detector = RelicGridDetector()
        status_ctrl = RelicStatusController(self.device)

        from module.ocr.ocr import Ocr

        # 创建一个简单的 button mock，因为 OCR 使用 direct_ocr=True 模式
        class SimpleButton:
            def __init__(self):
                self.name = "RelicOCR"
                self.area = (0, 0, 1280, 720)  # 默认全屏区域

        ocr_model = Ocr(button=SimpleButton(), lang='cn')

        # 遍历执行每个方案
        for plan_idx, plan in enumerate(plans, 1):
            plan_name = plan.get("name", f"方案{plan_idx}")
            params = plan.get("params", {})

            logger.info(f"===== 方案 {plan_idx}/{len(plans)}: {plan_name} =====")

            # 每个方案开始前，先返回主页面再进入强化界面
            logger.info("返回主页面...")
            self.ui_goto_main()
            logger.info("进入遗器强化页面...")
            self.ui_goto_relics()
            self.relics_goto_enhance()
            logger.info("✓ 已到达遗器列表页，准备应用筛选")

            # 提取参数
            filter_name = params.get("filter_name", "")
            check_slots = params.get("check_slots", ["head", "hands", "body", "feet"])
            desired_stats = self._normalize_stats(params.get("substats", []))
            main_stat_body = self._normalize_stats(params.get("main_stat_body", []))
            main_stat_feet = self._normalize_stats(params.get("main_stat_feet", []))
            main_stat_sphere = self._normalize_stats(params.get("main_stat_sphere", []))
            main_stat_rope = self._normalize_stats(params.get("main_stat_rope", []))
            min_hits_0 = params.get("min_hits_0", 1)
            min_hits_3 = params.get("min_hits_3", 1)
            min_hits_6 = params.get("min_hits_6", 2)
            min_hits_9 = params.get("min_hits_9", 3)
            save_threshold = params.get("save_threshold", 5)
            discard_trash = params.get("discard_trash", True)
            stop_if_fail = params.get("stop_if_fail", True)

            # 显示配置
            logger.info(f"  套装筛选: {filter_name or '全部'}")
            logger.info(f"  强化部位: {check_slots}")
            logger.info(f"  期望副词条: {[SUBSTAT_SLUG_TO_CN.get(s, s) for s in desired_stats]}")
            logger.info(f"  阈值: +0≥{min_hits_0}, +3≥{min_hits_3}, +6≥{min_hits_6}, +9≥{min_hits_9}")

            # 创建运行时策略
            precheck_config = {
                "init_subs": None,
                "require_any": desired_stats,
                "discard_if_fail": discard_trash,
                "stop_if_fail": stop_if_fail,
            }
            if main_stat_body:
                precheck_config["main_stat_body"] = main_stat_body
            if main_stat_feet:
                precheck_config["main_stat_feet"] = main_stat_feet

            runtime_strategy = StrategyProfile(
                id=f"plan_{plan_idx}",
                name=plan_name,
                description=[f"方案 {plan_idx}"],
                rules={
                    0: StrategyRule(level=0, min_total_hits=min_hits_0),
                    3: StrategyRule(level=3, min_total_hits=min_hits_3),
                    6: StrategyRule(level=6, min_total_hits=min_hits_6),
                    9: StrategyRule(level=9, min_total_hits=min_hits_9),
                    12: StrategyRule(level=12, min_total_hits=4, promote_to_15=True),
                    15: StrategyRule(level=15, keep_only=True),
                },
                precheck=precheck_config
            )

            # 创建强化执行器（传入权重配置）
            advanced = params.get("advanced", {})
            weight_config = advanced.get("weights", {})
            executor = RelicUpgradeExecutor(
                navigator=navigator,
                ocr_model=ocr_model,
                runtime_profile=runtime_strategy,
                desired_overrides=desired_stats,
                weight_config=weight_config,
            )

            manager = RelicEnhanceManager(
                executor=executor,
                status=status_ctrl,
                auto_discard_unqualified=discard_trash,
                save_threshold=save_threshold,
                params=params,
            )

            # 执行当前方案
            self._execute_plan_slots(
                navigator=navigator,
                grid_detector=grid_detector,
                status_ctrl=status_ctrl,
                manager=manager,
                executor=executor,
                filter_name=filter_name,
                check_slots=check_slots,
                desired_stats=desired_stats,
                main_stat_body=main_stat_body,
                main_stat_feet=main_stat_feet,
                main_stat_sphere=main_stat_sphere,
                main_stat_rope=main_stat_rope,
                min_hits_0=min_hits_0,
                min_hits_3=min_hits_3,
                min_hits_6=min_hits_6,
                min_hits_9=min_hits_9,
                discard_trash=discard_trash,
                params=params,
            )

        logger.info("===== 所有方案执行完毕 =====")

    def _run_with_basic_config(self):
        """基础模式：使用配置页面的参数"""
        # 从 config 读取参数
        filter_name = self.config.RelicEnhance_RelicEnhance_FilterName
        check_slots_str = self.config.RelicEnhance_RelicEnhance_CheckSlots
        desired_stats_str = self.config.RelicEnhance_RelicEnhance_DesiredStats
        main_stat_body_str = getattr(self.config, 'RelicEnhance_RelicEnhance_MainStatBody', '')
        main_stat_feet_str = getattr(self.config, 'RelicEnhance_RelicEnhance_MainStatFeet', '')
        min_hits_0 = self.config.RelicEnhance_RelicEnhance_MinHits0
        min_hits_3 = self.config.RelicEnhance_RelicEnhance_MinHits3
        min_hits_6 = self.config.RelicEnhance_RelicEnhance_MinHits6
        min_hits_9 = self.config.RelicEnhance_RelicEnhance_MinHits9
        discard_trash = self.config.RelicEnhance_RelicEnhance_DiscardTrash
        stop_if_fail = getattr(self.config, 'RelicEnhance_RelicEnhance_StopIfFail', True)

        # 解析参数
        check_slots = self._parse_list(check_slots_str)
        desired_stats = self._normalize_stats(self._parse_list(desired_stats_str))
        main_stat_body = self._normalize_stats(self._parse_list(main_stat_body_str))
        main_stat_feet = self._normalize_stats(self._parse_list(main_stat_feet_str))

        # 显示配置信息
        desired_stats_display = [SUBSTAT_SLUG_TO_CN.get(s, s) for s in desired_stats]
        main_stat_body_display = [SUBSTAT_SLUG_TO_CN.get(s, s) for s in main_stat_body]
        main_stat_feet_display = [SUBSTAT_SLUG_TO_CN.get(s, s) for s in main_stat_feet]

        logger.info(f"遗器强化配置:")
        logger.info(f"  套装筛选: {filter_name or '全部'}")
        logger.info(f"  强化部位: {check_slots}")
        logger.info(f"  期望副词条: {desired_stats_display}")
        if main_stat_body:
            logger.info(f"  躯干主词条约束: {main_stat_body_display}")
        if main_stat_feet:
            logger.info(f"  脚部主词条约束: {main_stat_feet_display}")
        logger.info(f"  阈值: +0≥{min_hits_0}, +3≥{min_hits_3}, +6≥{min_hits_6}, +9≥{min_hits_9}")
        logger.info(f"  弃置不达标: {discard_trash}")
        logger.info(f"  未达标时停止: {stop_if_fail}")

        # 导入遗器识别模块
        try:
            from tools.relics_recognizer.grid import RelicGridDetector
            from tools.relics_recognizer.manager import RelicEnhanceManager
            from tools.relics_recognizer.navigation import RelicNavigator
            from tools.relics_recognizer.status_controls import RelicStatusController
            from tools.relics_recognizer.upgrade_executor import RelicUpgradeExecutor
            from tools.relics_recognizer.upgrade_strategies import StrategyProfile, StrategyRule
        except ImportError as e:
            logger.error(f"导入遗器识别模块失败: {e}")
            return

        # 创建运行时策略
        # 构建预检查配置
        precheck_config = {
            "init_subs": None,
            "require_any": desired_stats,
            "discard_if_fail": discard_trash,
            "stop_if_fail": stop_if_fail,
        }

        # 添加主词条约束（如果有）
        if main_stat_body:
            precheck_config["main_stat_body"] = main_stat_body
        if main_stat_feet:
            precheck_config["main_stat_feet"] = main_stat_feet

        runtime_strategy = StrategyProfile(
            id="runtime_custom",
            name="用户自定义策略",
            description=["根据 WebUI 参数动态生成"],
            rules={
                0: StrategyRule(level=0, min_total_hits=min_hits_0),
                3: StrategyRule(level=3, min_total_hits=min_hits_3),
                6: StrategyRule(level=6, min_total_hits=min_hits_6),
                9: StrategyRule(level=9, min_total_hits=min_hits_9),
                12: StrategyRule(level=12, min_total_hits=4, promote_to_15=True),
                15: StrategyRule(level=15, keep_only=True),
            },
            precheck=precheck_config
        )

        # 存储主词条约束供后续使用
        self._main_stat_constraints = {
            "body": main_stat_body,
            "feet": main_stat_feet,
        }

        # 初始化组件
        # 注意：RelicNavigator 需要 config_name，但它内部会创建自己的 device
        # 这里我们需要复用 self.device
        navigator = RelicNavigator(self.config.config_name)
        # 将 navigator 的 device 替换为我们的 device
        navigator.device = self.device

        grid_detector = RelicGridDetector()
        status_ctrl = RelicStatusController(self.device)

        # OCR 模型
        from module.ocr.ocr import Ocr

        # 创建一个简单的 button mock，因为 OCR 使用 direct_ocr=True 模式
        class SimpleButton:
            def __init__(self):
                self.name = "RelicOCR"
                self.area = (0, 0, 1280, 720)  # 默认全屏区域

        ocr_model = Ocr(button=SimpleButton(), lang='cn')

        # 强化执行器
        executor = RelicUpgradeExecutor(
            navigator=navigator,
            ocr_model=ocr_model,
            runtime_profile=runtime_strategy,
            desired_overrides=desired_stats,
        )

        # 强化管理器 (基础模式不支持 save_threshold，使用默认行为)
        manager = RelicEnhanceManager(
            executor=executor,
            status=status_ctrl,
            auto_discard_unqualified=discard_trash,
        )

        # 进入遗器强化页面
        logger.info("进入遗器管理页面...")
        self.ui_goto_relics()
        self.relics_goto_enhance()
        logger.info("已进入遗器强化页面")

        # 应用套装筛选
        if filter_name:
            logger.info(f"应用套装筛选: {filter_name}")
            try:
                # 根据套装名称判断标签页类型
                tab = get_relic_set_tab(filter_name)

                # 根据套装类型自动过滤部位
                if tab == "ornament":
                    # 内圈套装只处理 sphere 和 rope
                    check_slots = [s for s in check_slots if s in ["sphere", "rope"]]
                    if not check_slots:
                        check_slots = ["sphere", "rope"]
                    logger.info(f"内圈套装，自动调整部位为: {check_slots}")
                else:
                    # 外圈套装只处理 head, hands, body, feet
                    check_slots = [s for s in check_slots if s in ["head", "hands", "body", "feet"]]
                    if not check_slots:
                        check_slots = ["head", "hands", "body", "feet"]

                success = navigator.apply_filter_by_set_name(filter_name, tab=tab)
                if success:
                    logger.info(f"✓ 筛选成功: {filter_name}，当前显示该套装的遗器")
                else:
                    logger.warning(f"✗ 筛选失败: {filter_name}，将处理所有遗器")
            except Exception as e:
                logger.warning(f"应用筛选失败: {e}")

        # 统计
        stats_total = 0
        stats_enhanced = 0
        stats_discarded = 0
        stats_skipped = 0

        # 遍历部位
        slot_cn = {"head": "头部", "hands": "手部", "body": "躯干", "feet": "脚部", "sphere": "位面球", "rope": "连结绳"}

        for slot_idx, slot in enumerate(check_slots):
            logger.info(f"===== 处理部位 ({slot_idx + 1}/{len(check_slots)}): {slot_cn.get(slot, slot)} =====")

            # 选择部位
            try:
                navigator.select_part(slot)
                time.sleep(0.5)
                logger.info(f"✓ 已选择部位: {slot_cn.get(slot, slot)}，准备检测网格")
            except Exception as e:
                logger.warning(f"选择部位失败: {e}")
                continue

            # 处理当前部位的遗器
            processed_positions = set()
            max_items = 50  # 最多处理50个

            for item_idx in range(max_items):
                # 截图并检测网格
                self.device.screenshot()
                snap = grid_detector.detect(self.device.image)
                if not snap or not snap.items:
                    logger.info("未检测到遗器，该部位处理完成")
                    break

                # 过滤已处理的位置（使用 row, col 而不是 center）
                items = [i for i in snap.items if (i.row, i.col) not in processed_positions]
                if not items:
                    # 当前页面所有遗器已处理，检查是否需要翻页
                    if navigator.grid_is_at_bottom():
                        logger.info("已到达底部，该部位处理完成")
                        break
                    else:
                        logger.info("当前页面已处理完成，尝试翻页")
                        moved = navigator.grid_page_down_by_thumb(rows=4)
                        if moved:
                            processed_positions.clear()  # 清空，准备处理新页面
                            logger.info("翻页成功，继续处理")
                            continue
                        else:
                            logger.warning("翻页失败，该部位处理完成")
                            break

                # 利用白框检测确定当前选中的遗器
                current = snap.selected

                # 找到下一个有效遗器（未弃置且未锁定）
                item = self._find_next_valid_item(
                    self.device.image,
                    items,
                    current,
                    grid_detector,
                )

                if item is None:
                    # 所有剩余遗器都已弃置/锁定，标记为已处理
                    logger.info("剩余遗器均已锁定或弃置，标记为已处理")
                    for it in items:
                        processed_positions.add((it.row, it.col))
                    continue

                # 处理第一个遗器
                processed_positions.add((item.row, item.col))
                stats_total += 1
                logger.info(f"处理遗器 {stats_total}")

                try:
                    # 点击选中遗器
                    navigator.click_slot_verified(grid_detector, item)

                    # 等待面板加载
                    panel_data = None
                    for _ in range(10):
                        self.device.screenshot()
                        panel_data = executor.read_relic_panel()
                        if len(panel_data.get("subs", [])) >= 3:
                            break
                        time.sleep(0.2)

                    # 从网格读取等级并补充到 panel_data
                    level = navigator.read_level_from_box(self.device.image, item.level_box, ocr_model)
                    if level is not None:
                        panel_data["level"] = level

                    # 读取等级
                    initial_level = panel_data.get("level", 0)
                    logger.info(f"初始等级: +{initial_level}")

                    # 检查主词条约束（躯干/脚部）
                    main_stat_info = panel_data.get("main", {})
                    main_stat_slug = main_stat_info.get("slug", "") if isinstance(main_stat_info, dict) else ""

                    if slot == "body" and main_stat_body:
                        if main_stat_slug and main_stat_slug not in main_stat_body:
                            main_stat_display = SUBSTAT_SLUG_TO_CN.get(main_stat_slug, main_stat_slug)
                            constraint_display = [SUBSTAT_SLUG_TO_CN.get(s, s) for s in main_stat_body]
                            logger.info(f"决策: 躯干主词条 {main_stat_display} 不在允许列表 {constraint_display} 中")
                            stats_skipped += 1
                            if discard_trash:
                                status_ctrl.ensure_discarded(True)
                                logger.info("决策: 标记为弃置")
                                stats_discarded += 1
                            continue

                    if slot == "feet" and main_stat_feet:
                        if main_stat_slug and main_stat_slug not in main_stat_feet:
                            main_stat_display = SUBSTAT_SLUG_TO_CN.get(main_stat_slug, main_stat_slug)
                            constraint_display = [SUBSTAT_SLUG_TO_CN.get(s, s) for s in main_stat_feet]
                            logger.info(f"决策: 脚部主词条 {main_stat_display} 不在允许列表 {constraint_display} 中")
                            stats_skipped += 1
                            if discard_trash:
                                status_ctrl.ensure_discarded(True)
                                logger.info("决策: 标记为弃置")
                                stats_discarded += 1
                            continue

                    # 检查是否已弃置
                    if status_ctrl.is_discarded():
                        logger.info("遗器已标记弃置，跳过")
                        stats_skipped += 1
                        continue

                    # 显示副词条详情
                    subs = panel_data.get("subs", [])
                    logger.info(f"副词条详情:")
                    for i, sub in enumerate(subs):
                        slug = sub.get("slug", "?")
                        value = sub.get("value", "?")
                        desired = sub.get("desired", False)
                        status = "✓" if desired else "✗"
                        logger.info(f"  [{i}] {slug}={value} {status}")

                    desired_count = sum(1 for s in subs if s.get("desired"))

                    # 如果启用权重系统，也显示加权命中
                    if executor.weight_config and executor.weight_config.get("enabled"):
                        weighted_hits = get_weighted_hits(subs, executor, slot=slot)
                        logger.info(f"期望词条: {desired_count} 个，加权命中: {weighted_hits}")
                    else:
                        logger.info(f"期望词条: {desired_count} 个")

                    # 检查阈值
                    level_thresholds = {0: min_hits_0, 3: min_hits_3, 6: min_hits_6, 9: min_hits_9}
                    threshold_level = (initial_level // 3) * 3
                    min_required = level_thresholds.get(threshold_level, 0)

                    if desired_count < min_required:
                        logger.info(f"阈值检查: {desired_count} < {min_required} ❌ 不满足")
                        logger.info(f"期望词条列表: {executor.desired_overrides}")
                        stats_skipped += 1
                        if discard_trash:
                            status_ctrl.ensure_discarded(True)
                            logger.info("决策: 标记为弃置")
                            stats_discarded += 1
                        continue

                    logger.info(f"阈值检查: {desired_count} ≥ {min_required} ✓ 满足")

                    # 构建遗器数据
                    relic_stats = {
                        "main": panel_data.get("main", {}),
                        "subs": subs,
                        "level": initial_level,
                        "history": []
                    }

                    # 执行强化
                    result = manager.enhance_until_stop(relic_stats)

                    if result.enhanced:
                        stats_enhanced += 1
                        final_level = result.outcome.level if result.outcome else "?"
                        logger.info(f"强化完成: Lv.{final_level}")

                        # 关闭强化面板
                        self._close_enhance_overlay()

                        # 执行后续操作（锁定/弃置）
                        manager.apply_post_action(result)
                        if result.good:
                            logger.info("遗器达标，已锁定")
                        else:
                            logger.info("遗器不达标，已标记弃置")
                            stats_discarded += 1

                        # 返回网格
                        self._force_return_to_grid(grid_detector)
                    else:
                        logger.info("强化未执行，跳过")
                        stats_skipped += 1
                        if discard_trash:
                            status_ctrl.ensure_discarded(True)
                            logger.info("已标记弃置")
                            stats_discarded += 1

                except Exception as e:
                    logger.warning(f"处理遗器失败: {e}")
                    stats_skipped += 1
                    self._force_return_to_grid(grid_detector)
                    continue

        # 输出统计
        logger.info("===== 强化统计 =====")
        logger.info(f"处理总数: {stats_total}")
        logger.info(f"强化成功: {stats_enhanced}")
        logger.info(f"标记弃置: {stats_discarded}")
        logger.info(f"跳过: {stats_skipped}")

    def _close_enhance_overlay(self):
        """关闭强化材料面板"""
        try:
            close_button = ClickButton(area=(1222, 25, 1252, 55), name="CLOSE_ENHANCE")
            self.device.click(close_button)
            time.sleep(0.4)
            logger.info("已关闭强化面板")
        except Exception as e:
            logger.warning(f"关闭强化面板失败: {e}")

    def _force_return_to_grid(self, grid_detector):
        """智能返回网格界面"""
        from tools.relics_recognizer.grid import RelicGridDetector

        for attempt in range(3):
            try:
                self.device.screenshot()
                snap = grid_detector.detect(self.device.image)
                if snap and snap.items:
                    logger.info("已回到遗器网格")
                    return
            except Exception:
                pass

            # 点击关闭按钮
            try:
                close_button = ClickButton(area=(1222, 25, 1252, 55), name="CLOSE")
                self.device.click(close_button)
                time.sleep(0.4)
            except Exception:
                break

    def _find_next_valid_item(
        self,
        image,
        items,
        current,
        grid_detector,
    ):
        """找到当前遗器之后的下一个【未弃置且未锁定】的遗器

        Args:
            image: 当前截图
            items: 网格中的所有遗器
            current: 当前选中的遗器（白框位置），None 表示从头开始
            grid_detector: 网格检测器

        Returns:
            下一个有效遗器，如果没有则返回 None
        """
        if not items:
            return None

        # 按 (row, col) 排序
        sorted_items = sorted(items, key=lambda x: (x.row, x.col))

        # 确定起始索引
        start_idx = 0
        if current is not None:
            for i, item in enumerate(sorted_items):
                if item.row == current.row and item.col == current.col:
                    start_idx = i + 1  # 从当前位置的下一个开始
                    break

        # 从起始位置开始，找第一个未弃置且未锁定的
        for i in range(start_idx, len(sorted_items)):
            item = sorted_items[i]
            if grid_detector.has_discard_mark(image, item):
                logger.debug(f"跳过已弃置: row={item.row} col={item.col}")
                continue
            if grid_detector.has_lock_mark(image, item):
                logger.debug(f"跳过已锁定: row={item.row} col={item.col}")
                continue
            return item

        return None

    def _execute_plan_slots(
        self,
        navigator,
        grid_detector,
        status_ctrl,
        manager,
        executor,
        filter_name: str,
        check_slots: List[str],
        desired_stats: List[str],
        main_stat_body: List[str],
        main_stat_feet: List[str],
        main_stat_sphere: List[str],
        main_stat_rope: List[str],
        min_hits_0: int,
        min_hits_3: int,
        min_hits_6: int,
        min_hits_9: int,
        discard_trash: bool,
        params: Optional[dict] = None,
    ):
        """执行单个方案的所有部位强化"""
        # 如果没有传入 params，构建一个基础的
        if params is None:
            params = {
                "min_hits_0": min_hits_0,
                "min_hits_3": min_hits_3,
                "min_hits_6": min_hits_6,
                "min_hits_9": min_hits_9,
            }
        # 应用套装筛选
        if filter_name:
            logger.info(f"应用套装筛选: {filter_name}")
            try:
                # 根据套装名称判断标签页类型
                tab = get_relic_set_tab(filter_name)

                # 根据套装类型自动过滤部位
                if tab == "ornament":
                    # 内圈套装只处理 sphere 和 rope
                    check_slots = [s for s in check_slots if s in ["sphere", "rope"]]
                    if not check_slots:
                        check_slots = ["sphere", "rope"]
                    logger.info(f"内圈套装，自动调整部位为: {check_slots}")
                else:
                    # 外圈套装只处理 head, hands, body, feet
                    check_slots = [s for s in check_slots if s in ["head", "hands", "body", "feet"]]
                    if not check_slots:
                        check_slots = ["head", "hands", "body", "feet"]

                success = navigator.apply_filter_by_set_name(filter_name, tab=tab)
                if success:
                    logger.info(f"✓ 筛选成功: {filter_name}，当前显示该套装的遗器")
                else:
                    logger.warning(f"✗ 筛选失败: {filter_name}，将处理所有遗器")
            except Exception as e:
                logger.warning(f"应用筛选失败: {e}")

        # 统计
        stats_total = 0
        stats_enhanced = 0
        stats_discarded = 0
        stats_skipped = 0

        slot_cn = {"head": "头部", "hands": "手部", "body": "躯干", "feet": "脚部", "sphere": "位面球", "rope": "连结绳"}

        for slot_idx, slot in enumerate(check_slots):
            logger.info(f"===== 处理部位 ({slot_idx + 1}/{len(check_slots)}): {slot_cn.get(slot, slot)} =====")

            try:
                navigator.select_part(slot)
                time.sleep(0.5)
                # 设置执行器的当前部位，用于权重查找
                executor.set_current_slot(slot)
            except Exception as e:
                logger.warning(f"选择部位失败: {e}")
                continue

            processed_positions = set()
            max_items = 50

            for item_idx in range(max_items):
                self.device.screenshot()
                snap = grid_detector.detect(self.device.image)
                if not snap or not snap.items:
                    logger.info("未检测到遗器，该部位处理完成")
                    break

                items = [i for i in snap.items if (i.row, i.col) not in processed_positions]
                if not items:
                    # 当前页面所有遗器已处理，检查是否需要翻页
                    if navigator.grid_is_at_bottom():
                        logger.info("已到达底部，该部位处理完成")
                        break
                    else:
                        logger.info("当前页面已处理完成，尝试翻页")
                        moved = navigator.grid_page_down_by_thumb(rows=4)
                        if moved:
                            processed_positions.clear()  # 清空，准备处理新页面
                            logger.info("翻页成功，继续处理")
                            continue
                        else:
                            logger.warning("翻页失败，该部位处理完成")
                            break

                # 利用白框检测确定当前选中的遗器
                current = snap.selected

                # 找到下一个有效遗器（未弃置且未锁定）
                item = self._find_next_valid_item(
                    self.device.image,
                    items,
                    current,
                    grid_detector,
                )

                if item is None:
                    # 所有剩余遗器都已弃置/锁定，标记为已处理
                    logger.info("剩余遗器均已锁定或弃置，标记为已处理")
                    for it in items:
                        processed_positions.add((it.row, it.col))
                    continue

                processed_positions.add((item.row, item.col))
                stats_total += 1
                logger.info(f"处理遗器 {stats_total}")

                try:
                    navigator.click_slot_verified(grid_detector, item)

                    panel_data = None
                    for _ in range(10):
                        self.device.screenshot()
                        panel_data = executor.read_relic_panel()
                        if len(panel_data.get("subs", [])) >= 3:
                            break
                        time.sleep(0.2)

                    # 从网格读取等级并补充到 panel_data
                    level = navigator.read_level_from_box(self.device.image, item.level_box, executor.ocr)
                    if level is not None:
                        panel_data["level"] = level

                    initial_level = panel_data.get("level", 0)
                    logger.info(f"初始等级: +{initial_level}")

                    # 检查主词条约束
                    main_stat_info = panel_data.get("main", {})
                    main_stat_slug = main_stat_info.get("slug", "") if isinstance(main_stat_info, dict) else ""
                    main_stat_value = main_stat_info.get("value", "") if isinstance(main_stat_info, dict) else ""

                    # 对主词条 slug 进行映射 (hp + % → hp_pct)
                    if main_stat_slug in {"hp", "atk", "def"} and "%" in str(main_stat_value):
                        original_slug = main_stat_slug
                        main_stat_slug = f"{main_stat_slug}_pct"
                        logger.info(f"主词条映射: {original_slug} + {main_stat_value} → {main_stat_slug}")

                    if slot == "body" and main_stat_body:
                        if main_stat_slug and main_stat_slug not in main_stat_body:
                            logger.info(f"躯干主词条不匹配，跳过")
                            stats_skipped += 1
                            if discard_trash:
                                status_ctrl.ensure_discarded(True)
                                stats_discarded += 1
                            continue

                    if slot == "feet" and main_stat_feet:
                        if main_stat_slug and main_stat_slug not in main_stat_feet:
                            logger.info(f"脚部主词条不匹配，跳过")
                            stats_skipped += 1
                            if discard_trash:
                                status_ctrl.ensure_discarded(True)
                                stats_discarded += 1
                            continue

                    if slot == "sphere" and main_stat_sphere:
                        if main_stat_slug and main_stat_slug not in main_stat_sphere:
                            logger.info(f"位面球主词条不匹配，跳过")
                            stats_skipped += 1
                            if discard_trash:
                                status_ctrl.ensure_discarded(True)
                                stats_discarded += 1
                            continue

                    if slot == "rope" and main_stat_rope:
                        if main_stat_slug and main_stat_slug not in main_stat_rope:
                            logger.info(f"连结绳主词条不匹配，跳过")
                            stats_skipped += 1
                            if discard_trash:
                                status_ctrl.ensure_discarded(True)
                                stats_discarded += 1
                            continue

                    if status_ctrl.is_discarded():
                        logger.info("遗器已标记弃置，跳过")
                        stats_skipped += 1
                        continue

                    subs = panel_data.get("subs", [])
                    # 使用加权命中计算（支持权重系统）
                    weighted_hits = get_weighted_hits(subs, executor, slot=slot)
                    desired_count = sum(1 for s in subs if s.get("desired"))
                    logger.info(f"副词条: {len(subs)} 个，期望词条: {desired_count} 个，加权命中: {weighted_hits:.1f}")

                    # 使用部位特定阈值
                    threshold_level = (initial_level // 3) * 3
                    min_required = get_threshold_for_slot(slot, threshold_level, params)

                    # 构建遗器数据（移到阈值检查前，供探索模式使用）
                    relic_stats = {
                        "main": panel_data.get("main", {}),
                        "subs": subs,
                        "level": initial_level,
                        "history": []
                    }

                    if weighted_hits < min_required:
                        logger.info(f"+{initial_level}级检查: 加权命中 {weighted_hits:.1f} < {min_required:.1f}")

                        # 3初始词条探索模式 - 给不达标遗器一个机会
                        explore_action, should_continue = manager.handle_three_init_exploration(relic_stats, slot)

                        if explore_action == "explore":
                            logger.info("3初始探索: 值得探索，强化到+3检查第4条")
                            # 执行单次强化到+3
                            step_outcome = executor.run(relic_stats)
                            if step_outcome:
                                # 强化成功，重新读取面板获取第4条
                                self._close_enhance_overlay()
                                time.sleep(0.3)
                                self.device.screenshot()
                                new_panel = executor.read_relic_panel()
                                relic_stats["subs"] = new_panel.get("subs", [])
                                relic_stats["level"] = new_panel.get("level", 3)

                                # 检查第4条
                                fourth_action, fourth_continue = manager.check_fourth_stat(relic_stats, slot)
                                if fourth_action == "discard":
                                    logger.info("3初始探索: 第4条不满足，弃置")
                                    status_ctrl.ensure_discarded(True)
                                    stats_discarded += 1
                                    stats_skipped += 1
                                    self._force_return_to_grid(grid_detector)
                                    continue
                                elif fourth_action == "stop":
                                    logger.info("3初始探索: 第4条不满足，停止")
                                    stats_skipped += 1
                                    self._force_return_to_grid(grid_detector)
                                    continue
                                # fourth_action == "continue" or "normal" - 继续正常强化
                                logger.info("3初始探索: 第4条满足，继续强化")
                                # 不 continue，让代码继续执行到 enhance_until_stop
                            else:
                                logger.warning("3初始探索: 强化到+3失败")
                                stats_skipped += 1
                                continue
                        elif explore_action == "discard":
                            logger.info("3初始探索: 不值得探索，弃置")
                            stats_skipped += 1
                            if discard_trash:
                                status_ctrl.ensure_discarded(True)
                                stats_discarded += 1
                            continue
                        elif explore_action == "skip":
                            logger.info("3初始探索: 不值得探索，跳过")
                            stats_skipped += 1
                            continue
                        else:
                            # "normal" - 不是3初始遗器，正常弃置/跳过
                            logger.info(f"阈值检查不通过，跳过")
                            stats_skipped += 1
                            if discard_trash:
                                status_ctrl.ensure_discarded(True)
                                stats_discarded += 1
                            continue

                    logger.info(f"+{initial_level}级检查: 加权命中 {weighted_hits:.1f} ≥ {min_required:.1f}，开始强化")

                    result = manager.enhance_until_stop(relic_stats)

                    if result.enhanced:
                        stats_enhanced += 1
                        final_level = result.outcome.level if result.outcome else "?"
                        logger.info(f"强化完成: Lv.{final_level}")

                        self._close_enhance_overlay()
                        manager.apply_post_action(result)
                        if result.good:
                            logger.info("遗器达标，已锁定")
                        else:
                            logger.info("遗器不达标，已标记弃置")
                            stats_discarded += 1

                        self._force_return_to_grid(grid_detector)
                    else:
                        logger.info("强化未执行，跳过")
                        stats_skipped += 1
                        if discard_trash:
                            status_ctrl.ensure_discarded(True)
                            stats_discarded += 1

                except Exception as e:
                    logger.warning(f"处理遗器失败: {e}")
                    stats_skipped += 1
                    self._force_return_to_grid(grid_detector)
                    continue

        logger.info(f"方案统计: 处理 {stats_total}, 强化 {stats_enhanced}, 弃置 {stats_discarded}, 跳过 {stats_skipped}")
