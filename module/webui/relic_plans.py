"""
遗器强化方案管理模块

提供方案的增删改查、启用/禁用、排序等功能。
方案存储在 config/relic_plans_{config_name}.yaml 文件中。
"""

from pathlib import Path
from typing import List, Dict, Any, Optional
import time
import yaml

from module.logger import logger

PLANS_DIR = Path("config")


def get_plans_file(config_name: str) -> Path:
    """获取方案存储文件路径"""
    return PLANS_DIR / f"relic_plans_{config_name}.yaml"


def load_plans(config_name: str) -> List[Dict]:
    """
    加载方案列表

    Args:
        config_name: 配置名称（账号名）

    Returns:
        方案列表，每个方案包含 id, name, enabled, params
    """
    plans_file = get_plans_file(config_name)
    if not plans_file.exists():
        logger.info(f"方案文件不存在: {plans_file}")
        return []

    try:
        with open(plans_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        plans = data.get("plans", [])

        # 迁移旧配置
        needs_save = False
        for plan in plans:
            if "params" in plan:
                plan["params"] = ensure_advanced_params(plan["params"])

                # 检测权重是否需要更新（新词条或默认值变更）
                if _weights_need_update(plan["params"].get("advanced", {})):
                    _update_weights_to_latest(plan["params"]["advanced"])
                    needs_save = True
                    logger.info(f"方案 '{plan.get('name')}' 的权重配置已更新")

        # 一次性保存迁移结果
        if needs_save:
            save_plans(config_name, plans)
            logger.info(f"已自动迁移 {config_name} 的权重配置")

        logger.info(f"加载 {len(plans)} 个方案: {config_name}")
        return plans
    except Exception as e:
        logger.error(f"加载方案失败: {e}")
        return []


def save_plans(config_name: str, plans: List[Dict]) -> bool:
    """
    保存方案列表

    Args:
        config_name: 配置名称（账号名）
        plans: 方案列表

    Returns:
        是否保存成功
    """
    plans_file = get_plans_file(config_name)
    try:
        PLANS_DIR.mkdir(parents=True, exist_ok=True)
        with open(plans_file, "w", encoding="utf-8") as f:
            yaml.dump({"plans": plans}, f, allow_unicode=True, default_flow_style=False)
        logger.info(f"保存 {len(plans)} 个方案: {config_name}")
        return True
    except Exception as e:
        logger.error(f"保存方案失败: {e}")
        return False


def _weights_need_update(advanced: Dict[str, Any]) -> bool:
    """检查权重配置是否需要更新"""
    if "weights" not in advanced:
        return False

    current_weights = advanced["weights"].get("global", {})
    default_weights = get_default_advanced_params()["weights"]["global"]

    # 检查是否有新词条缺失
    for slug in default_weights:
        if slug not in current_weights:
            return True

    # 检查是否有旧默认值0.0需要更新为新默认值
    for slug, default_weight in default_weights.items():
        if current_weights.get(slug) == 0.0 and default_weight != 0.0:
            return True

    return False


def _update_weights_to_latest(advanced: Dict[str, Any]) -> None:
    """更新权重配置到最新默认值（添加缺失的词条，并更新旧默认值0.0）"""
    if "weights" not in advanced:
        advanced["weights"] = get_default_advanced_params()["weights"]
        return

    current_weights = advanced["weights"].get("global", {})
    default_weights = get_default_advanced_params()["weights"]["global"]

    # 添加缺失的词条，并更新值为0.0的旧默认值（保留用户自定义的非零值）
    for slug, default_weight in default_weights.items():
        if slug not in current_weights or current_weights.get(slug) == 0.0:
            current_weights[slug] = default_weight

    advanced["weights"]["global"] = current_weights


def generate_plan_id() -> str:
    """生成唯一的方案ID"""
    return f"plan_{int(time.time() * 1000)}"


def get_default_params() -> Dict[str, Any]:
    """获取默认方案参数"""
    return {
        "mode": "enhance",
        "filter_name": "",
        "check_slots": ["head", "hands", "body", "feet"],
        "substats": ["spd", "crit_rate", "crit_dmg"],
        "main_stat_body": [],
        "main_stat_feet": [],
        "main_stat_sphere": [],
        "main_stat_rope": [],
        "min_hits_0": 1,
        "min_hits_3": 1,
        "min_hits_6": 2,
        "min_hits_9": 3,
        "save_threshold": 5,
        "enhance_goal": 15,
        "stop_if_fail": True,
        "discard_trash": True,
        # 高级选项（默认全部禁用，保持向后兼容）
        "advanced": get_default_advanced_params(),
    }


def get_default_advanced_params() -> Dict[str, Any]:
    """获取默认高级参数"""
    return {
        # 功能1：部位独立阈值
        "slot_thresholds": {
            "enabled": False,
            "groups": {
                "head_hands": ["head", "hands"],
                "body": ["body"],
                "feet": ["feet"],
                "sphere": ["sphere"],
                "rope": ["rope"],
            },
            "overrides": {
                "head_hands": {},
                "body": {},
                "feet": {},
                "sphere": {},
                "rope": {},
            },
        },
        # 功能2：词条权重系统
        "weights": {
            "enabled": False,
            "global": {
                "spd": 1.0,
                "crit_rate": 1.0,
                "crit_dmg": 1.0,
                "break": 1.0,
                "atk_pct": 1.0,
                "hp_pct": 1.0,
                "def_pct": 1.0,
                "eff_hit": 1.0,
                "eff_res": 1.0,
                # 固定值词条（权重 0.5）
                "atk_flat": 0.5,
                "hp_flat": 0.5,
                "def_flat": 0.5,
            },
            "slot_overrides": {},
        },
        # 功能3：3初始词条探索模式
        "three_init_explore": {
            "enabled": False,
            "min_weighted_hits": 1.0,
            "fourth_stat_whitelist": ["spd", "crit_rate", "crit_dmg"],
            "discard_if_miss": True,
        },
    }


def ensure_advanced_params(params: Dict[str, Any]) -> Dict[str, Any]:
    """确保参数包含 advanced 字段（迁移旧配置）"""
    if "advanced" not in params:
        params["advanced"] = get_default_advanced_params()
    else:
        # 确保 advanced 包含所有必需的子字段
        default_advanced = get_default_advanced_params()
        for key, value in default_advanced.items():
            if key not in params["advanced"]:
                params["advanced"][key] = value
            elif isinstance(value, dict):
                # 深度合并
                for sub_key, sub_value in value.items():
                    if sub_key not in params["advanced"][key]:
                        params["advanced"][key][sub_key] = sub_value
    return params


def create_plan(config_name: str, name: str, params: Optional[Dict] = None) -> Optional[Dict]:
    """
    创建新方案

    Args:
        config_name: 配置名称
        name: 方案名称
        params: 方案参数（可选，使用默认值）

    Returns:
        新创建的方案，失败返回 None
    """
    plans = load_plans(config_name)

    new_plan = {
        "id": generate_plan_id(),
        "name": name,
        "enabled": True,
        "params": params or get_default_params(),
    }

    plans.append(new_plan)

    if save_plans(config_name, plans):
        logger.info(f"创建方案: {name} (id={new_plan['id']})")
        return new_plan
    return None


def update_plan(config_name: str, plan_id: str, updates: Dict) -> Optional[Dict]:
    """
    更新方案

    Args:
        config_name: 配置名称
        plan_id: 方案ID
        updates: 要更新的字段（可包含 name, enabled, params）

    Returns:
        更新后的方案，失败返回 None
    """
    plans = load_plans(config_name)

    for i, plan in enumerate(plans):
        if plan.get("id") == plan_id:
            # 更新字段
            if "name" in updates:
                plan["name"] = updates["name"]
            if "enabled" in updates:
                plan["enabled"] = updates["enabled"]
            if "params" in updates:
                # 合并参数更新
                plan["params"] = {**plan.get("params", {}), **updates["params"]}

            plans[i] = plan

            if save_plans(config_name, plans):
                logger.info(f"更新方案: {plan_id}")
                return plan
            return None

    logger.warning(f"方案不存在: {plan_id}")
    return None


def delete_plan(config_name: str, plan_id: str) -> bool:
    """
    删除方案

    Args:
        config_name: 配置名称
        plan_id: 方案ID

    Returns:
        是否删除成功
    """
    plans = load_plans(config_name)
    original_len = len(plans)

    plans = [p for p in plans if p.get("id") != plan_id]

    if len(plans) == original_len:
        logger.warning(f"方案不存在: {plan_id}")
        return False

    if save_plans(config_name, plans):
        logger.info(f"删除方案: {plan_id}")
        return True
    return False


def get_plan(config_name: str, plan_id: str) -> Optional[Dict]:
    """
    获取单个方案

    Args:
        config_name: 配置名称
        plan_id: 方案ID

    Returns:
        方案数据，不存在返回 None
    """
    plans = load_plans(config_name)
    for plan in plans:
        if plan.get("id") == plan_id:
            return plan
    return None


def toggle_plan(config_name: str, plan_id: str) -> Optional[bool]:
    """
    切换方案启用/禁用状态

    Args:
        config_name: 配置名称
        plan_id: 方案ID

    Returns:
        新的启用状态，失败返回 None
    """
    plans = load_plans(config_name)

    for i, plan in enumerate(plans):
        if plan.get("id") == plan_id:
            new_state = not plan.get("enabled", True)
            plan["enabled"] = new_state
            plans[i] = plan

            if save_plans(config_name, plans):
                logger.info(f"切换方案状态: {plan_id} -> {new_state}")
                return new_state
            return None

    logger.warning(f"方案不存在: {plan_id}")
    return None


def reorder_plans(config_name: str, plan_ids: List[str]) -> List[Dict]:
    """
    调整方案顺序

    Args:
        config_name: 配置名称
        plan_ids: 新的方案ID顺序

    Returns:
        重排序后的方案列表
    """
    plans = load_plans(config_name)

    # 创建ID到方案的映射
    plan_map = {p.get("id"): p for p in plans}

    # 按新顺序重排
    reordered = []
    for pid in plan_ids:
        if pid in plan_map:
            reordered.append(plan_map[pid])
            del plan_map[pid]

    # 将未在列表中的方案追加到末尾
    for plan in plan_map.values():
        reordered.append(plan)

    if save_plans(config_name, reordered):
        logger.info(f"重排序方案: {len(reordered)} 个")
        return reordered
    return plans


def move_plan(config_name: str, plan_id: str, direction: str) -> List[Dict]:
    """
    移动方案位置

    Args:
        config_name: 配置名称
        plan_id: 方案ID
        direction: 移动方向 ("up" 或 "down")

    Returns:
        移动后的方案列表
    """
    plans = load_plans(config_name)

    # 找到方案索引
    idx = None
    for i, plan in enumerate(plans):
        if plan.get("id") == plan_id:
            idx = i
            break

    if idx is None:
        logger.warning(f"方案不存在: {plan_id}")
        return plans

    # 计算新位置
    if direction == "up" and idx > 0:
        new_idx = idx - 1
    elif direction == "down" and idx < len(plans) - 1:
        new_idx = idx + 1
    else:
        return plans

    # 交换位置
    plans[idx], plans[new_idx] = plans[new_idx], plans[idx]

    if save_plans(config_name, plans):
        logger.info(f"移动方案: {plan_id} {direction}")

    return plans


def duplicate_plan(config_name: str, plan_id: str) -> Optional[Dict]:
    """
    复制方案

    Args:
        config_name: 配置名称
        plan_id: 要复制的方案ID

    Returns:
        新创建的方案副本
    """
    source = get_plan(config_name, plan_id)
    if not source:
        logger.warning(f"方案不存在: {plan_id}")
        return None

    new_name = f"{source.get('name', '未命名')} (副本)"
    new_params = source.get("params", {}).copy()

    return create_plan(config_name, new_name, new_params)


def get_enabled_plans(config_name: str) -> List[Dict]:
    """
    获取所有启用的方案

    Args:
        config_name: 配置名称

    Returns:
        启用的方案列表
    """
    plans = load_plans(config_name)
    return [p for p in plans if p.get("enabled", True)]


def plans_summary(config_name: str) -> Dict[str, Any]:
    """
    获取方案摘要信息

    Args:
        config_name: 配置名称

    Returns:
        摘要信息字典
    """
    plans = load_plans(config_name)
    enabled = [p for p in plans if p.get("enabled", True)]

    return {
        "total": len(plans),
        "enabled": len(enabled),
        "disabled": len(plans) - len(enabled),
        "plans": [{"id": p.get("id"), "name": p.get("name"), "enabled": p.get("enabled", True)} for p in plans],
    }
