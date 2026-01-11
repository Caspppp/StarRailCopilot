from tasks.dungeon.keywords import KEYWORDS_DUNGEON_LIST

from tasks.forgotten_hall.challenge_modes.base import StandardDungeonMode

MODE = StandardDungeonMode(
    dungeon_type='Memory_of_Chaos',
    max_stage=12,
    display_name=KEYWORDS_DUNGEON_LIST.Memory_of_Chaos.cn,
)
