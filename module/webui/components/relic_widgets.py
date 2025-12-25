"""
Relic management UI widgets.

Provides reusable components for the redesigned relic enhancement interface.
"""

from __future__ import annotations
from typing import List, Dict, Callable, Optional, Any

from pywebio.output import (
    put_text,
    put_buttons,
    put_row,
    put_column,
    put_scope,
    put_collapse,
    use_scope,
    Output,
)
from pywebio.pin import pin, pin_on_change
from pywebio.input import input_update as pw_input_update

from module.webui.pin import put_checkbox, put_input, put_select
from module.webui.lang import t
from module.logger import logger


# Available substat slugs for relic enhancement
ALL_SUBSTAT_SLUGS = [
    'spd', 'crit_rate', 'crit_dmg', 'break',
    'atk_pct', 'hp_pct', 'def_pct', 'eff_hit', 'eff_res',
    'atk_flat', 'hp_flat', 'def_flat'  # 固定值词条
]

# Slot options for relic enhancement
SLOT_OPTIONS = [
    {"slug": "head", "label": "头部"},
    {"slug": "hands", "label": "手部"},
    {"slug": "body", "label": "躯干"},
    {"slug": "feet", "label": "脚部"},
    {"slug": "sphere", "label": "位面球"},
    {"slug": "rope", "label": "连结绳"},
]

# 外圈遗器部位
OUTER_SLOT_OPTIONS = [
    {"slug": "head", "label": "头部"},
    {"slug": "hands", "label": "手部"},
    {"slug": "body", "label": "躯干"},
    {"slug": "feet", "label": "脚部"},
]

# 内圈位面饰品部位
INNER_SLOT_OPTIONS = [
    {"slug": "sphere", "label": "位面球"},
    {"slug": "rope", "label": "连结绳"},
]


def is_inner_relic_set(filter_name: str) -> bool:
    """判断套装是否为内圈（位面饰品）

    Args:
        filter_name: 套装中文名称

    Returns:
        True 表示内圈饰品，False 表示外圈遗器
    """
    if not filter_name:
        return False  # 空选择默认外圈
    try:
        from tasks.relics.keywords import relicset as relicset_mod
        for obj in relicset_mod.RelicSet.instances.values():
            if getattr(obj, 'cn', '') == filter_name:
                return getattr(obj, 'is_inner', False)
    except Exception:
        pass
    return False

# Substat options with Chinese labels
SUBSTAT_OPTIONS = [
    {"slug": "spd", "label": "速度"},
    {"slug": "crit_rate", "label": "暴击率"},
    {"slug": "crit_dmg", "label": "暴击伤害"},
    {"slug": "break", "label": "击破特攻"},
    {"slug": "atk_pct", "label": "攻击%"},
    {"slug": "hp_pct", "label": "生命%"},
    {"slug": "def_pct", "label": "防御%"},
    {"slug": "eff_hit", "label": "效果命中"},
    {"slug": "eff_res", "label": "效果抵抗"},
    # 固定值词条
    {"slug": "atk_flat", "label": "攻击"},
    {"slug": "hp_flat", "label": "生命"},
    {"slug": "def_flat", "label": "防御"},
]

# Main stat options for body piece
MAIN_STAT_BODY_OPTIONS = [
    {"slug": "crit_rate", "label": "暴击率"},
    {"slug": "crit_dmg", "label": "暴击伤害"},
    {"slug": "atk_pct", "label": "攻击%"},
    {"slug": "hp_pct", "label": "生命%"},
    {"slug": "def_pct", "label": "防御%"},
    {"slug": "eff_hit", "label": "效果命中"},
    {"slug": "heal", "label": "治疗量加成"},
]

# Main stat options for feet piece
MAIN_STAT_FEET_OPTIONS = [
    {"slug": "spd", "label": "速度"},
    {"slug": "atk_pct", "label": "攻击%"},
    {"slug": "hp_pct", "label": "生命%"},
    {"slug": "def_pct", "label": "防御%"},
]

# Main stat options for sphere piece (planar ornament)
MAIN_STAT_SPHERE_OPTIONS = [
    {"slug": "hp_pct", "label": "生命%"},
    {"slug": "atk_pct", "label": "攻击%"},
    {"slug": "def_pct", "label": "防御%"},
    {"slug": "physical_dmg", "label": "物理伤害"},
    {"slug": "fire_dmg", "label": "火伤害"},
    {"slug": "ice_dmg", "label": "冰伤害"},
    {"slug": "thunder_dmg", "label": "雷伤害"},
    {"slug": "wind_dmg", "label": "风伤害"},
    {"slug": "quantum_dmg", "label": "量子伤害"},
    {"slug": "imaginary_dmg", "label": "虚数伤害"},
]

# Main stat options for rope piece (link rope)
MAIN_STAT_ROPE_OPTIONS = [
    {"slug": "hp_pct", "label": "生命值%"},
    {"slug": "atk_pct", "label": "攻击力%"},
    {"slug": "def_pct", "label": "防御力%"},
    {"slug": "eer", "label": "能量恢复效率"},
]

# Slug to Chinese label mapping
SLUG_TO_CN = {opt["slug"]: opt["label"] for opt in SUBSTAT_OPTIONS}
SLUG_TO_CN.update({opt["slug"]: opt["label"] for opt in MAIN_STAT_BODY_OPTIONS})
SLOT_SLUG_TO_CN = {opt["slug"]: opt["label"] for opt in SLOT_OPTIONS}


def checkbox_grid(
    pin_name: str,
    grid_name: str,
    const_key: str,
    current_value: str,
    scope: str,
    all_slugs: List[str],
    label_fn: Callable[[str], str],
    modified_queue: Any,
    suspend_keys: set,
    show_global_reset: bool = True,
) -> List[Output]:
    """
    Create a checkbox grid widget with sync to a comma-separated input field.
    
    Reuses the logic from app.py:389-528 but extracted as a reusable component.
    
    Args:
        pin_name: Name of the hidden input field (comma-separated string)
        grid_name: Name of the checkbox grid widget
        const_key: Config key path (e.g., "RelicsEnhance.RelicsEnhance.HeadHandsDesired")
        current_value: Current comma-separated value
        scope: CSS scope selector
        all_slugs: List of all available slug options
        label_fn: Function to translate slug to display label
        modified_queue: Queue to push config changes
        suspend_keys: Set to track suspended watchers (avoid loops)
        show_global_reset: Whether to show "用全局" button
        
    Returns:
        List of Output widgets (grid + buttons)
    """
    # Parse current value
    if isinstance(current_value, str):
        current = [p.strip() for p in current_value.split(',') if p.strip()]
    elif isinstance(current_value, (list, tuple)):
        current = list(current_value)
    else:
        current = []
    
    initial_sel_set = set(current)
    initializing = [True]
    
    # Create checkbox grid
    options = [{"label": label_fn(slug), "value": slug} for slug in all_slugs]
    grid = put_checkbox(name=grid_name, options=options, inline=True, value=current)
    grid.spec["scope"] = scope
    grid.style("display:grid;grid-template-columns:repeat(3,1fr);column-gap:24px;align-items:center;")
    
    # Helper: update main input field
    def _update_main_input(value_str: str):
        logger.debug(f"[RelicsWidget] update_main_input {const_key} -> {value_str}")
        try:
            suspend_keys.add(const_key)
            pin[pin_name] = value_str
            pw_input_update(pin_name, value=value_str)
        except Exception:
            pass
        finally:
            try:
                suspend_keys.discard(const_key)
            except Exception:
                pass
    
    # Grid change handler
    def _grid_change(_: any):
        try:
            sel = pin[grid_name] or []
        except Exception:
            sel = []
        sel_str = ",".join(sel)
        logger.info(f"[RelicsWidget] checkbox merge {const_key} -> {sel_str}")
        _update_main_input(sel_str)
        try:
            if not initializing[0] or set(sel) != initial_sel_set:
                modified_queue.put({"name": const_key, "value": sel_str})
        except Exception:
            pass
    
    pin_on_change(grid_name, _grid_change)
    
    # Initialize
    _update_main_input(",".join(current))
    initializing[0] = False
    
    # Sync from input field to grid
    def _sync_from_input(_: any):
        try:
            val = pin[pin_name]
            logger.debug(f"[RelicsWidget] input change {pin_name} -> {val}")
        except Exception:
            val = ""
        if isinstance(val, str):
            want = [p.strip() for p in val.split(',') if p.strip()]
        elif isinstance(val, (list, tuple)):
            want = list(val)
        else:
            want = []
        logger.debug(f"[RelicsWidget] sync_from_input {const_key} -> {want}")
        try:
            pw_input_update(grid_name, value=want)
            pin[grid_name] = want
        except Exception:
            pass
    
    pin_on_change(pin_name, _sync_from_input)
    
    # Action buttons
    def _apply_all(clear=False):
        want = [] if clear else all_slugs
        logger.info(f"[RelicsWidget] apply_all {const_key} clear={clear} -> {want}")
        try:
            pw_input_update(grid_name, value=want)
            pin[grid_name] = want
        except Exception:
            pass
        sel_str = ",".join(want)
        _update_main_input(sel_str)
        try:
            modified_queue.put({"name": const_key, "value": sel_str})
        except Exception:
            pass
    
    def _global_reset():
        _update_main_input('')
        try:
            pw_input_update(grid_name, value=[])
            pin[grid_name] = []
        except Exception:
            pass
        try:
            modified_queue.put({"name": const_key, "value": ''})
        except Exception:
            pass
    
    # Build button row
    btns = [
        {"label": '全选', "value": 0, "color": 'off'},
        {"label": '清空', "value": 1, "color": 'off'},
    ]
    onclick_handlers = [
        lambda: _apply_all(False),
        lambda: _apply_all(True),
    ]
    
    if show_global_reset:
        btns.append({"label": '用全局', "value": 2, "color": 'off'})
        onclick_handlers.append(_global_reset)
    
    btn_row = put_buttons(btns, onclick=onclick_handlers)
    btn_row.spec["scope"] = scope
    
    return [grid, btn_row]


def threshold_slider_row(
    level: int,
    pin_name: str,
    current_value: int,
    min_val: int,
    max_val: int,
    scope: str,
) -> Output:
    """
    Create a threshold slider row for a specific enhancement level.
    
    Args:
        level: Enhancement level (0, 3, 6, 9, 12, 15)
        pin_name: Name of the input pin
        current_value: Current threshold value
        min_val: Minimum allowed value
        max_val: Maximum allowed value
        scope: CSS scope selector
        
    Returns:
        Output widget containing the slider row
    """
    # For now, use a simple number input
    # TODO: Add actual slider when PyWebIO slider is available
    label = f"Lv {level} {'入场门槛' if level == 0 else '继续阈值' if level < 15 else '保留阈值'}"
    
    row = put_row([
        put_text(label).style("flex: 0 0 120px;"),
        put_input(
            name=pin_name,
            type="number",
            value=current_value,
            help_text=f"范围: {min_val}-{max_val}",
        ).style("flex: 1;"),
        put_text(f"{current_value} 次命中").style("flex: 0 0 80px;"),
    ])
    row.spec["scope"] = scope
    return row


def preset_toggle_section(
    toggle_pin_name: str,
    current_preset: bool,
    preset_label: str,
    custom_content_scope: str,
) -> List[Output]:
    """
    Create a preset/custom toggle section.
    
    Args:
        toggle_pin_name: Name of the toggle pin
        current_preset: Current state (True = use preset, False = custom)
        preset_label: Label for the preset option
        custom_content_scope: Scope name for custom content (will be shown/hidden)
        
    Returns:
        List of Output widgets
    """
    from pywebio.output import put_html
    
    toggle = put_select(
        name=toggle_pin_name,
        options=[
            ("使用预设规则", True),
            ("自定义配置", False),
        ],
        value=current_preset,
    )
    
    # Show/hide custom content based on toggle
    def _toggle_change(_: any):
        use_preset = pin[toggle_pin_name]
        display = "none" if use_preset else "block"
        # TODO: Implement scope visibility toggle via JS
        logger.info(f"[RelicsWidget] preset toggle: {use_preset}")
    
    pin_on_change(toggle_pin_name, _toggle_change)
    
    preset_hint = put_text(f"当前使用 {preset_label} 预设规则").style(
        "color: #666; font-size: 0.9em; margin-top: 8px;"
    )
    
    return [toggle, preset_hint]


def part_config_section(
    part_name: str,
    part_label: str,
    has_scenarios: bool,
    scope: str,
) -> Output:
    """
    Create a configuration section for a specific relic part.

    Args:
        part_name: Internal part name (e.g., "feet", "body")
        part_label: Display label (e.g., "脚部", "衣服")
        has_scenarios: Whether this part has scenario-specific config
        scope: CSS scope selector

    Returns:
        Output widget containing the part section
    """
    content = [
        put_text(f"🔹 {part_label}").style("font-weight: bold; margin-bottom: 8px;"),
        put_scope(f"{scope}_main_whitelist"),
        put_scope(f"{scope}_global_desired"),
    ]

    if has_scenarios:
        content.extend([
            put_collapse(
                title="场景特定配置（可选）",
                content=[
                    put_scope(f"{scope}_scenario_1"),
                    put_scope(f"{scope}_scenario_2"),
                ],
                open=False,
            )
        ])

    section = put_scope(scope, content)
    return section


def slot_checkbox_grid(
    pin_name: str,
    grid_name: str,
    const_key: str,
    current_value: str,
    scope: str,
    modified_queue: Any,
    suspend_keys: set,
) -> List[Output]:
    """
    Create a slot selection checkbox grid for relic enhancement.

    Args:
        pin_name: Name of the hidden input field (comma-separated string)
        grid_name: Name of the checkbox grid widget
        const_key: Config key path
        current_value: Current comma-separated value (e.g., "head,hands,body,feet")
        scope: CSS scope selector
        modified_queue: Queue to push config changes
        suspend_keys: Set to track suspended watchers

    Returns:
        List of Output widgets
    """
    all_slugs = [opt["slug"] for opt in SLOT_OPTIONS]
    label_fn = lambda slug: SLOT_SLUG_TO_CN.get(slug, slug)

    return checkbox_grid(
        pin_name=pin_name,
        grid_name=grid_name,
        const_key=const_key,
        current_value=current_value,
        scope=scope,
        all_slugs=all_slugs,
        label_fn=label_fn,
        modified_queue=modified_queue,
        suspend_keys=suspend_keys,
        show_global_reset=False,
    )


def substat_checkbox_grid(
    pin_name: str,
    grid_name: str,
    const_key: str,
    current_value: str,
    scope: str,
    modified_queue: Any,
    suspend_keys: set,
) -> List[Output]:
    """
    Create a substat selection checkbox grid for relic enhancement.

    Args:
        pin_name: Name of the hidden input field (comma-separated string)
        grid_name: Name of the checkbox grid widget
        const_key: Config key path
        current_value: Current comma-separated value (e.g., "spd,crit_rate,crit_dmg")
        scope: CSS scope selector
        modified_queue: Queue to push config changes
        suspend_keys: Set to track suspended watchers

    Returns:
        List of Output widgets
    """
    all_slugs = [opt["slug"] for opt in SUBSTAT_OPTIONS]
    label_fn = lambda slug: SLUG_TO_CN.get(slug, slug)

    return checkbox_grid(
        pin_name=pin_name,
        grid_name=grid_name,
        const_key=const_key,
        current_value=current_value,
        scope=scope,
        all_slugs=all_slugs,
        label_fn=label_fn,
        modified_queue=modified_queue,
        suspend_keys=suspend_keys,
        show_global_reset=False,
    )


def main_stat_body_checkbox_grid(
    pin_name: str,
    grid_name: str,
    const_key: str,
    current_value: str,
    scope: str,
    modified_queue: Any,
    suspend_keys: set,
) -> List[Output]:
    """
    Create a main stat selection checkbox grid for body piece.

    Args:
        pin_name: Name of the hidden input field (comma-separated string)
        grid_name: Name of the checkbox grid widget
        const_key: Config key path
        current_value: Current comma-separated value
        scope: CSS scope selector
        modified_queue: Queue to push config changes
        suspend_keys: Set to track suspended watchers

    Returns:
        List of Output widgets
    """
    all_slugs = [opt["slug"] for opt in MAIN_STAT_BODY_OPTIONS]
    label_fn = lambda slug: SLUG_TO_CN.get(slug, slug)

    return checkbox_grid(
        pin_name=pin_name,
        grid_name=grid_name,
        const_key=const_key,
        current_value=current_value,
        scope=scope,
        all_slugs=all_slugs,
        label_fn=label_fn,
        modified_queue=modified_queue,
        suspend_keys=suspend_keys,
        show_global_reset=True,
    )


def main_stat_feet_checkbox_grid(
    pin_name: str,
    grid_name: str,
    const_key: str,
    current_value: str,
    scope: str,
    modified_queue: Any,
    suspend_keys: set,
) -> List[Output]:
    """
    Create a main stat selection checkbox grid for feet piece.

    Args:
        pin_name: Name of the hidden input field (comma-separated string)
        grid_name: Name of the checkbox grid widget
        const_key: Config key path
        current_value: Current comma-separated value
        scope: CSS scope selector
        modified_queue: Queue to push config changes
        suspend_keys: Set to track suspended watchers

    Returns:
        List of Output widgets
    """
    all_slugs = [opt["slug"] for opt in MAIN_STAT_FEET_OPTIONS]
    label_fn = lambda slug: SLUG_TO_CN.get(slug, slug)

    return checkbox_grid(
        pin_name=pin_name,
        grid_name=grid_name,
        const_key=const_key,
        current_value=current_value,
        scope=scope,
        all_slugs=all_slugs,
        label_fn=label_fn,
        modified_queue=modified_queue,
        suspend_keys=suspend_keys,
        show_global_reset=True,
    )


def main_stat_sphere_checkbox_grid(
    pin_name: str,
    grid_name: str,
    const_key: str,
    current_value: str,
    scope: str,
    modified_queue: Any,
    suspend_keys: set,
) -> List[Output]:
    """
    Create a main stat selection checkbox grid for sphere piece.

    Args:
        pin_name: Name of the hidden input field (comma-separated string)
        grid_name: Name of the checkbox grid widget
        const_key: Config key path
        current_value: Current comma-separated value
        scope: CSS scope selector
        modified_queue: Queue to push config changes
        suspend_keys: Set to track suspended watchers

    Returns:
        List of Output widgets
    """
    all_slugs = [opt["slug"] for opt in MAIN_STAT_SPHERE_OPTIONS]
    label_fn = lambda slug: SLUG_TO_CN.get(slug, slug)

    return checkbox_grid(
        pin_name=pin_name,
        grid_name=grid_name,
        const_key=const_key,
        current_value=current_value,
        scope=scope,
        all_slugs=all_slugs,
        label_fn=label_fn,
        modified_queue=modified_queue,
        suspend_keys=suspend_keys,
        show_global_reset=True,
    )


def main_stat_rope_checkbox_grid(
    pin_name: str,
    grid_name: str,
    const_key: str,
    current_value: str,
    scope: str,
    modified_queue: Any,
    suspend_keys: set,
) -> List[Output]:
    """
    Create a main stat selection checkbox grid for rope piece.

    Args:
        pin_name: Name of the hidden input field (comma-separated string)
        grid_name: Name of the checkbox grid widget
        const_key: Config key path
        current_value: Current comma-separated value
        scope: CSS scope selector
        modified_queue: Queue to push config changes
        suspend_keys: Set to track suspended watchers

    Returns:
        List of Output widgets
    """
    all_slugs = [opt["slug"] for opt in MAIN_STAT_ROPE_OPTIONS]
    label_fn = lambda slug: SLUG_TO_CN.get(slug, slug)

    return checkbox_grid(
        pin_name=pin_name,
        grid_name=grid_name,
        const_key=const_key,
        current_value=current_value,
        scope=scope,
        all_slugs=all_slugs,
        label_fn=label_fn,
        modified_queue=modified_queue,
        suspend_keys=suspend_keys,
        show_global_reset=True,
    )


# =============================================================================
# 方案管理 UI 组件
# =============================================================================

def get_relic_set_options() -> List[Dict[str, str]]:
    """
    获取遗器套装选项列表

    Returns:
        套装选项列表 [{"label": "显示名", "value": "值"}, ...]
    """
    options = [{"label": "全部/不筛选", "value": ""}]

    try:
        from tasks.relics.keywords import relicset as relicset_mod

        # 获取所有遗器套装实例
        for name, obj in vars(relicset_mod).items():
            if not name.startswith('_') and hasattr(obj, 'cn'):
                cn_name = getattr(obj, 'cn', name)
                if hasattr(obj, 'is_outer') and obj.is_outer:
                    options.append({"label": f"[遗器] {cn_name}", "value": cn_name})
                elif hasattr(obj, 'is_inner') and obj.is_inner:
                    options.append({"label": f"[饰品] {cn_name}", "value": cn_name})
    except Exception as e:
        logger.warning(f"加载遗器套装列表失败: {e}")
        # 添加一些常用套装作为备选
        fallback_sets = [
            "快枪手的野穴冒险",
            "铁骑之将",
            "过客",
            "云无留迹的过客",
            "野穴星的骑士",
            "仙舟罗浮的信使",
            "流星追迹的怪盗",
            "盗匪荒漠的废土客",
            "太空封印站",
            "不老者的仙舟",
            "泛银河商业公司",
            "差分宇宙",
        ]
        for name in fallback_sets:
            options.append({"label": name, "value": name})

    return options


def relic_set_dropdown(
    pin_name: str,
    current_value: str,
    scope: str,
    on_change: Optional[Callable[[str], None]] = None,
) -> Output:
    """
    套装筛选下拉框

    Args:
        pin_name: pin 名称
        current_value: 当前值
        scope: CSS scope
        on_change: 值变化回调

    Returns:
        Output widget
    """
    options = get_relic_set_options()

    dropdown = put_select(
        name=pin_name,
        label="套装筛选",
        options=[(opt["label"], opt["value"]) for opt in options],
        value=current_value,
        help_text="选择要强化的遗器套装，留空则处理所有遗器",
    )

    if on_change:
        def _on_change(_):
            try:
                val = pin[pin_name]
                on_change(val)
            except Exception as e:
                logger.error(f"套装选择回调失败: {e}")

        pin_on_change(pin_name, _on_change)

    return dropdown


def render_plan_list(
    plans: List[Dict],
    on_edit: Callable[[str], None],
    on_delete: Callable[[str], None],
    on_toggle: Callable[[str], None],
    on_move_up: Callable[[str], None],
    on_move_down: Callable[[str], None],
) -> None:
    """
    直接渲染方案列表到当前 scope（不返回 Output 列表）

    使用 PyWebIO 原生组件避免 put_html() 导致的 DOM 合并问题。
    布局方案A：按钮在卡片内部右侧，信息在左侧两行显示。
    """
    if not plans:
        put_text("暂无方案，点击下方按钮新建").style("color: #888; padding: 8px 0;")
        return

    # 直接渲染每个方案
    for idx, plan in enumerate(plans):
        plan_id = plan.get("id", "")
        plan_name = plan.get("name", "未命名")
        enabled = plan.get("enabled", True)
        params = plan.get("params", {})

        # 摘要信息
        filter_name = params.get("filter_name", "") or "全部"
        substats = params.get("substats", [])
        substats_display = ", ".join([SLUG_TO_CN.get(s, s) for s in substats[:3]])
        if len(substats) > 3:
            substats_display += "..."

        # 状态样式
        status_dot = "🟢" if enabled else "🔴"
        bg_color = "#f8fff8" if enabled else "#fff8f8"
        border_color = "#c3e6c3" if enabled else "#e6c3c3"
        filter_info = f"{filter_name} | {substats_display}" if filter_name != "全部" else substats_display

        # 卡片布局：左侧信息 + 右侧按钮
        put_row([
            # 左侧：名称和词条信息（两行）
            put_column([
                put_text(f"{status_dot} {plan_name}").style("font-weight: 500; font-size: 14px; margin-bottom: 4px;"),
                put_text(filter_info).style("color: #666; font-size: 0.85em; padding-left: 22px;"),
            ]).style("flex: 1; min-width: 0;"),
            # 右侧：操作按钮
            put_buttons(
                [
                    {"label": "禁用" if enabled else "启用", "value": "toggle", "color": "secondary" if enabled else "success"},
                    {"label": "编辑", "value": "edit", "color": "info"},
                    {"label": "↑", "value": "up", "color": "light"},
                    {"label": "↓", "value": "down", "color": "light"},
                    {"label": "×", "value": "delete", "color": "danger"},
                ],
                onclick=[
                    lambda pid=plan_id: on_toggle(pid),
                    lambda pid=plan_id: on_edit(pid),
                    lambda pid=plan_id: on_move_up(pid),
                    lambda pid=plan_id: on_move_down(pid),
                    lambda pid=plan_id: on_delete(pid),
                ],
                small=True,
            ).style("flex-shrink: 0; margin: 0;"),
        ]).style(f"display: flex; align-items: center; padding: 10px 12px; background: {bg_color}; border: 1px solid {border_color}; border-radius: 8px; margin-bottom: 8px;")


def _create_slot_widgets(scope: str, is_inner: bool, params: Dict) -> List:
    """根据套装类型创建部位选择widgets

    Args:
        scope: pin名称前缀
        is_inner: 是否为内圈套装
        params: 当前参数值

    Returns:
        部位选择widgets列表
    """
    from pywebio.output import put_html

    slot_options = INNER_SLOT_OPTIONS if is_inner else OUTER_SLOT_OPTIONS
    valid_slugs = {opt["slug"] for opt in slot_options}

    # 过滤掉不属于当前类型的已选部位
    current_slots = params.get("check_slots", [])
    filtered_slots = [s for s in current_slots if s in valid_slugs]

    widgets = []
    widgets.append(put_html("<div style='margin-top: 16px;'><b>强化部位</b></div>"))
    slot_grid = put_checkbox(
        name=f"{scope}_slots",
        options=[{"label": opt["label"], "value": opt["slug"]} for opt in slot_options],
        value=filtered_slots,
        inline=True,
    )
    slot_grid.style("display:grid;grid-template-columns:repeat(3,minmax(70px,1fr));column-gap:16px;row-gap:8px;")
    widgets.append(slot_grid)
    return widgets


def _create_main_stat_widgets(scope: str, is_inner: bool, params: Dict) -> List:
    """根据套装类型创建主词条筛选widgets

    Args:
        scope: pin名称前缀
        is_inner: 是否为内圈套装
        params: 当前参数值

    Returns:
        主词条筛选widgets列表
    """
    from pywebio.output import put_html

    widgets = []

    if is_inner:
        # 内圈：位面球、连结绳
        widgets.append(put_html("<div style='margin-top: 16px;'><b>位面球主词条约束</b> <span style='color:#888;'>(留空接受任意)</span></div>"))
        sphere_grid = put_checkbox(
            name=f"{scope}_main_sphere",
            options=[{"label": opt["label"], "value": opt["slug"]} for opt in MAIN_STAT_SPHERE_OPTIONS],
            value=params.get("main_stat_sphere", []),
            inline=True,
        )
        sphere_grid.style("display:grid;grid-template-columns:repeat(5,minmax(70px,1fr));column-gap:12px;row-gap:8px;")
        widgets.append(sphere_grid)

        widgets.append(put_html("<div style='margin-top: 16px;'><b>连结绳主词条约束</b> <span style='color:#888;'>(留空接受任意)</span></div>"))
        rope_grid = put_checkbox(
            name=f"{scope}_main_rope",
            options=[{"label": opt["label"], "value": opt["slug"]} for opt in MAIN_STAT_ROPE_OPTIONS],
            value=params.get("main_stat_rope", []),
            inline=True,
        )
        rope_grid.style("display:grid;grid-template-columns:repeat(4,minmax(70px,1fr));column-gap:12px;row-gap:8px;")
        widgets.append(rope_grid)
    else:
        # 外圈：躯干、脚部
        widgets.append(put_html("<div style='margin-top: 16px;'><b>躯干主词条约束</b> <span style='color:#888;'>(留空接受任意)</span></div>"))
        body_grid = put_checkbox(
            name=f"{scope}_main_body",
            options=[{"label": opt["label"], "value": opt["slug"]} for opt in MAIN_STAT_BODY_OPTIONS],
            value=params.get("main_stat_body", []),
            inline=True,
        )
        body_grid.style("display:grid;grid-template-columns:repeat(4,minmax(70px,1fr));column-gap:12px;row-gap:8px;")
        widgets.append(body_grid)

        widgets.append(put_html("<div style='margin-top: 16px;'><b>脚部主词条约束</b> <span style='color:#888;'>(留空接受任意)</span></div>"))
        feet_grid = put_checkbox(
            name=f"{scope}_main_feet",
            options=[{"label": opt["label"], "value": opt["slug"]} for opt in MAIN_STAT_FEET_OPTIONS],
            value=params.get("main_stat_feet", []),
            inline=True,
        )
        feet_grid.style("display:grid;grid-template-columns:repeat(4,minmax(60px,1fr));column-gap:12px;row-gap:8px;")
        widgets.append(feet_grid)

    return widgets


def plan_edit_form(
    plan: Optional[Dict],
    on_save: Callable[[Dict], None],
    on_cancel: Callable[[], None],
    scope: str = "plan_edit_form",
    modified_queue: Optional[Any] = None,
) -> List[Output]:
    """
    方案编辑表单

    Args:
        plan: 要编辑的方案（None 表示新建）
        on_save: 保存回调，接收完整的方案数据
        on_cancel: 取消回调
        scope: CSS scope
        modified_queue: 配置修改队列（用于 checkbox_grid）

    Returns:
        Output widget list
    """
    from pywebio.output import put_html

    is_new = plan is None
    plan = plan or {}
    params = plan.get("params", {})

    # 默认参数
    default_params = {
        "filter_name": "",
        "check_slots": ["head", "hands", "body", "feet"],
        "substats": ["spd", "crit_rate", "crit_dmg"],
        "main_stat_body": [],
        "main_stat_feet": [],
        "min_hits_0": 1,
        "min_hits_3": 1,
        "min_hits_6": 2,
        "min_hits_9": 3,
        "stop_if_fail": True,
        "discard_trash": True,
    }

    for k, v in default_params.items():
        if k not in params:
            params[k] = v

    outputs = []

    # 标题
    title = "新建方案" if is_new else f"编辑方案: {plan.get('name', '')}"
    outputs.append(put_html(f"<h3>{title}</h3>"))

    # 方案名称
    name_input = put_input(
        name=f"{scope}_name",
        label="方案名称",
        value=plan.get("name", ""),
    )
    outputs.append(name_input)

    # 套装筛选 - 使用下拉选择器
    filter_select = put_select(
        name=f"{scope}_filter",
        label="套装筛选",
        options=[(opt["label"], opt["value"]) for opt in get_relic_set_options()],
        value=params.get("filter_name", ""),
        help_text="选择要强化的遗器套装，留空则处理所有遗器",
    )
    outputs.append(filter_select)

    # 判断初始套装类型
    initial_is_inner = is_inner_relic_set(params.get("filter_name", ""))

    # 部位选择容器 - 动态显示内圈/外圈部位
    slot_widgets = _create_slot_widgets(scope, initial_is_inner, params)
    outputs.append(put_scope(f"{scope}_slots_container", content=slot_widgets))

    # 有效副词条
    outputs.append(put_html("<div style='margin-top: 16px;'><b>有效副词条</b></div>"))
    substat_grid = put_checkbox(
        name=f"{scope}_substats",
        options=[{"label": opt["label"], "value": opt["slug"]} for opt in SUBSTAT_OPTIONS],
        value=params.get("substats", []),
        inline=True,
    )
    substat_grid.style("display:grid;grid-template-columns:repeat(3,minmax(80px,1fr));column-gap:16px;row-gap:8px;")
    outputs.append(substat_grid)

    # 主词条约束容器 - 动态显示内圈/外圈主词条
    main_stat_widgets = _create_main_stat_widgets(scope, initial_is_inner, params)
    outputs.append(put_scope(f"{scope}_main_stats_container", content=main_stat_widgets))

    # 套装变化时更新部位和主词条显示
    def on_filter_change(_):
        try:
            filter_name = pin[f"{scope}_filter"] or ""
            is_inner = is_inner_relic_set(filter_name)

            # 保存当前已选的部位和主词条到params
            for slot_type in ["body", "feet", "sphere", "rope"]:
                try:
                    val = pin[f"{scope}_main_{slot_type}"]
                    if val is not None:
                        params[f"main_stat_{slot_type}"] = val
                except Exception:
                    pass
            try:
                val = pin[f"{scope}_slots"]
                if val is not None:
                    params["check_slots"] = val
            except Exception:
                pass

            # 更新部位选择
            with use_scope(f"{scope}_slots_container", clear=True):
                for w in _create_slot_widgets(scope, is_inner, params):
                    w.show()

            # 更新主词条筛选
            with use_scope(f"{scope}_main_stats_container", clear=True):
                for w in _create_main_stat_widgets(scope, is_inner, params):
                    w.show()
        except Exception as e:
            logger.error(f"套装筛选变化回调出错: {e}")

    pin_on_change(f"{scope}_filter", on_filter_change)

    # 阈值设置 - 使用 (label, value) 元组格式，支持 0.5 间隔
    outputs.append(put_html("<div style='margin-top: 16px;'><b>阈值设置</b></div>"))
    threshold_options = [(str(v), v) for v in [0, 0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5]]
    threshold_row = put_row([
        put_select(name=f"{scope}_min0", label="+0级", options=threshold_options, value=params.get("min_hits_0", 1)),
        put_select(name=f"{scope}_min3", label="+3级", options=threshold_options, value=params.get("min_hits_3", 1)),
        put_select(name=f"{scope}_min6", label="+6级", options=threshold_options, value=params.get("min_hits_6", 2)),
        put_select(name=f"{scope}_min9", label="+9级", options=threshold_options, value=params.get("min_hits_9", 3)),
        put_select(name=f"{scope}_save_threshold", label="保存阈值", options=threshold_options, value=params.get("save_threshold", 5)),
    ])
    outputs.append(threshold_row)

    # 选项开关
    outputs.append(put_html("<div style='margin-top: 16px;'><b>选项</b></div>"))
    options_grid = put_checkbox(
        name=f"{scope}_options",
        options=[
            {"label": "未达标时停止强化", "value": "stop_if_fail"},
            {"label": "弃置不达标遗器", "value": "discard_trash"},
        ],
        value=[
            k for k in ["stop_if_fail", "discard_trash"]
            if params.get(k, True)
        ],
        inline=True,
    )
    outputs.append(options_grid)

    # ==================== 高级选项 ====================
    advanced = params.get("advanced", {})

    # 高级选项折叠区
    advanced_content = []

    # --- 1. 部位独立阈值 ---
    slot_thresholds = advanced.get("slot_thresholds", {})
    adv_slot_enabled = slot_thresholds.get("enabled", False)

    # 启用开关
    adv_slot_switch = put_checkbox(
        name=f"{scope}_adv_slot_enabled",
        options=[{"label": "启用部位独立阈值", "value": "enabled"}],
        value=["enabled"] if adv_slot_enabled else [],
        inline=True,
    )
    advanced_content.append(adv_slot_switch)

    # 部位组阈值编辑器
    slot_groups = [
        ("head_hands", "头部/手部"),
        ("body", "躯干"),
        ("feet", "脚部"),
        ("sphere", "位面球"),
        ("rope", "连结绳"),
    ]
    overrides = slot_thresholds.get("overrides", {})

    for group_key, group_label in slot_groups:
        group_overrides = overrides.get(group_key, {})
        advanced_content.append(put_html(f"<div style='margin-top:8px;color:#666;'><b>{group_label}</b></div>"))
        threshold_row = put_row([
            put_select(
                name=f"{scope}_adv_{group_key}_0",
                label="+0",
                options=[("继承", -1)] + [(str(i), i) for i in range(5)],
                value=group_overrides.get("min_hits_0", -1),
            ),
            put_select(
                name=f"{scope}_adv_{group_key}_3",
                label="+3",
                options=[("继承", -1)] + [(str(i), i) for i in range(5)],
                value=group_overrides.get("min_hits_3", -1),
            ),
            put_select(
                name=f"{scope}_adv_{group_key}_6",
                label="+6",
                options=[("继承", -1)] + [(str(i), i) for i in range(5)],
                value=group_overrides.get("min_hits_6", -1),
            ),
            put_select(
                name=f"{scope}_adv_{group_key}_9",
                label="+9",
                options=[("继承", -1)] + [(str(i), i) for i in range(5)],
                value=group_overrides.get("min_hits_9", -1),
            ),
        ])
        advanced_content.append(threshold_row)

    advanced_content.append(put_html("<hr style='margin:16px 0;border-color:#ddd;'>"))

    # --- 2. 词条权重系统 ---
    weights_config = advanced.get("weights", {})
    adv_weights_enabled = weights_config.get("enabled", False)

    adv_weights_switch = put_checkbox(
        name=f"{scope}_adv_weights_enabled",
        options=[{"label": "启用词条权重系统", "value": "enabled"}],
        value=["enabled"] if adv_weights_enabled else [],
        inline=True,
    )
    advanced_content.append(adv_weights_switch)

    # 权重编辑表格
    global_weights = weights_config.get("global", {})
    weight_options = [("0", 0.0), ("0.5", 0.5), ("1.0", 1.0), ("1.5", 1.5), ("2.0", 2.0)]

    advanced_content.append(put_html("<div style='margin-top:8px;color:#666;'>全局权重</div>"))
    weight_rows = []
    # 获取默认权重作为回退值
    from module.webui.relic_plans import get_default_advanced_params
    default_global_weights = get_default_advanced_params()["weights"]["global"]
    for substat in SUBSTAT_OPTIONS:
        slug = substat["slug"]
        label = substat["label"]
        current_weight = global_weights.get(slug, default_global_weights.get(slug, 1.0))
        weight_rows.append(
            put_row([
                put_html(f"<span style='min-width:70px;display:inline-block;'>{label}</span>"),
                put_select(
                    name=f"{scope}_adv_weight_{slug}",
                    label="",
                    options=weight_options,
                    value=current_weight,
                ),
            ], size="auto 100px")
        )
    # 分3列显示权重
    for i in range(0, len(weight_rows), 3):
        row_items = weight_rows[i:i+3]
        advanced_content.append(put_row(row_items))

    advanced_content.append(put_html("<hr style='margin:16px 0;border-color:#ddd;'>"))

    # --- 3. 3初始探索模式 ---
    three_init = advanced.get("three_init_explore", {})
    adv_3init_enabled = three_init.get("enabled", False)

    adv_3init_switch = put_checkbox(
        name=f"{scope}_adv_3init_enabled",
        options=[{"label": "启用3初始探索模式", "value": "enabled"}],
        value=["enabled"] if adv_3init_enabled else [],
        inline=True,
    )
    advanced_content.append(adv_3init_switch)

    # 最低加权命中
    min_weighted_opts = [(str(v), v) for v in [0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0]]
    adv_3init_min = put_select(
        name=f"{scope}_adv_3init_min",
        label="最低加权命中",
        options=min_weighted_opts,
        value=three_init.get("min_weighted_hits", 1.0),
    )
    advanced_content.append(adv_3init_min)

    # 第4条白名单
    advanced_content.append(put_html("<div style='margin-top:8px;'><b>第4条必须是</b> <span style='color:#888;'>(留空接受任意)</span></div>"))
    fourth_whitelist = put_checkbox(
        name=f"{scope}_adv_4th_whitelist",
        options=[{"label": opt["label"], "value": opt["slug"]} for opt in SUBSTAT_OPTIONS],
        value=three_init.get("fourth_stat_whitelist", ["spd", "crit_rate", "crit_dmg"]),
        inline=True,
    )
    fourth_whitelist.style("display:grid;grid-template-columns:repeat(3,minmax(80px,1fr));column-gap:16px;row-gap:8px;")
    advanced_content.append(fourth_whitelist)

    # 不满足时弃置
    adv_3init_discard = put_checkbox(
        name=f"{scope}_adv_3init_discard",
        options=[{"label": "第4条不满足时弃置", "value": "discard"}],
        value=["discard"] if three_init.get("discard_if_miss", True) else [],
        inline=True,
    )
    advanced_content.append(adv_3init_discard)

    # 放入折叠区
    outputs.append(put_html("<div style='margin-top: 16px;'></div>"))
    outputs.append(put_collapse("高级选项", advanced_content, open=False))

    # 保存/取消按钮
    def do_save():
        def _safe_get_pin(pin_name: str, fallback):
            """安全获取pin值，如果不存在则返回fallback"""
            try:
                val = pin[pin_name]
                return val if val is not None else fallback
            except Exception:
                return fallback

        try:
            # 收集高级选项
            # 1. 部位独立阈值
            slot_thresholds_data = {
                "enabled": "enabled" in (pin[f"{scope}_adv_slot_enabled"] or []),
                "groups": {
                    "head_hands": ["head", "hands"],
                    "body": ["body"],
                    "feet": ["feet"],
                    "sphere": ["sphere"],
                    "rope": ["rope"],
                },
                "overrides": {},
            }
            for group_key, _ in [("head_hands", ""), ("body", ""), ("feet", ""), ("sphere", ""), ("rope", "")]:
                group_overrides = {}
                for level in [0, 3, 6, 9]:
                    try:
                        val = pin[f"{scope}_adv_{group_key}_{level}"]
                        if val is not None and int(val) >= 0:
                            group_overrides[f"min_hits_{level}"] = int(val)
                    except (KeyError, ValueError, TypeError):
                        pass
                if group_overrides:
                    slot_thresholds_data["overrides"][group_key] = group_overrides

            # 2. 词条权重系统
            weights_data = {
                "enabled": "enabled" in (pin[f"{scope}_adv_weights_enabled"] or []),
                "global": {},
                "slot_overrides": {},
            }
            for substat in SUBSTAT_OPTIONS:
                slug = substat["slug"]
                try:
                    val = pin[f"{scope}_adv_weight_{slug}"]
                    if val is not None:
                        weights_data["global"][slug] = float(val)
                except (KeyError, ValueError, TypeError):
                    pass

            # 3. 3初始探索模式
            three_init_data = {
                "enabled": "enabled" in (pin[f"{scope}_adv_3init_enabled"] or []),
                "min_weighted_hits": float(pin[f"{scope}_adv_3init_min"] or 1.0),
                "fourth_stat_whitelist": pin[f"{scope}_adv_4th_whitelist"] or [],
                "discard_if_miss": "discard" in (pin[f"{scope}_adv_3init_discard"] or []),
            }

            form_data = {
                "id": plan.get("id"),
                "name": pin[f"{scope}_name"] or "未命名方案",
                "enabled": plan.get("enabled", True),
                "params": {
                    "mode": "enhance",
                    "filter_name": pin[f"{scope}_filter"] or "",
                    "check_slots": _safe_get_pin(f"{scope}_slots", params.get("check_slots", [])),
                    "substats": pin[f"{scope}_substats"] or [],
                    # 安全获取主词条 - 可能因动态隐藏而不存在
                    "main_stat_body": _safe_get_pin(f"{scope}_main_body", params.get("main_stat_body", [])),
                    "main_stat_feet": _safe_get_pin(f"{scope}_main_feet", params.get("main_stat_feet", [])),
                    "main_stat_sphere": _safe_get_pin(f"{scope}_main_sphere", params.get("main_stat_sphere", [])),
                    "main_stat_rope": _safe_get_pin(f"{scope}_main_rope", params.get("main_stat_rope", [])),
                    "min_hits_0": float(pin[f"{scope}_min0"]),
                    "min_hits_3": float(pin[f"{scope}_min3"]),
                    "min_hits_6": float(pin[f"{scope}_min6"]),
                    "min_hits_9": float(pin[f"{scope}_min9"]),
                    "save_threshold": float(pin[f"{scope}_save_threshold"]),
                    "stop_if_fail": "stop_if_fail" in (pin[f"{scope}_options"] or []),
                    "discard_trash": "discard_trash" in (pin[f"{scope}_options"] or []),
                    "enhance_goal": 15,
                    "advanced": {
                        "slot_thresholds": slot_thresholds_data,
                        "weights": weights_data,
                        "three_init_explore": three_init_data,
                    },
                },
            }
            on_save(form_data)
        except Exception as e:
            logger.error(f"保存方案失败: {e}")

    btn_row = put_buttons(
        [
            {"label": "保存", "value": "save", "color": "success"},
            {"label": "取消", "value": "cancel", "color": "secondary"},
        ],
        onclick=[do_save, on_cancel],
    )
    btn_row.style("margin-top: 24px;")
    outputs.append(btn_row)

    return outputs


def plan_summary_bar(
    total: int,
    enabled: int,
    scope: str = "plan_summary",
) -> Output:
    """
    方案摘要栏 - 简单文本样式

    Args:
        total: 方案总数
        enabled: 启用方案数

    Returns:
        Output widget
    """
    # 使用简单文本样式，与其他配置组风格一致
    return put_text(f"共 {total} 个方案，{enabled} 个启用").style(
        "color: #666; font-size: 0.9em; margin-bottom: 8px;"
    )
