"""
Helpers to estimate how many upgrade rolls contributed to a relic sub-stat
value, based on known per-roll increments.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Dict, List, Optional, Sequence, Tuple


@dataclass
class RollEstimate:
    stat: str
    value: float
    unit: str
    rolls: Optional[int]
    combo: Sequence[float]
    diff: float
    status: str  # "exact" or "approx"


STAT_INCREMENT_TABLE: Dict[Tuple[str, str], Dict] = {
    ("生命值", "flat"): {"unit": "pt", "increments": [33, 37, 42, 46], "tolerance": 2.0},
    ("生命值", "percent"): {"unit": "%", "increments": [3.5, 4.0, 4.4, 4.9], "tolerance": 0.25},
    ("攻击力", "flat"): {"unit": "pt", "increments": [16, 18, 20, 22], "tolerance": 1.5},
    ("攻击力", "percent"): {"unit": "%", "increments": [3.5, 4.0, 4.4, 4.9], "tolerance": 0.25},
    ("防御力", "flat"): {"unit": "pt", "increments": [16, 18, 20, 22], "tolerance": 1.5},
    ("防御力", "percent"): {"unit": "%", "increments": [4.4, 4.9, 5.4, 5.9], "tolerance": 0.3},
    ("暴击率", "percent"): {"unit": "%", "increments": [2.7, 3.1, 3.5, 3.9], "tolerance": 0.2},
    ("暴击伤害", "percent"): {"unit": "%", "increments": [5.4, 6.2, 7.0, 7.8], "tolerance": 0.3},
    ("效果命中", "percent"): {"unit": "%", "increments": [3.5, 4.0, 4.4, 4.9], "tolerance": 0.25},
    ("效果抵抗", "percent"): {"unit": "%", "increments": [3.5, 4.0, 4.4, 4.9], "tolerance": 0.25},
    ("速度", "flat"): {"unit": "pt", "increments": [2, 3], "tolerance": 0.2, "max_rolls": 6},
    ("击破特攻", "percent"): {"unit": "%", "increments": [5.0, 5.7, 6.4, 7.1], "tolerance": 0.35},
}


def parse_value(value_text: str) -> Tuple[Optional[float], Optional[str]]:
    if not value_text:
        return None, None
    text = value_text.strip()
    unit = "%" if "%" in text else "pt"
    cleaned = text.replace("%", "").replace("+", "").strip()
    cleaned = cleaned.replace("－", "-").replace("．", ".")
    cleaned = ''.join(ch for ch in cleaned if ch.isdigit() or ch in ".-")
    if not cleaned:
        return None, unit
    try:
        value = float(cleaned)
    except ValueError:
        return None, unit
    return value, unit


def get_stat_key(stat_name: str, is_percent: bool) -> Optional[Tuple[str, str]]:
    if stat_name in ("暴击率", "暴击伤害", "效果命中", "效果抵抗", "速度", "击破特攻"):
        suffix = "percent" if stat_name != "速度" else "flat"
        return (stat_name, suffix)
    if stat_name in ("生命值", "攻击力", "防御力"):
        suffix = "percent" if is_percent else "flat"
        return (stat_name, suffix)
    return None


def estimate_rolls(stat_name: str, value_text: str) -> Optional[RollEstimate]:
    numeric_value, unit = parse_value(value_text)
    if numeric_value is None or unit is None:
        return None
    key = get_stat_key(stat_name, unit == "%")
    if key is None:
        return None
    table = STAT_INCREMENT_TABLE.get(key)
    if table is None:
        return None
    increments = table["increments"]
    tolerance = table.get("tolerance", 0.25 if unit == "%" else 1.5)
    max_rolls = table.get("max_rolls", 6)
    best = _search_combination(target=numeric_value, increments=increments, max_rolls=max_rolls, tolerance=tolerance)
    if best is not None:
        rolls, total, combo = best
        return RollEstimate(
            stat=stat_name,
            value=numeric_value,
            unit=unit,
            rolls=rolls,
            combo=combo,
            diff=abs(total - numeric_value),
            status="exact",
        )

    approx_rolls = max(1, min(max_rolls, round(numeric_value / (sum(increments) / len(increments)))))
    approx_combo = []
    return RollEstimate(
        stat=stat_name,
        value=numeric_value,
        unit=unit,
        rolls=approx_rolls,
        combo=approx_combo,
        diff=0.0,
        status="approx",
    )


def _search_combination(target: float, increments: Sequence[float], max_rolls: int, tolerance: float):
    best = None
    stack: List[Tuple[int, float, List[float]]] = [(0, 0.0, [])]
    while stack:
        rolls, total, combo = stack.pop()
        if rolls > 0 and abs(total - target) <= tolerance:
            if (
                best is None
                or abs(total - target) < abs(best[1] - target) - 1e-6
                or (
                    abs(abs(total - target) - abs(best[1] - target)) <= 1e-6
                    and rolls < best[0]
                )
            ):
                best = (rolls, total, combo.copy())
        if rolls >= max_rolls:
            continue
        for inc in increments:
            stack.append((rolls + 1, total + inc, combo + [inc]))
    return best


def estimate_max_rolls(stat_name: str, value_text: str) -> Optional[int]:
    """乐观估算“最多可能有多少次命中”。

    用于旧遗器在仅有当前数值的情况下，按“最小增量叠加”的方式估算上界：
      hits_max ≈ ceil(value / min_increment)，并限制在 [1, max_rolls] 范围内。
    """
    numeric_value, unit = parse_value(value_text)
    if numeric_value is None or unit is None:
        return None
    key = get_stat_key(stat_name, unit == "%")
    if key is None:
        return None
    table = STAT_INCREMENT_TABLE.get(key)
    if table is None:
        return None
    increments = table.get("increments") or []
    if not increments:
        return None
    min_inc = min(increments)
    if min_inc <= 0:
        return None
    max_rolls = int(table.get("max_rolls", 6))
    # 使用最小增量作为每次命中的基准，向上取整得到“最多命中次数”
    approx = int(math.ceil(numeric_value / float(min_inc)))
    return max(1, min(max_rolls, approx))
