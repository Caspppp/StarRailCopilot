"""
深渊挑战任务

手动触发的深渊挑战功能，支持混沌回忆和忘却之庭。
支持自动选关模式：自动扫描关卡星数，从最高未完成关卡开始挑战。
"""

from module.logger import logger
from module.base.timer import Timer
from tasks.forgotten_hall.ui import ForgottenHallUI
from tasks.forgotten_hall.keywords import KEYWORDS_FORGOTTEN_HALL_STAGE
from tasks.dungeon.keywords import KEYWORDS_DUNGEON_LIST


class ForgottenHallChallenge(ForgottenHallUI):
    """
    深渊挑战任务类

    功能：
    - 支持混沌回忆（1-12层）和忘却之庭（1-15层）
    - 自动导航到指定舞台
    - 自动选择队伍
    - 进入副本
    - 自动选关模式：扫描星数、自动升级/降级
    """

    def run(self):
        """主执行方法"""
        try:
            # 读取配置
            auto_selection = getattr(self.config, 'ForgottenHallChallenge_AutoStageSelection', False)
            dungeon_type = self.config.ForgottenHallChallenge_DungeonType
            team1_preset = int(self.config.ForgottenHallChallenge_Team1Preset)
            team2_preset = int(self.config.ForgottenHallChallenge_Team2Preset)

            # 记录配置状态
            logger.hr('Forgotten Hall Challenge Configuration', level=1)
            logger.info(f'Dungeon Type: {dungeon_type}')
            logger.info(f'Auto Stage Selection: {auto_selection}')
            logger.info(f'Team1 Preset: {team1_preset}')
            logger.info(f'Team2 Preset: {team2_preset}')

            # 根据模式选择流程
            if auto_selection:
                logger.hr('Auto Stage Selection Mode', level=1)
                return self.run_auto_selection()

            # 手动选关模式
            logger.hr('Manual Stage Selection Mode', level=1)

            # 1. 解析配置参数
            stage_num = int(self.config.ForgottenHallChallenge_Stage)
            logger.info(f'Target Stage: {stage_num}')

            # 2. 选择深渊类型
            if dungeon_type == 'Memory_of_Chaos':
                dungeon = KEYWORDS_DUNGEON_LIST.Memory_of_Chaos
                max_stage = 12
                logger.info('Dungeon: Memory of Chaos (1-12)')
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

            # 5.2 上半战斗（Battle 1）- 带重试逻辑
            logger.hr('Battle 1: Upper Half', level=2)
            max_retries = 3
            battle1_success = False
            attempts_battle1 = 0

            for attempt in range(1, max_retries + 1):
                logger.hr(f'Battle 1 Attempt {attempt}/{max_retries}', level=2)
                attempts_battle1 = attempt

                # 进入副本并战斗
                logger.info(f'Battle 1 Attempt {attempt}: Entering dungeon')
                self.enter_forgotten_hall_dungeon(skip_first_screenshot=(attempt == 1))

                # 检测 Battle 1 结果：只检测是否失败
                logger.info(f'Battle 1 Attempt {attempt}: Checking for battle failure')
                # 使用短超时检测 BATTLE_FAILED，未出现则认为成功
                from tasks.forgotten_hall.assets.assets_forgotten_hall_ui import BATTLE_FAILED
                from module.base.timer import Timer

                # 开始检测前清除 stuck record（遵循 SRC 官方模式）
                self.device.stuck_record_clear()

                timeout = Timer(3).start()  # 3秒短超时
                battle1_failed = False

                while not timeout.reached():
                    self.device.screenshot()
                    # 使用 appear() + interval 替代 match_template_color()
                    if self.appear(BATTLE_FAILED, interval=0.5):
                        logger.info('Battle 1 failed - BATTLE_FAILED detected')
                        battle1_failed = True
                        break
                    self.device.sleep(0.5)

                if not battle1_failed:
                    # Battle 1 成功（未检测到失败屏幕，已进入 Battle 2 场景）
                    logger.info(f'Battle 1 succeeded on attempt {attempt}/{max_retries}')
                    logger.info('Staying in dungeon for Battle 2')
                    battle1_success = True
                    break
                else:
                    # Battle 1 失败
                    logger.warning(f'Battle 1 failed on attempt {attempt}/{max_retries}')

                    # 处理失败（返回关卡选择界面）
                    if not self.handle_battle_failure():
                        logger.error('Failed to return to stage selection')
                        return False

                    if attempt >= max_retries:
                        logger.error(f'Battle 1 failed after {max_retries} retries')
                        break

                    logger.info(f'Waiting 2s before retry attempt {attempt+1}')
                    self.device.sleep(2.0)
                    continue

            # 5.3 检查上半结果
            if not battle1_success:
                logger.hr('Battle 1 Failed', level=1)
                logger.attr('Attempts', attempts_battle1)
                logger.error('Battle 1 failed after maximum retries')
                logger.info('Currently at stage selection screen')
                return False

            logger.hr('Battle 1 Completed Successfully', level=1)
            logger.attr('Attempts', attempts_battle1)
            logger.info('Proceeding to Battle 2 (Lower Half)')

            # 5.4 下半战斗（Battle 2）- 带重试逻辑
            logger.hr('Battle 2: Lower Half', level=2)
            battle2_success = False
            attempts_battle2 = 0

            for attempt in range(1, max_retries + 1):
                logger.hr(f'Battle 2 Attempt {attempt}/{max_retries}', level=2)
                attempts_battle2 = attempt

                # ✅ 已经在副本内，直接开怪战斗
                logger.info('Already in dungeon, auto-engaging enemy for Battle 2')
                engage_success = self.auto_engage_enemy(move_duration=8, timeout=15)

                if not engage_success:
                    logger.warning(f'Battle 2 Attempt {attempt}: Failed to engage enemy')
                    # 尝试退出副本重新进入
                    logger.info('Exiting dungeon to retry')
                    self.exit_dungeon()

                    if attempt >= max_retries:
                        logger.error(f'Battle 2 failed to engage enemy after {max_retries} retries')
                        break

                    logger.info(f'Re-entering dungeon for retry attempt {attempt+1}')
                    self.enter_forgotten_hall_dungeon(skip_first_screenshot=False)
                    continue

                # ✅ 已进入战斗：执行 combat_execute()，避免仅靠短超时等待结果导致误判超时
                logger.info(f'Battle 2 Attempt {attempt}: Executing combat')

                from module.base.timer import Timer
                from tasks.combat.assets.assets_combat_finish import COMBAT_AGAIN
                from tasks.forgotten_hall.assets.assets_forgotten_hall_ui import BATTLE_FAILED, RETURN_TO_FORGOTTEN_HALL
                from tasks.base.assets.assets_base_page import FORGOTTEN_HALL_CHECK

                def is_battle_end():
                    """Check if battle has ended (success or failure)."""
                    if not hasattr(self, '_battle_end_stuck_timer'):
                        self._battle_end_stuck_timer = Timer(10).start()

                    if self._battle_end_stuck_timer.reached():
                        logger.info('[Battle 2 is_battle_end] Clear stuck record (10s interval)')
                        self.device.stuck_record_clear()
                        self._battle_end_stuck_timer.reset()

                    if self.appear(BATTLE_FAILED, interval=0.5):
                        logger.info('[Battle 2 is_battle_end] BATTLE_FAILED detected')
                        return True

                    # ✅ 深渊成功结算界面的"返回忘却之庭"按钮
                    if self.appear(RETURN_TO_FORGOTTEN_HALL, interval=0.5):
                        logger.info('[Battle 2 is_battle_end] RETURN_TO_FORGOTTEN_HALL detected')
                        return True

                    if self.appear(COMBAT_AGAIN, interval=0.5):
                        logger.info('[Battle 2 is_battle_end] COMBAT_AGAIN detected')
                        return True

                    if self.appear(FORGOTTEN_HALL_CHECK, interval=0.5):
                        logger.info('[Battle 2 is_battle_end] FORGOTTEN_HALL_CHECK detected')
                        return True

                    return False

                self.combat_execute(expected_end=is_battle_end)

                # 战斗结束后判断结果：优先失败，其余按成功处理并收尾退出
                self.device.screenshot()
                if self.appear(BATTLE_FAILED):
                    result = 'failure'
                else:
                    result = 'success'

                if result == 'success':
                    logger.info(f'Battle 2 succeeded on attempt {attempt}/{max_retries}')
                    # ✅ 下半成功后才调用 handle_battle_success() 退出副本
                    self.handle_battle_success()
                    if self.is_in_main() and not self.appear(FORGOTTEN_HALL_CHECK):
                        self.exit_dungeon()
                    battle2_success = True
                    break
                elif result == 'failure':
                    logger.warning(f'Battle 2 failed on attempt {attempt}/{max_retries}')

                    # 处理失败（返回关卡选择界面）
                    if not self.handle_battle_failure():
                        logger.error('Failed to return to stage selection')
                        return False

                    if attempt >= max_retries:
                        logger.error(f'Battle 2 failed after {max_retries} retries')
                        break

                    logger.info(f'Waiting 2s before retry attempt {attempt+1}')
                    self.device.sleep(2.0)

                    # 重新进入副本（从关卡选择界面）
                    logger.info(f'Re-entering dungeon for Battle 2 retry attempt {attempt+1}')
                    self.enter_forgotten_hall_dungeon(skip_first_screenshot=False)
                    continue

            # 5.5 报告最终结果
            if battle2_success:
                logger.hr('Battle 2 Completed Successfully', level=1)
                logger.attr('Attempts', attempts_battle2)
                logger.info('Both battles completed, returned to forgotten hall')

                logger.hr('Challenge Complete - All Battles Successful', level=1)
                logger.attr('Battle 1 Attempts', attempts_battle1)
                logger.attr('Battle 2 Attempts', attempts_battle2)
                return True
            else:
                logger.hr('Battle 2 Failed', level=1)
                logger.attr('Attempts', attempts_battle2)
                logger.error('Battle 2 failed after maximum retries')
                logger.info('Currently at stage selection screen')

                logger.hr('Challenge Incomplete - Battle 2 Failed', level=1)
                logger.attr('Battle 1 Attempts', attempts_battle1)
                logger.attr('Battle 2 Attempts', attempts_battle2)
                return False

        except Exception as e:
            logger.error(f'Challenge failed: {e}')
            logger.exception(e)
            return False

    def run_auto_selection(self):
        """
        自动选关挑战主流程（增强版：支持队伍调换和奖励领取）

        流程：
        1. 进入关卡选择界面
        2. 检测并领取可用奖励
        3. 扫描所有关卡星数
        4. 确定起始关卡（最高未完成关卡）
        5. 循环挑战：
           - 成功(达目标星数) → 领取奖励 → 升级到下一关
           - 失败/未达标：
             - 向下探索阶段 → 降级
             - 向上攀爬阶段 → 尝试队伍调换重试，调换后仍失败则停止任务
        6. 终止条件：
           - 最高关卡达成目标星数
           - 降到最低关卡仍失败
           - 向上攀爬时调换队伍后仍失败

        Returns:
            bool: 是否成功完成任务
        """
        try:
            # 1. 读取配置
            dungeon_type = self.config.ForgottenHallChallenge_DungeonType
            team1_preset = int(self.config.ForgottenHallChallenge_Team1Preset)
            team2_preset = int(self.config.ForgottenHallChallenge_Team2Preset)
            target_stars = int(getattr(self.config, 'ForgottenHallChallenge_TargetStars', 3))
            min_stage = int(getattr(self.config, 'ForgottenHallChallenge_MinStage', 1))

            # 根据深渊类型确定最大关卡
            if dungeon_type == 'Memory_of_Chaos':
                dungeon = KEYWORDS_DUNGEON_LIST.Memory_of_Chaos
                max_stage = 12
            else:
                dungeon = KEYWORDS_DUNGEON_LIST.The_Last_Vestiges_of_Towering_Citadel
                max_stage = 15

            logger.hr('Auto Stage Selection Mode', level=1)
            logger.info(f'Dungeon: {dungeon_type}')
            logger.info(f'Target stars: {target_stars}')
            logger.info(f'Min stage: {min_stage}, Max stage: {max_stage}')
            logger.info(f'Team1 Preset: {team1_preset}, Team2 Preset: {team2_preset}')

            # 2. 进入关卡选择界面（不选择特定关卡，保持游戏默认定位）
            self.goto_stage_selection(dungeon)

            # 2.1 首次进入时检测并领取奖励
            self.check_and_claim_rewards(skip_first_screenshot=False)

            # 3. 检测当前最高可挑战关卡（不需要滑动）
            current_stage, stage_stars = self.detect_current_highest_stage(
                max_stage=max_stage,
                target_stars=target_stars
            )

            # 4. 检查是否已完成所有关卡
            if current_stage == -1:
                logger.hr('All Stages Completed!', level=1)
                logger.info(f'All stages have reached {target_stars}+ stars')
                return True

            # 5. 状态变量：阶段和队伍调换
            # phase: 'EXPLORING_DOWN' = 向下探索（新账号找能三星的关卡）
            #        'CLIMBING_UP' = 向上攀爬（成功后继续挑战更高关卡）
            phase = 'EXPLORING_DOWN'
            team_swapped = False  # 当前关卡是否已调换队伍

            logger.info(f'Initial phase: {phase}')

            # 6. 主循环：挑战 -> 判断结果 -> 升级/降级/调换队伍
            while True:
                # 决定使用的队伍配置
                if team_swapped:
                    actual_team1, actual_team2 = team2_preset, team1_preset
                    logger.info(f'Using SWAPPED teams: team1={actual_team1}, team2={actual_team2}')
                else:
                    actual_team1, actual_team2 = team1_preset, team2_preset

                logger.hr(f'Auto Challenge Stage {current_stage} (Phase: {phase})', level=1)

                # 挑战当前关卡
                success, actual_stars = self._challenge_stage(
                    dungeon=dungeon,
                    stage_num=current_stage,
                    team1_preset=actual_team1,
                    team2_preset=actual_team2,
                    target_stars=target_stars
                )

                if success:
                    # 成功：领取奖励
                    self.check_and_claim_rewards(skip_first_screenshot=False)

                    # 检查是否完成任务
                    if current_stage >= max_stage:
                        logger.hr('All Stages Completed!', level=1)
                        logger.info(f'Stage {max_stage} completed with {target_stars}+ stars')
                        return True

                    # 阶段转换：第一次成功时进入攀爬阶段
                    if phase == 'EXPLORING_DOWN':
                        phase = 'CLIMBING_UP'
                        logger.info(f'Phase transition: EXPLORING_DOWN -> CLIMBING_UP at stage {current_stage}')

                    # 升级到下一关，重置调换状态
                    current_stage += 1
                    team_swapped = False
                    logger.info(f'Stage passed! Moving to stage {current_stage}')
                else:
                    # 失败或未达目标星数
                    if phase == 'EXPLORING_DOWN':
                        # 向下探索阶段：直接降级，不调换队伍
                        if current_stage <= min_stage:
                            logger.hr('Challenge Failed at Minimum Stage (Exploring)', level=1)
                            logger.error(f'Failed at stage {current_stage} (min_stage={min_stage})')
                            return False

                        current_stage -= 1
                        team_swapped = False
                        logger.info(f'Exploring down: falling back to stage {current_stage}')

                    else:  # phase == 'CLIMBING_UP'
                        # 向上攀爬阶段：尝试队伍调换
                        if not team_swapped:
                            # 首次失败：尝试调换队伍重新挑战同一关卡
                            team_swapped = True
                            logger.warning(f'Stage {current_stage} failed, trying team swap...')
                            # 不改变 current_stage，下一轮会用调换后的队伍重新挑战
                        else:
                            # 已调换仍失败：停止任务
                            logger.hr('Challenge Failed After Team Swap', level=1)
                            logger.error(f'Stage {current_stage} failed even with swapped teams, stopping task')
                            return False

        except Exception as e:
            logger.error(f'Auto selection challenge failed: {e}')
            logger.exception(e)
            return False

    def _challenge_stage(self, dungeon, stage_num: int, team1_preset: int,
                         team2_preset: int, target_stars: int = 3) -> tuple:
        """
        挑战单个关卡

        Args:
            dungeon: 深渊类型关键词
            stage_num: 关卡编号
            team1_preset: 上半预设编队
            team2_preset: 下半预设编队
            target_stars: 目标星数

        Returns:
            tuple[bool, int]: (是否达成目标星数, 实际获得星数)
            - (True, 3): 成功达成3星
            - (False, 2): 未达目标，获得2星
            - (False, 0): 战斗失败
        """
        stage = getattr(KEYWORDS_FORGOTTEN_HALL_STAGE, f'Stage_{stage_num}')
        logger.hr(f'Challenge Stage {stage_num}', level=2)

        # 导航到关卡并配置队伍
        if not self.stage_goto(dungeon, stage,
                               team1_preset=team1_preset,
                               team2_preset=team2_preset):
            logger.error(f'Failed to navigate to stage {stage_num}')
            return (False, 0)

        # 执行 Battle 1 (上半)
        from tasks.forgotten_hall.assets.assets_forgotten_hall_ui import BATTLE_FAILED

        logger.hr('Battle 1: Upper Half', level=2)
        self.enter_forgotten_hall_dungeon(skip_first_screenshot=True)

        # 检测 Battle 1 结果
        self.device.stuck_record_clear()
        timeout = Timer(3).start()
        battle1_failed = False

        while not timeout.reached():
            self.device.screenshot()
            if self.appear(BATTLE_FAILED, interval=0.5):
                logger.info('Battle 1 failed - BATTLE_FAILED detected')
                battle1_failed = True
                break
            self.device.sleep(0.5)

        if battle1_failed:
            logger.warning('Battle 1 failed')
            self.handle_battle_failure()
            return (False, 0)

        logger.info('Battle 1 succeeded, proceeding to Battle 2')

        # 执行 Battle 2 (下半)
        logger.hr('Battle 2: Lower Half', level=2)
        engage_success = self.auto_engage_enemy(move_duration=8, timeout=15)

        if not engage_success:
            logger.warning('Failed to engage enemy in Battle 2')
            self.exit_dungeon()
            return (False, 0)

        # 执行战斗
        from tasks.combat.assets.assets_combat_finish import COMBAT_AGAIN
        from tasks.forgotten_hall.assets.assets_forgotten_hall_ui import RETURN_TO_FORGOTTEN_HALL
        from tasks.base.assets.assets_base_page import FORGOTTEN_HALL_CHECK

        def is_battle_end():
            if not hasattr(self, '_battle_end_stuck_timer'):
                self._battle_end_stuck_timer = Timer(10).start()

            if self._battle_end_stuck_timer.reached():
                self.device.stuck_record_clear()
                self._battle_end_stuck_timer.reset()

            if self.appear(BATTLE_FAILED, interval=0.5):
                return True
            if self.appear(RETURN_TO_FORGOTTEN_HALL, interval=0.5):
                return True
            if self.appear(COMBAT_AGAIN, interval=0.5):
                return True
            if self.appear(FORGOTTEN_HALL_CHECK, interval=0.5):
                return True
            return False

        self.combat_execute(expected_end=is_battle_end)

        # 判断战斗结果
        self.device.screenshot()
        if self.appear(BATTLE_FAILED):
            logger.warning('Battle 2 failed')
            self.handle_battle_failure()
            return (False, 0)

        # 战斗成功，处理结算界面
        logger.info('Battle 2 succeeded')
        self.handle_battle_success()

        # 获取实际星数
        actual_stars = self.get_stage_star_count(stage_num)
        if actual_stars < 0:
            actual_stars = 0

        logger.info(f'Stage {stage_num} completed with {actual_stars} stars (target: {target_stars})')

        if actual_stars >= target_stars:
            return (True, actual_stars)
        else:
            return (False, actual_stars)
