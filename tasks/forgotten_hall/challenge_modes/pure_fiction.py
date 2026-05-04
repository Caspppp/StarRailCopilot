from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from module.base.timer import Timer
from module.logger import logger
from tasks.dungeon.keywords import KEYWORDS_DUNGEON_NAV

if TYPE_CHECKING:
    from tasks.forgotten_hall.challenge import ForgottenHallChallenge


@dataclass(frozen=True)
class PureFictionDungeonMode:
    dungeon_type: str
    max_stage: int
    display_name: str

    def run_auto_selection(
        self,
        task: "ForgottenHallChallenge",
        team1_preset: int,
        team2_preset: int,
        team1_buff: int | str | list[str],
        team2_buff: int | str | list[str],
        target_stars: int,
        min_stage: int,
    ) -> bool:
        _ = min_stage
        dungeon_type = self.dungeon_type
        target_stars = 1
        max_stage = self.max_stage

        logger.hr('Auto Stage Selection Mode: Pure Fiction', level=1)
        logger.info(f'Dungeon: {self.display_name}')
        logger.info(f'Target stars: {target_stars} (>=1 means cleared)')
        logger.info(f'Max stage: {max_stage}')
        logger.info(f'Team1 Preset: {team1_preset}, Team2 Preset: {team2_preset}')
        logger.info(f'Team1 Buff: {team1_buff}, Team2 Buff: {team2_buff}')

        if not task.goto_stage_selection_by_dungeon_type(dungeon_type):
            logger.error('Failed to navigate to stage selection')
            return False

        task.check_and_claim_rewards(skip_first_screenshot=False)

        while True:
            next_stage, stage_stars = task.pure_fiction_next_stage_to_challenge()

            if next_stage == -1:
                logger.hr('All Stages Completed!', level=1)
                logger.info('Pure Fiction: all 4 stages have yellow stars')
                return True

            if next_stage < 1 or next_stage > max_stage:
                logger.error(
                    f'Invalid next stage: {next_stage} (max={max_stage}), '
                    f'stage_stars={stage_stars}'
                )
                return False

            logger.hr(f'Auto Challenge Pure Fiction Stage {next_stage}', level=1)
            logger.info(f'[PureFiction] Stage stars snapshot: {stage_stars}')

            attempts = [
                (team1_preset, team2_preset, team1_buff, team2_buff, False),
                (team2_preset, team1_preset, team2_buff, team1_buff, True),
            ]
            stage_succeeded = False
            last_stars = 0

            for actual_team1, actual_team2, actual_buff1, actual_buff2, swapped in attempts:
                if swapped:
                    logger.warning(
                        f'Pure Fiction stage {next_stage} failed, retrying with swapped teams: '
                        f'team1={actual_team1}, team2={actual_team2}'
                    )

                success, actual_stars = task._challenge_stage(
                    dungeon_type=dungeon_type,
                    stage_num=next_stage,
                    team1_preset=actual_team1,
                    team2_preset=actual_team2,
                    team1_buff=actual_buff1,
                    team2_buff=actual_buff2,
                    target_stars=target_stars,
                )

                last_stars = actual_stars
                if success:
                    stage_succeeded = True
                    break

                task.check_and_claim_rewards(skip_first_screenshot=False)

            if not stage_succeeded:
                logger.error(
                    'Pure Fiction stage '
                    f'{next_stage} failed or did not reach target stars after team swap: '
                    f'{last_stars}'
                )
                return False

            task.check_and_claim_rewards(skip_first_screenshot=False)

    def get_stage_star_count(
        self,
        task: "ForgottenHallChallenge",
        stage_num: int,
        target_stars: int,
    ) -> int:
        timeout = Timer(5).start()
        actual_stars = 0
        while not timeout.reached():
            task.device.screenshot()
            actual_stars = task.pure_fiction_get_stage_star_count(
                stage_num,
                image=task.device.image,
            )
            if actual_stars >= target_stars:
                break
        return actual_stars


MODE = PureFictionDungeonMode(
    dungeon_type='Pure_Fiction',
    max_stage=4,
    display_name=KEYWORDS_DUNGEON_NAV.Pure_Fiction.cn,
)
