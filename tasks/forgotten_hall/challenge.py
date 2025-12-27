"""
深渊挑战任务

手动触发的深渊挑战功能，支持混沌回忆和忘却之庭。
"""

from module.logger import logger
from tasks.forgotten_hall.ui import ForgottenHallUI
from tasks.forgotten_hall.keywords import KEYWORDS_FORGOTTEN_HALL_STAGE
from tasks.dungeon.keywords import KEYWORDS_DUNGEON_LIST


class ForgottenHallChallenge(ForgottenHallUI):
    """
    深渊挑战任务类

    功能：
    - 支持混沌回忆（1-10层）和忘却之庭（1-15层）
    - 自动导航到指定舞台
    - 自动选择队伍
    - 进入副本
    """

    def run(self):
        """主执行方法"""
        try:
            # 1. 解析配置参数
            dungeon_type = self.config.ForgottenHallChallenge_DungeonType
            stage_num = int(self.config.ForgottenHallChallenge_Stage)
            team1_preset = int(self.config.ForgottenHallChallenge_Team1Preset)
            team2_preset = int(self.config.ForgottenHallChallenge_Team2Preset)

            logger.hr('Forgotten Hall Challenge', level=1)
            logger.info(f'Dungeon type: {dungeon_type}')
            logger.info(f'Stage: {stage_num}')
            logger.info(f'Team1 Preset: {team1_preset}')
            logger.info(f'Team2 Preset: {team2_preset}')

            # 2. 选择深渊类型
            if dungeon_type == 'Memory_of_Chaos':
                dungeon = KEYWORDS_DUNGEON_LIST.Memory_of_Chaos
                max_stage = 10
                logger.info('Dungeon: Memory of Chaos (1-10)')
            elif dungeon_type == 'The_Last_Vestiges_of_Towering_Citadel':
                dungeon = KEYWORDS_DUNGEON_LIST.The_Last_Vestiges_of_Towering_Citadel
                max_stage = 15
                logger.info('Dungeon: The Last Vestiges of Towering Citadel (1-15)')
            else:
                logger.error(f'Unknown dungeon type: {dungeon_type}')
                return False

            # 3. 验证舞台编号
            if stage_num < 1 or stage_num > max_stage:
                logger.error(f'Invalid stage: {stage_num}, must be 1-{max_stage}')
                return False

            # 4. 获取舞台关键词
            stage = getattr(KEYWORDS_FORGOTTEN_HALL_STAGE, f'Stage_{stage_num}')
            logger.info(f'Target stage: {stage.cn}')

            # 5. 执行挑战流程
            logger.hr(f'Challenge: {dungeon.cn} - {stage.cn}', level=2)

            # 5.1 导航到舞台并配置预设编队
            logger.info('Navigate to stage and configure preset teams')
            if not self.stage_goto(dungeon, stage,
                                   team1_preset=team1_preset,
                                   team2_preset=team2_preset):
                logger.error('Failed to navigate to stage')
                return False
            logger.info('Stage navigation and team configuration complete')

            # 5.2 进入副本
            logger.info('Enter dungeon')
            self.enter_forgotten_hall_dungeon()
            logger.info('Dungeon entered')

            # 5.3 提示信息
            logger.info('Wait for battle')
            logger.warning('Battle is not automated, manual control required')
            logger.info('Use exit_dungeon() to leave dungeon')

            logger.hr('Challenge complete', level=1)
            return True

        except Exception as e:
            logger.error(f'Challenge failed: {e}')
            logger.exception(e)
            return False
