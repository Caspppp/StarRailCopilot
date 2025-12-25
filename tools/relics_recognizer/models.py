"""
Data structures shared by the relic recognizer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class StatLine:
    """Represents either a main stat or a sub stat entry."""

    name: str
    value_text: str
    value: Optional[float] = None
    rolls: Optional[int] = None
    confidence: float = 0.0


@dataclass
class RelicData:
    """Structured dump for a single relic detail page."""

    slot: Optional[str] = None
    set_name: Optional[str] = None
    rarity: Optional[int] = None
    level: Optional[int] = None
    locked: Optional[bool] = None

    main_stat: Optional[StatLine] = None
    sub_stats: List[StatLine] = field(default_factory=list)

    screenshot_path: Optional[str] = None
    raw_ocr: dict = field(default_factory=dict)

    def has_speed_substat(self) -> bool:
        """Convenience helper for downstream strategies."""
        for stat in self.sub_stats:
            if stat.name and "speed" in stat.name.lower():
                return True
        return False
