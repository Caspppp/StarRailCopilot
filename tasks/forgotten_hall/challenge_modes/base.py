from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from module.logger import logger

if TYPE_CHECKING:
    from tasks.forgotten_hall.challenge import ForgottenHallChallenge


@dataclass(frozen=True)
class StandardDungeonMode:
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
        try:
            if min_stage < 1:
                min_stage = 1
            if min_stage > self.max_stage:
                logger.warning(
                    f"MinStage {min_stage} > max_stage {self.max_stage}, clamp to {self.max_stage}"
                )
                min_stage = self.max_stage

            logger.hr('Auto Stage Selection Mode', level=1)
            logger.info(f'Dungeon: {self.display_name}')
            logger.info(f'Target stars: {target_stars}')
            logger.info(f'Min stage: {min_stage}, Max stage: {self.max_stage}')
            logger.info(f'Team1 Preset: {team1_preset}, Team2 Preset: {team2_preset}')

            if not task.goto_stage_selection_by_dungeon_type(self.dungeon_type):
                logger.error('Failed to navigate to stage selection')
                return False

            task.check_and_claim_rewards(skip_first_screenshot=False)

            current_stage, stage_stars = task.detect_current_highest_stage(
                max_stage=self.max_stage,
                target_stars=target_stars,
            )

            if current_stage == -1:
                logger.hr('All Stages Completed!', level=1)
                logger.info(f'All stages have reached {target_stars}+ stars')
                return True

            phase = 'EXPLORING_DOWN'
            team_swapped = False

            logger.info(f'Initial phase: {phase}')

            while True:
                if team_swapped:
                    actual_team1, actual_team2 = team2_preset, team1_preset
                    logger.info(
                        f'Using SWAPPED teams: team1={actual_team1}, team2={actual_team2}'
                    )
                else:
                    actual_team1, actual_team2 = team1_preset, team2_preset

                logger.hr(
                    f'Auto Challenge Stage {current_stage} (Phase: {phase})',
                    level=1,
                )

                success, actual_stars = task._challenge_stage(
                    dungeon_type=self.dungeon_type,
                    stage_num=current_stage,
                    team1_preset=actual_team1,
                    team2_preset=actual_team2,
                    team1_buff=team1_buff,
                    team2_buff=team2_buff,
                    target_stars=target_stars,
                )

                if success:
                    task.check_and_claim_rewards(skip_first_screenshot=False)

                    if current_stage >= self.max_stage:
                        logger.hr('All Stages Completed!', level=1)
                        logger.info(
                            f'Stage {self.max_stage} completed with {target_stars}+ stars'
                        )
                        return True

                    if phase == 'EXPLORING_DOWN':
                        phase = 'CLIMBING_UP'
                        logger.info(
                            'Phase transition: EXPLORING_DOWN -> CLIMBING_UP '
                            f'at stage {current_stage}'
                        )

                    current_stage += 1
                    team_swapped = False
                    logger.info(f'Stage passed! Moving to stage {current_stage}')
                else:
                    if phase == 'EXPLORING_DOWN':
                        if current_stage <= min_stage:
                            logger.hr('Challenge Failed at Minimum Stage (Exploring)', level=1)
                            logger.error(
                                f'Failed at stage {current_stage} (min_stage={min_stage})'
                            )
                            return False

                        next_stage = current_stage - 1
                        if (
                            next_stage in stage_stars
                            and stage_stars[next_stage] >= target_stars
                        ):
                            logger.warning(
                                f'Stage {current_stage} failed, but stage {next_stage} '
                                f'already has {target_stars}+ stars'
                            )
                            if not team_swapped:
                                team_swapped = True
                                logger.warning(
                                    f'Cannot downgrade to completed stage {next_stage}, '
                                    'trying team swap instead'
                                )
                            else:
                                logger.hr('Challenge Failed After Team Swap', level=1)
                                logger.error(
                                    f'Stage {current_stage} failed even with swapped teams, '
                                    'stopping task'
                                )
                                return False
                        else:
                            current_stage -= 1
                            team_swapped = False
                            logger.info(
                                f'Exploring down: falling back to stage {current_stage}'
                            )

                    else:
                        if not team_swapped:
                            team_swapped = True
                            logger.warning(
                                f'Stage {current_stage} failed, trying team swap...'
                            )
                        else:
                            logger.hr('Challenge Failed After Team Swap', level=1)
                            logger.error(
                                f'Stage {current_stage} failed even with swapped teams, '
                                'stopping task'
                            )
                            return False

        except Exception as e:
            logger.error(f'Auto selection challenge failed: {e}')
            logger.exception(e)
            return False

    def get_stage_star_count(
        self,
        task: "ForgottenHallChallenge",
        stage_num: int,
        target_stars: int,
    ) -> int:
        _ = target_stars
        return task.get_stage_star_count(stage_num)
