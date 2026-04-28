"""Forgotten Hall UI compatibility facade.

The implementation is split into focused mixins under ``tasks.forgotten_hall.ui_parts``
so existing imports can keep using ``ForgottenHallUI`` from this module.
"""

from tasks.dungeon.ui.ui import DungeonUI
from tasks.forgotten_hall.stage_ocr import (
    DraggableStageList,
    ForgottenHallStageOcr,
    STAGE_LIST,
    detect_unlocked_text,
    scan_for_unlocked_stages,
)
from tasks.forgotten_hall.team import ForgottenHallTeam
from tasks.forgotten_hall.ui_parts.battle import ForgottenHallBattleMixin
from tasks.forgotten_hall.ui_parts.preset_team import ForgottenHallPresetTeamMixin
from tasks.forgotten_hall.ui_parts.pure_fiction import ForgottenHallPureFictionMixin
from tasks.forgotten_hall.ui_parts.reward import ForgottenHallRewardMixin
from tasks.forgotten_hall.ui_parts.stage_selection import ForgottenHallStageSelectionMixin
from tasks.map.control.control import MapControl


class ForgottenHallUI(
    DungeonUI,
    ForgottenHallTeam,
    MapControl,
    ForgottenHallPureFictionMixin,
    ForgottenHallPresetTeamMixin,
    ForgottenHallStageSelectionMixin,
    ForgottenHallBattleMixin,
    ForgottenHallRewardMixin,
):
    pass


__all__ = [
    'ForgottenHallUI',
    'ForgottenHallStageOcr',
    'DraggableStageList',
    'STAGE_LIST',
    'detect_unlocked_text',
    'scan_for_unlocked_stages',
]
