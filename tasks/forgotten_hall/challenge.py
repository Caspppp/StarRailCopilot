"""
深渊挑战任务

手动触发的深渊挑战功能，支持混沌回忆、忘却之庭、虚构叙事、末日幻影。
支持自动选关模式：自动扫描关卡星数，从最高未完成关卡开始挑战。
"""

from module.logger import logger
from module.base.timer import Timer
from tasks.forgotten_hall.ui import ForgottenHallUI
from tasks.forgotten_hall.keywords import KEYWORDS_FORGOTTEN_HALL_STAGE
from tasks.dungeon.keywords import KEYWORDS_DUNGEON_LIST, KEYWORDS_DUNGEON_NAV


class ForgottenHallChallenge(ForgottenHallUI):
    """
    深渊挑战任务类

    功能：
    - 支持混沌回忆（1-12层）/ 忘却之庭（1-15层）/ 虚构叙事（1-4）/ 末日幻影（1-4）
    - 自动导航到指定舞台
    - 自动选择队伍
    - 进入副本
    - 自动选关模式：扫描星数、自动升级/降级
    """

    DUNGEON_TYPE_MAX_STAGE = {
        'Memory_of_Chaos': 12,
        'The_Last_Vestiges_of_Towering_Citadel': 15,
        # 逐光捡金
        'Pure_Fiction': 4,
        'Apocalyptic_Shadow': 4,
    }

    def _get_max_stage(self, dungeon_type: str) -> int | None:
        return self.DUNGEON_TYPE_MAX_STAGE.get(dungeon_type)

    def _get_dungeon_display_name(self, dungeon_type: str) -> str:
        if dungeon_type == 'Memory_of_Chaos':
            return KEYWORDS_DUNGEON_LIST.Memory_of_Chaos.cn
        if dungeon_type == 'The_Last_Vestiges_of_Towering_Citadel':
            return KEYWORDS_DUNGEON_LIST.The_Last_Vestiges_of_Towering_Citadel.cn
        if dungeon_type == 'Pure_Fiction':
            return KEYWORDS_DUNGEON_NAV.Pure_Fiction.cn
        if dungeon_type == 'Apocalyptic_Shadow':
            return KEYWORDS_DUNGEON_NAV.Apocalyptic_Shadow.cn
        return dungeon_type

    def _get_selected_dungeon_types(self) -> list[str]:
        """
        获取本次需要执行的深渊类型列表：
        - 若 DungeonTypes（多选）非空，则按其顺序执行
        - 否则回退到旧配置 DungeonType（单选）
        """
        dungeon_types = getattr(self.config, 'ForgottenHallChallenge_DungeonTypes', None)
        if isinstance(dungeon_types, str):
            dungeon_types = [dungeon_types]

        if isinstance(dungeon_types, list) and dungeon_types:
            supported: list[str] = []
            for dungeon_type in dungeon_types:
                if dungeon_type in self.DUNGEON_TYPE_MAX_STAGE:
                    supported.append(dungeon_type)
                else:
                    logger.warning(f'Ignored unknown dungeon type in DungeonTypes: {dungeon_type}')
            if supported:
                return supported

        return [self.config.ForgottenHallChallenge_DungeonType]

    def run(self):
        """主执行方法"""
        success = False
        try:
            # 确保游戏已启动并在主界面
            # 如果游戏未运行，会抛出 GameNotRunningError，调度器会自动调用 Restart 任务
            self.ui_goto_main()

            auto_selection = getattr(self.config, 'ForgottenHallChallenge_AutoStageSelection', False)
            team1_preset = int(self.config.ForgottenHallChallenge_Team1Preset)
            team2_preset = int(self.config.ForgottenHallChallenge_Team2Preset)
            dungeon_types = self._get_selected_dungeon_types()

            logger.hr('Forgotten Hall Challenge Configuration', level=1)
            logger.info(f'Dungeon Types: {dungeon_types}')
            logger.info(f'Auto Stage Selection: {auto_selection}')
            logger.info(f'Team1 Preset: {team1_preset}')
            logger.info(f'Team2 Preset: {team2_preset}')

            if auto_selection:
                for dungeon_type in dungeon_types:
                    dungeon_name = self._get_dungeon_display_name(dungeon_type)
                    logger.hr(f'Auto Stage Selection Mode: {dungeon_name}', level=1)
                    if not self.run_auto_selection(dungeon_type=dungeon_type):
                        return False
                success = True
                return True

            logger.hr('Manual Stage Selection Mode', level=1)
            stage_num = int(self.config.ForgottenHallChallenge_Stage)
            logger.info(f'Target Stage: {stage_num}')

            for dungeon_type in dungeon_types:
                if not self._run_manual_single_dungeon(
                    dungeon_type,
                    stage_num=stage_num,
                    team1_preset=team1_preset,
                    team2_preset=team2_preset,
                ):
                    return False

            success = True
            return True

        except Exception as e:
            logger.error(f'Challenge failed: {e}')
            logger.exception(e)
            return False
        finally:
            # 任务结束时重置 next_run，避免调度器立即重复执行导致死循环
            if success:
                logger.info('Forgotten Hall challenge completed successfully')
                self.config.task_delay(server_update=True)
            else:
                logger.info('Forgotten Hall challenge failed or incomplete, will retry after 1 week')
                # 深渊是周期性挑战，失败后延迟1周（10080分钟）再重试
                # 因为队伍强度短期内不会改变，短时间重试无意义
                self.config.task_delay(minute=10080)

    def _run_manual_single_dungeon(
        self,
        dungeon_type: str,
        stage_num: int,
        team1_preset: int,
        team2_preset: int,
    ) -> bool:
        max_stage = self._get_max_stage(dungeon_type)
        if max_stage is None:
            logger.error(f'Unknown dungeon type: {dungeon_type}')
            return False

        if stage_num < 1 or stage_num > max_stage:
            logger.error(f'Invalid stage: {stage_num}, must be 1-{max_stage}')
            return False

        stage = getattr(KEYWORDS_FORGOTTEN_HALL_STAGE, f'Stage_{stage_num}')
        dungeon_name = self._get_dungeon_display_name(dungeon_type)

        logger.hr(f'Challenge: {dungeon_name} - {stage.cn}', level=2)

        logger.info('Navigate to stage and configure preset teams')
        if not self.stage_goto_by_dungeon_type(
            dungeon_type,
            stage,
            team1_preset=team1_preset,
            team2_preset=team2_preset,
        ):
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

            # Step 1: Enter dungeon (standard SRC pattern)
            logger.info(f'Battle 1 Attempt {attempt}: Entering dungeon')
            self._click_enter_dungeon(skip_first_screenshot=(attempt == 1))

            # Step 2: Auto engage enemy
            logger.info(f'Battle 1 Attempt {attempt}: Auto-engaging enemy')
            engage_success = self.auto_engage_enemy(move_duration=8, timeout=15)

            if not engage_success:
                logger.warning(f'Battle 1 Attempt {attempt}: Failed to engage enemy')
                logger.info('Exiting dungeon to retry')
                self.exit_dungeon()

                if attempt >= max_retries:
                    logger.error(f'Battle 1 failed to engage enemy after {max_retries} retries')
                    break

                logger.info(f'Waiting 2s before retry attempt {attempt + 1}')
                self.device.sleep(2.0)
                continue

            logger.info(f'Battle 1 Attempt {attempt}: Executing combat')

            from module.base.timer import Timer
            from tasks.combat.assets.assets_combat_finish import COMBAT_AGAIN
            from tasks.forgotten_hall.assets.assets_forgotten_hall_ui import BATTLE_FAILED, RETURN_TO_FORGOTTEN_HALL
            from tasks.base.assets.assets_base_page import FORGOTTEN_HALL_CHECK

            def is_battle_end():
                """Check if battle has ended (success or failure)."""
                if not hasattr(self, '_battle1_end_stuck_timer'):
                    self._battle1_end_stuck_timer = Timer(10).start()

                if self._battle1_end_stuck_timer.reached():
                    logger.info('[Battle 1 is_battle_end] Clear stuck record (10s interval)')
                    self.device.stuck_record_clear()
                    self._battle1_end_stuck_timer.reset()

                if self.appear(BATTLE_FAILED, interval=0.5):
                    logger.info('[Battle 1 is_battle_end] BATTLE_FAILED detected')
                    return True

                if self.appear(RETURN_TO_FORGOTTEN_HALL, interval=0.5):
                    logger.info('[Battle 1 is_battle_end] RETURN_TO_FORGOTTEN_HALL detected')
                    return True

                if self.appear(COMBAT_AGAIN, interval=0.5):
                    logger.info('[Battle 1 is_battle_end] COMBAT_AGAIN detected')
                    return True

                if self.appear(FORGOTTEN_HALL_CHECK, interval=0.5):
                    logger.info('[Battle 1 is_battle_end] FORGOTTEN_HALL_CHECK detected')
                    return True

                return False

            self.combat_execute(expected_end=is_battle_end)

            self.device.screenshot()

            if self.appear(BATTLE_FAILED):
                logger.warning(f'Battle 1 failed on attempt {attempt}/{max_retries}')

                if not self.handle_battle_failure():
                    logger.error('Failed to return to stage selection')
                    return False

                if attempt >= max_retries:
                    logger.error(f'Battle 1 failed after {max_retries} retries')
                    break

                logger.info(f'Waiting 2s before retry attempt {attempt + 1}')
                self.device.sleep(2.0)
                continue

            logger.info(f'Battle 1 succeeded on attempt {attempt}/{max_retries}')
            logger.info('Staying in dungeon for Battle 2')
            battle1_success = True
            break

        if not battle1_success:
            logger.hr('Battle 1 Failed', level=1)
            logger.attr('Attempts', attempts_battle1)
            logger.error('Battle 1 failed after maximum retries')
            logger.info('Currently at stage selection screen')
            return False

        logger.hr('Battle 1 Completed Successfully', level=1)
        logger.attr('Attempts', attempts_battle1)
        logger.info('Proceeding to Battle 2 (Lower Half)')

        logger.hr('Battle 2: Lower Half', level=2)
        battle2_success = False
        attempts_battle2 = 0

        for attempt in range(1, max_retries + 1):
            logger.hr(f'Battle 2 Attempt {attempt}/{max_retries}', level=2)
            attempts_battle2 = attempt

            logger.info('Already in dungeon, auto-engaging enemy for Battle 2')
            engage_success = self.auto_engage_enemy(move_duration=8, timeout=15)

            if not engage_success:
                logger.warning(f'Battle 2 Attempt {attempt}: Failed to engage enemy')
                logger.info('Exiting dungeon to retry')
                self.exit_dungeon()

                if attempt >= max_retries:
                    logger.error(f'Battle 2 failed to engage enemy after {max_retries} retries')
                    break

                logger.info(f'Re-entering dungeon for retry attempt {attempt + 1}')
                self.enter_forgotten_hall_dungeon(skip_first_screenshot=False)
                continue

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

            self.device.screenshot()
            if self.appear(BATTLE_FAILED):
                result = 'failure'
            else:
                result = 'success'

            if result == 'success':
                logger.info(f'Battle 2 succeeded on attempt {attempt}/{max_retries}')
                self.handle_battle_success()
                if self.is_in_main() and not self.appear(FORGOTTEN_HALL_CHECK):
                    self.exit_dungeon()
                battle2_success = True
                break

            logger.warning(f'Battle 2 failed on attempt {attempt}/{max_retries}')

            if not self.handle_battle_failure():
                logger.error('Failed to return to stage selection')
                return False

            if attempt >= max_retries:
                logger.error(f'Battle 2 failed after {max_retries} retries')
                break

            logger.info(f'Waiting 2s before retry attempt {attempt + 1}')
            self.device.sleep(2.0)

            logger.info(f'Re-entering dungeon for Battle 2 retry attempt {attempt + 1}')
            self.enter_forgotten_hall_dungeon(skip_first_screenshot=False)

        if battle2_success:
            logger.hr('Battle 2 Completed Successfully', level=1)
            logger.attr('Attempts', attempts_battle2)
            logger.info('Both battles completed, returned to forgotten hall')

            logger.hr('Challenge Complete - All Battles Successful', level=1)
            logger.attr('Battle 1 Attempts', attempts_battle1)
            logger.attr('Battle 2 Attempts', attempts_battle2)
            return True

        logger.hr('Battle 2 Failed', level=1)
        logger.attr('Attempts', attempts_battle2)
        logger.error('Battle 2 failed after maximum retries')
        logger.info('Currently at stage selection screen')

        logger.hr('Challenge Incomplete - Battle 2 Failed', level=1)
        logger.attr('Battle 1 Attempts', attempts_battle1)
        logger.attr('Battle 2 Attempts', attempts_battle2)
        return False

    def run_auto_selection(self, dungeon_type: str | None = None):
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
            dungeon_type = dungeon_type or self.config.ForgottenHallChallenge_DungeonType
            team1_preset = int(self.config.ForgottenHallChallenge_Team1Preset)
            team2_preset = int(self.config.ForgottenHallChallenge_Team2Preset)
            target_stars = int(getattr(self.config, 'ForgottenHallChallenge_TargetStars', 3))
            min_stage = int(getattr(self.config, 'ForgottenHallChallenge_MinStage', 1))

            max_stage = self._get_max_stage(dungeon_type)
            if max_stage is None:
                logger.error(f'Unknown dungeon type: {dungeon_type}')
                return False

            if min_stage < 1:
                min_stage = 1
            if min_stage > max_stage:
                logger.warning(f'MinStage {min_stage} > max_stage {max_stage}, clamp to {max_stage}')
                min_stage = max_stage

            logger.hr('Auto Stage Selection Mode', level=1)
            logger.info(f'Dungeon: {self._get_dungeon_display_name(dungeon_type)}')
            logger.info(f'Target stars: {target_stars}')
            logger.info(f'Min stage: {min_stage}, Max stage: {max_stage}')
            logger.info(f'Team1 Preset: {team1_preset}, Team2 Preset: {team2_preset}')

            # 2. 进入关卡选择界面（不选择特定关卡，保持游戏默认定位）
            if not self.goto_stage_selection_by_dungeon_type(dungeon_type):
                logger.error('Failed to navigate to stage selection')
                return False

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
                    dungeon_type=dungeon_type,
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

                        # 检查下一关卡是否已完成
                        next_stage = current_stage - 1
                        if next_stage in stage_stars and stage_stars[next_stage] >= target_stars:
                            # 下一关已完成，不应降级，改为触发队伍调换
                            logger.warning(f'Stage {current_stage} failed, but stage {next_stage} already has {target_stars}+ stars')
                            if not team_swapped:
                                team_swapped = True
                                logger.warning(f'Cannot downgrade to completed stage {next_stage}, trying team swap instead')
                                # 不改变 current_stage，下一轮用调换后的队伍重试当前关卡
                            else:
                                # 已调换仍失败：停止任务
                                logger.hr('Challenge Failed After Team Swap', level=1)
                                logger.error(f'Stage {current_stage} failed even with swapped teams, stopping task')
                                return False
                        else:
                            # 正常降级逻辑（下一关未完成或不在字典中）
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

    def _challenge_stage(self, dungeon_type: str, stage_num: int, team1_preset: int,
                         team2_preset: int, target_stars: int = 3) -> tuple:
        """
        挑战单个关卡

        Args:
            dungeon_type: 深渊类型
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
        if not self.stage_goto_by_dungeon_type(
            dungeon_type,
            stage,
                               team1_preset=team1_preset,
                               team2_preset=team2_preset):
            logger.error(f'Failed to navigate to stage {stage_num}')
            return (False, 0)

        # 执行 Battle 1 (上半) - Standard SRC pattern
        from tasks.forgotten_hall.assets.assets_forgotten_hall_ui import BATTLE_FAILED
        from tasks.combat.assets.assets_combat_finish import COMBAT_AGAIN
        from tasks.forgotten_hall.assets.assets_forgotten_hall_ui import RETURN_TO_FORGOTTEN_HALL
        from tasks.base.assets.assets_base_page import FORGOTTEN_HALL_CHECK

        logger.hr('Battle 1: Upper Half', level=2)

        # Step 1: Enter dungeon
        self._click_enter_dungeon(skip_first_screenshot=True)

        # Step 2: Auto engage enemy
        engage_success = self.auto_engage_enemy(move_duration=8, timeout=15)
        if not engage_success:
            logger.warning('Failed to engage enemy in Battle 1')
            self.exit_dungeon()
            return (False, 0)

        # Step 3: Execute combat with battle end detection
        def is_battle_end():
            if not hasattr(self, '_battle1_end_stuck_timer'):
                self._battle1_end_stuck_timer = Timer(10).start()

            if self._battle1_end_stuck_timer.reached():
                self.device.stuck_record_clear()
                self._battle1_end_stuck_timer.reset()

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

        # Step 4: Check result
        self.device.screenshot()
        if self.appear(BATTLE_FAILED):
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
