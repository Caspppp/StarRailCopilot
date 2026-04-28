"""
深渊挑战任务

手动触发的深渊挑战功能，支持混沌回忆、忘却之庭、虚构叙事、末日幻影。
支持自动选关模式：自动扫描关卡星数，从最高未完成关卡开始挑战。
"""

from dataclasses import dataclass

from module.logger import logger
from module.base.timer import Timer
from tasks.base.assets.assets_base_page import FORGOTTEN_HALL_CHECK
from tasks.forgotten_hall.ui import ForgottenHallUI
from tasks.forgotten_hall.keywords import KEYWORDS_FORGOTTEN_HALL_STAGE
from tasks.forgotten_hall.challenge_modes.apocalyptic_shadow import MODE as APOCALYPTIC_SHADOW_MODE
from tasks.forgotten_hall.challenge_modes.memory_of_chaos import MODE as MEMORY_OF_CHAOS_MODE
from tasks.forgotten_hall.challenge_modes.pure_fiction import MODE as PURE_FICTION_MODE
from tasks.forgotten_hall.challenge_modes.towering_citadel import MODE as TOWERING_CITADEL_MODE

DUNGEON_MODES = {
    MEMORY_OF_CHAOS_MODE.dungeon_type: MEMORY_OF_CHAOS_MODE,
    TOWERING_CITADEL_MODE.dungeon_type: TOWERING_CITADEL_MODE,
    PURE_FICTION_MODE.dungeon_type: PURE_FICTION_MODE,
    APOCALYPTIC_SHADOW_MODE.dungeon_type: APOCALYPTIC_SHADOW_MODE,
}


@dataclass(frozen=True)
class HalfBattleResult:
    success: bool
    attempts: int
    reason: str = ''


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

    def _get_mode(self, dungeon_type: str):
        return DUNGEON_MODES.get(dungeon_type)

    def _get_max_stage(self, dungeon_type: str) -> int | None:
        mode = self._get_mode(dungeon_type)
        if mode is None:
            return None
        return mode.max_stage

    def _get_dungeon_display_name(self, dungeon_type: str) -> str:
        mode = self._get_mode(dungeon_type)
        if mode is None:
            return dungeon_type
        return mode.display_name

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
                if dungeon_type in DUNGEON_MODES:
                    supported.append(dungeon_type)
                else:
                    logger.warning(f'Ignored unknown dungeon type in DungeonTypes: {dungeon_type}')
            if supported:
                return supported

        return [self.config.ForgottenHallChallenge_DungeonType]

    @staticmethod
    def _safe_int(value, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _get_buff_config(self, key: str, default: int = 1) -> int | str | list[str]:
        """
        Pure Fiction Buff 配置：支持数字选项（1/2/3）或 OCR 关键字（字符串/字符串列表）。
        - int / 数字字符串：按选项编号选择
        - 非数字字符串 / 字符串列表：按关键字匹配 Buff 文本后选择
        """
        value = getattr(self.config, key, default)
        if value is None:
            return 0

        if isinstance(value, int):
            return value

        if isinstance(value, str):
            text = value.strip()
            if not text:
                return 0
            if text.isdigit():
                return int(text)
            return text

        if isinstance(value, list):
            cleaned = [str(v).strip() for v in value if str(v).strip()]
            return cleaned

        try:
            return int(value)
        except (TypeError, ValueError):
            text = str(value).strip()
            return text if text else 0

    def _battle_end_checker(self, battle_num: int, include_pure_fiction_return: bool = False):
        from tasks.combat.assets.assets_combat_finish import COMBAT_AGAIN
        from tasks.forgotten_hall.assets.assets_forgotten_hall_ui import BATTLE_FAILED, RETURN_TO_FORGOTTEN_HALL
        from tasks.base.assets.assets_base_page import FORGOTTEN_HALL_CHECK
        from tasks.forgotten_hall.assets.assets_pure_fiction_ui import PURE_FICTION_RETURN

        timer_attr = '_battle1_end_stuck_timer' if battle_num == 1 else '_battle_end_stuck_timer'
        log_prefix = f'Battle {battle_num} is_battle_end'

        def is_battle_end():
            """Check if battle has ended (success or failure)."""
            if not hasattr(self, timer_attr):
                setattr(self, timer_attr, Timer(10).start())

            timer = getattr(self, timer_attr)
            if timer.reached():
                logger.info(f'[{log_prefix}] Clear stuck record (10s interval)')
                self.device.stuck_record_clear()
                timer.reset()

            if self.appear(BATTLE_FAILED, interval=0.5):
                logger.info(f'[{log_prefix}] BATTLE_FAILED detected')
                return True

            if self.appear(RETURN_TO_FORGOTTEN_HALL, interval=0.5):
                logger.info(f'[{log_prefix}] RETURN_TO_FORGOTTEN_HALL detected')
                return True

            if self.appear(COMBAT_AGAIN, interval=0.5):
                logger.info(f'[{log_prefix}] COMBAT_AGAIN detected')
                return True

            if include_pure_fiction_return and self.appear(PURE_FICTION_RETURN, interval=0.5):
                logger.info(f'[{log_prefix}] PURE_FICTION_RETURN detected')
                return True

            if self.appear(FORGOTTEN_HALL_CHECK, interval=0.5):
                logger.info(f'[{log_prefix}] FORGOTTEN_HALL_CHECK detected')
                return True

            return False

        return is_battle_end

    def _execute_battle_combat(self, battle_num: int, include_pure_fiction_return: bool = False) -> bool:
        from tasks.forgotten_hall.assets.assets_forgotten_hall_ui import BATTLE_FAILED

        self.combat_execute(
            expected_end=self._battle_end_checker(
                battle_num=battle_num,
                include_pure_fiction_return=include_pure_fiction_return,
            )
        )
        self.device.screenshot()
        return not self.appear(BATTLE_FAILED)

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
            team1_buff = self._get_buff_config('ForgottenHallChallenge_Team1Buff', default=1)
            team2_buff = self._get_buff_config('ForgottenHallChallenge_Team2Buff', default=1)
            dungeon_types = self._get_selected_dungeon_types()

            logger.hr('Forgotten Hall Challenge Configuration', level=1)
            logger.info(f'Dungeon Types: {dungeon_types}')
            logger.info(f'Auto Stage Selection: {auto_selection}')
            logger.info(f'Team1 Preset: {team1_preset}')
            logger.info(f'Team2 Preset: {team2_preset}')
            if 'Pure_Fiction' in dungeon_types:
                logger.info(f'Team1 Buff: {team1_buff}, Team2 Buff: {team2_buff}')

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
                    team1_buff=team1_buff,
                    team2_buff=team2_buff,
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
        team1_buff: int | str | list[str],
        team2_buff: int | str | list[str],
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
            team1_buff=team1_buff,
            team2_buff=team2_buff,
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

                logger.info(f'Preparing retry attempt {attempt + 1}')
                continue

            logger.info(f'Battle 1 Attempt {attempt}: Executing combat')
            if not self._execute_battle_combat(battle_num=1):
                logger.warning(f'Battle 1 failed on attempt {attempt}/{max_retries}')

                if not self.handle_battle_failure():
                    logger.error('Failed to return to stage selection')
                    return False

                if attempt >= max_retries:
                    logger.error(f'Battle 1 failed after {max_retries} retries')
                    break

                logger.info(f'Preparing retry attempt {attempt + 1}')
                continue

            logger.info(f'Battle 1 succeeded on attempt {attempt}/{max_retries}')
            logger.info('Staying in dungeon for Battle 2')
            battle1_success = True
            break

        battle1_result = HalfBattleResult(
            success=battle1_success,
            attempts=attempts_battle1,
            reason='' if battle1_success else 'max_retries',
        )

        if not battle1_result.success:
            logger.hr('Battle 1 Failed', level=1)
            logger.attr('Attempts', battle1_result.attempts)
            logger.error('Battle 1 failed after maximum retries')
            logger.info('Currently at stage selection screen')
            return False

        logger.hr('Battle 1 Completed Successfully', level=1)
        logger.attr('Attempts', battle1_result.attempts)
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
            if self._execute_battle_combat(battle_num=2):
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

            logger.info(f'Preparing retry attempt {attempt + 1}')

            logger.info(f'Re-entering dungeon for Battle 2 retry attempt {attempt + 1}')
            self.enter_forgotten_hall_dungeon(skip_first_screenshot=False)

        battle2_result = HalfBattleResult(
            success=battle2_success,
            attempts=attempts_battle2,
            reason='' if battle2_success else 'max_retries',
        )

        if battle2_result.success:
            logger.hr('Battle 2 Completed Successfully', level=1)
            logger.attr('Attempts', battle2_result.attempts)
            logger.info('Both battles completed, returned to forgotten hall')

            logger.hr('Challenge Complete - All Battles Successful', level=1)
            logger.attr('Battle 1 Attempts', battle1_result.attempts)
            logger.attr('Battle 2 Attempts', battle2_result.attempts)
            return True

        logger.hr('Battle 2 Failed', level=1)
        logger.attr('Attempts', battle2_result.attempts)
        logger.error('Battle 2 failed after maximum retries')
        logger.info('Currently at stage selection screen')

        logger.hr('Challenge Incomplete - Battle 2 Failed', level=1)
        logger.attr('Battle 1 Attempts', battle1_result.attempts)
        logger.attr('Battle 2 Attempts', battle2_result.attempts)
        return False

    def run_auto_selection(self, dungeon_type: str | None = None):
        """
        自动选关入口，按深渊类型分发到对应模式逻辑。
        """
        try:
            dungeon_type = dungeon_type or self.config.ForgottenHallChallenge_DungeonType
            team1_preset = int(self.config.ForgottenHallChallenge_Team1Preset)
            team2_preset = int(self.config.ForgottenHallChallenge_Team2Preset)
            team1_buff = self._get_buff_config('ForgottenHallChallenge_Team1Buff', default=1)
            team2_buff = self._get_buff_config('ForgottenHallChallenge_Team2Buff', default=1)
            target_stars = int(getattr(self.config, 'ForgottenHallChallenge_TargetStars', 3))
            min_stage = int(getattr(self.config, 'ForgottenHallChallenge_MinStage', 1))

            mode = self._get_mode(dungeon_type)
            if mode is None:
                logger.error(f'Unknown dungeon type: {dungeon_type}')
                return False

            return mode.run_auto_selection(
                self,
                team1_preset=team1_preset,
                team2_preset=team2_preset,
                team1_buff=team1_buff,
                team2_buff=team2_buff,
                target_stars=target_stars,
                min_stage=min_stage,
            )
        except Exception as e:
            logger.error(f'Auto selection challenge failed: {e}')
            logger.exception(e)
            return False

    def _challenge_stage(
        self,
        dungeon_type: str,
        stage_num: int,
        team1_preset: int,
        team2_preset: int,
        team1_buff: int | str | list[str],
        team2_buff: int | str | list[str],
        target_stars: int = 3,
    ) -> tuple:
        """
        挑战单个关卡

        Args:
            dungeon_type: 深渊类型
            stage_num: 关卡编号
            team1_preset: 上半预设编队
            team2_preset: 下半预设编队
            team1_buff: 上半 Buff 选项编号（仅虚构叙事）
            team2_buff: 下半 Buff 选项编号（仅虚构叙事）
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
            team2_preset=team2_preset,
            team1_buff=team1_buff,
            team2_buff=team2_buff,
        ):
            logger.error(f'Failed to navigate to stage {stage_num}')
            return (False, 0)

        # 执行 Battle 1 (上半) - Standard SRC pattern
        logger.hr('Battle 1: Upper Half', level=2)

        # Step 1: Enter dungeon
        self._click_enter_dungeon(skip_first_screenshot=True)

        # Step 2: Auto engage enemy
        engage_success = self.auto_engage_enemy(move_duration=8, timeout=15)
        if not engage_success:
            logger.warning('Failed to engage enemy in Battle 1')
            self.exit_dungeon()
            return (False, 0)

        # Step 3-4: Execute combat with battle end detection and check result
        if not self._execute_battle_combat(battle_num=1, include_pure_fiction_return=True):
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

        # 执行战斗并判断战斗结果
        if not self._execute_battle_combat(battle_num=2, include_pure_fiction_return=True):
            logger.warning('Battle 2 failed')
            self.handle_battle_failure()
            return (False, 0)

        # 战斗成功，处理结算界面
        logger.info('Battle 2 succeeded')
        self.handle_battle_success()

        mode = self._get_mode(dungeon_type)
        if mode is None:
            actual_stars = self.get_stage_star_count(stage_num)
        else:
            actual_stars = mode.get_stage_star_count(self, stage_num, target_stars)
        if actual_stars < 0:
            actual_stars = 0

        logger.info(f'Stage {stage_num} completed with {actual_stars} stars (target: {target_stars})')

        if actual_stars >= target_stars:
            return (True, actual_stars)
        else:
            return (False, actual_stars)
