import cv2
import numpy as np
import os
import re
import time
from dataclasses import dataclass

from module.base.timer import Timer
from module.base.utils import crop, save_image
from module.logger.logger import logger, logger_debug
from tasks.base.assets.assets_base_page import CLOSE, FORGOTTEN_HALL_CHECK, MAP_EXIT
from tasks.base.page import page_guide
from tasks.dungeon.keywords import DungeonList, KEYWORDS_DUNGEON_LIST
from tasks.forgotten_hall.assets.assets_forgotten_hall_nav import *
from tasks.forgotten_hall.assets.assets_forgotten_hall_ui import *
from tasks.forgotten_hall.assets.assets_pure_fiction_ui import (
    PURE_FICTION_CLEAR_ICON,
    PURE_FICTION_ENTER_STORY,
    PURE_FICTION_PRESET_ICON,
    PURE_FICTION_PRESET_TAB_SELECTED,
    PURE_FICTION_PRESET_TAB_UNSELECTED,
    PURE_FICTION_RETURN,
    PURE_FICTION_ROW1_EMPTY,
    PURE_FICTION_ROW2_EMPTY,
)
from tasks.forgotten_hall.assets.assets_stage_selection_ui import STAGE_REWARD_BUTTON_LOWER
from tasks.forgotten_hall.keywords import ForgottenHallStage, KEYWORDS_FORGOTTEN_HALL_STAGE
from tasks.forgotten_hall.stage_ocr import STAGE_LIST, detect_unlocked_text
from tasks.map.control.joystick import JoystickContact

class ForgottenHallBattleMixin:
    def exit_dungeon(self, skip_first_screenshot=True):
        """
        Pages:
            in: page_main, in forgotten hall map
            out: page_forgotten_hall, FORGOTTEN_HALL_CHECK
        """
        logger.info('Exit dungeon')
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(FORGOTTEN_HALL_CHECK):
                logger.info("Forgotten hall dungeon exited")
                break

            if self.is_in_map_exit(interval=2):
                self.device.click(MAP_EXIT)
                continue
            if self.handle_popup_confirm():
                continue
            if self.handle_popup_single():
                continue

    def detect_battle_result(self, timeout=10, skip_first_screenshot=True):
        """
        Detect battle result after combat_execute() completes

        Args:
            timeout: Maximum time to wait for result detection (seconds)
            skip_first_screenshot: Whether to skip first screenshot

        Returns:
            str: 'success', 'failure', or 'timeout'

        Pages:
            in: After combat_execute()
            out: COMBAT_AGAIN (success) or BATTLE_FAILED (failure)
        """
        from tasks.combat.assets.assets_combat_finish import COMBAT_AGAIN
        from tasks.forgotten_hall.assets.assets_forgotten_hall_ui import BATTLE_FAILED

        logger.hr('Detect battle result', level=2)
        timer = Timer(timeout).start()
        stuck_clear_timer = Timer(10).start()  # 每 10 秒清除一次 stuck record

        while not timer.reached():
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 定期清除 stuck record（遵循 SRC 官方模式，参考 tasks/login/login.py）
            # 解决 handle_combat_damage_change() 失效导致的 wait too long 问题
            if stuck_clear_timer.reached():
                logger.info('[detect_battle_result] Clear stuck record (10s interval)')
                self.device.stuck_record_clear()
                stuck_clear_timer.reset()

            # 使用 appear() + interval 替代 match_template_color()
            if self.appear(COMBAT_AGAIN, interval=0.5):
                logger.info('Battle succeeded - COMBAT_AGAIN detected')
                return 'success'

            if self.appear(BATTLE_FAILED, interval=0.5):
                logger.info('Battle failed - BATTLE_FAILED detected')
                return 'failure'

        logger.warning(f'Battle result detection timeout after {timeout}s')
        return 'timeout'

    def handle_battle_failure(self, skip_first_screenshot=False):
        """
        Handle battle failure screen and return to stage selection

        Args:
            skip_first_screenshot: Whether to skip first screenshot

        Returns:
            bool: True if successfully returned to stage selection

        Pages:
            in: BATTLE_FAILED screen
            out: FORGOTTEN_HALL_CHECK (stage selection)
        """
        from tasks.forgotten_hall.assets.assets_forgotten_hall_ui import RETURN_TO_FORGOTTEN_HALL

        logger.hr('Handle battle failure', level=2)
        timeout = Timer(10).start()
        clicked_return = False

        while not timeout.reached():
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # End condition: back at stage selection
            if (
                self.appear(FORGOTTEN_HALL_CHECK)
                or self.match_template_color(STAGE_REWARD_BUTTON_LOWER, interval=0)
                or self.match_template_color(PURE_FICTION_ENTER_STORY, interval=0)
                or self.appear(PURE_FICTION_TEAM_BUTTON, interval=0)
                or self.appear(PURE_FICTION_TEAM_TITLE, interval=0)
            ):
                logger.info('Successfully returned to stage selection')
                if self.appear(FORGOTTEN_HALL_CHECK, interval=0):
                    self.device.screenshot()
                    STAGE_LIST.load_rows(main=self)
                return True

            # Click return button using match_template_color for better detection
            if not clicked_return and self.match_template_color(RETURN_TO_FORGOTTEN_HALL, interval=2):
                self.device.click(RETURN_TO_FORGOTTEN_HALL)
                logger.info('Clicked return to forgotten hall button')
                clicked_return = True
                continue

        logger.error('Failed to return to stage selection after battle failure')
        return False

    def handle_battle_success(self):
        """
        Handle battle success by clicking through reward screens

        Returns:
            bool: True if successfully handled

        Pages:
            in: COMBAT_AGAIN screen
            out: FORGOTTEN_HALL_CHECK
        """
        from tasks.combat.assets.assets_combat_finish import COMBAT_AGAIN
        from tasks.forgotten_hall.assets.assets_forgotten_hall_ui import (
            QUICK_COMPLETE_TITLE, QUICK_COMPLETE_CONFIRM
        )

        logger.hr('Handle battle success', level=2)
        timeout = Timer(15).start()

        while not timeout.reached():
            self.device.screenshot()

            # 处理快速通关弹窗（3星通关时前置关卡奖励解锁提示）
            if self.appear(QUICK_COMPLETE_TITLE, interval=2):
                logger.info('Quick complete popup detected, clicking confirm')
                self.device.click(QUICK_COMPLETE_CONFIRM)
                continue

            if (
                self.appear(FORGOTTEN_HALL_CHECK)
                or self.match_template_color(STAGE_REWARD_BUTTON_LOWER, interval=0.2)
                or self.match_template_color(PURE_FICTION_ENTER_STORY, interval=0.2)
                or self.appear(PURE_FICTION_TEAM_BUTTON, interval=0.2)
                or self.appear(PURE_FICTION_TEAM_TITLE, interval=0.2)
            ):
                logger.info('Battle success handled, returned to stage selection')
                return True

            # Pure Fiction battle result may not show COMBAT_AGAIN; return button leads back to stage selection.
            if self.appear_then_click(PURE_FICTION_RETURN, interval=2):
                continue

            if self.appear_then_click(COMBAT_AGAIN, interval=3):
                continue

            if self.handle_reward(interval=2):
                continue

            if self.handle_popup_confirm():
                continue
            if self.handle_popup_single():
                continue

        logger.warning('Battle success handling timeout')
        return True

    def enter_and_battle_with_retry(self, max_retries=3, skip_first_screenshot=True):
        """
        Enter dungeon, battle, and auto-retry on failure

        Args:
            max_retries: Maximum number of retry attempts
            skip_first_screenshot: Whether to skip first screenshot

        Returns:
            tuple: (success: bool, attempts_used: int)

        Pages:
            in: FORGOTTEN_HALL_CHECK (stage selection)
            out: FORGOTTEN_HALL_CHECK (after battle)
        """
        logger.hr('Enter dungeon with auto-retry enabled', level=1)
        logger.attr('MaxRetries', max_retries)

        for attempt in range(1, max_retries + 1):
            logger.hr(f'Battle Attempt {attempt}/{max_retries}', level=2)

            # Step 1: Enter dungeon
            logger.info(f'Attempt {attempt}: Entering dungeon')
            self.enter_forgotten_hall_dungeon(skip_first_screenshot=skip_first_screenshot)
            skip_first_screenshot = False

            # Step 2: Detect result
            logger.info(f'Attempt {attempt}: Detecting battle result')
            result = self.detect_battle_result(timeout=10)

            # Step 3: Handle result
            if result == 'success':
                logger.info(f'Battle succeeded on attempt {attempt}/{max_retries}')
                self.handle_battle_success()
                return (True, attempt)

            elif result == 'failure':
                logger.warning(f'Battle failed on attempt {attempt}/{max_retries}')

                if not self.handle_battle_failure():
                    logger.error(f'Failed to return to stage selection, cannot retry')
                    return (False, attempt)

                if attempt >= max_retries:
                    logger.error(f'Max retries ({max_retries}) exceeded, giving up')
                    return (False, attempt)

                logger.info(f'Preparing retry attempt {attempt+1}')
                continue

            else:  # timeout
                logger.error(f'Battle result detection timeout on attempt {attempt}')
                logger.info('Attempting to exit dungeon after timeout')
                self.exit_dungeon()

                if attempt >= max_retries:
                    logger.error(f'Max retries ({max_retries}) exceeded after timeout')
                    return (False, attempt)

                logger.info(f'Retrying after timeout, attempt {attempt+1}')
                continue

        logger.error('Unexpected exit from retry loop')
        return (False, max_retries)

    def _click_enter_dungeon(self, skip_first_screenshot=True, timeout: float = 20.0):
        """
        Click enter button to enter forgotten hall dungeon (without combat execution)

        This method only handles entering the dungeon itself, not the combat.
        For full dungeon entry with combat, use enter_forgotten_hall_dungeon() instead.

        Args:
            skip_first_screenshot: Whether to skip first screenshot

        Pages:
            in: ENTRANCE_CHECKED, ENTER_FORGOTTEN_HALL_DUNGEON
            out: In dungeon (map exit / combat executing)
        """
        from tasks.forgotten_hall.assets.assets_forgotten_hall_ui import ENTER_FORGOTTEN_HALL_DUNGEON

        logger.info('Entering forgotten hall dungeon')
        click_interval = Timer(2.0).start()
        overall_timeout = Timer(timeout).start()
        clicked = False

        while not overall_timeout.reached():
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self._handle_forgotten_hall_click_blank_prompt(interval=0.8):
                continue

            # Handle any FH buff popups that block the screen after entering.
            if self.handle_forgotten_hall_buff(interval=0.8):
                continue

            # Success: in dungeon map or already in combat.
            if self.is_combat_executing():
                logger.info('Successfully entered dungeon (combat detected)')
                break
            if self.is_in_map_exit(interval=0):
                logger.info('Successfully entered dungeon (map detected)')
                break

            if not clicked and self.appear(ENTER_FORGOTTEN_HALL_DUNGEON, interval=0):
                clicked = True

            # Click enter button when ready.
            if click_interval.reached() and self.team_prepared():
                self.device.click(ENTER_FORGOTTEN_HALL_DUNGEON)
                click_interval.reset()

        else:
            if clicked:
                logger.warning('[ForgottenHall] Enter dungeon timeout, continuing...')
            else:
                logger.warning('[ForgottenHall] Enter dungeon: enter button not found, continuing...')

    def enter_forgotten_hall_dungeon(self, skip_first_screenshot=True):
        """
        Enter forgotten hall dungeon and execute combat (standard SRC pattern)

        This is a convenience method that combines entering the dungeon
        and executing combat. For more control, use _click_enter_dungeon()
        and combat_execute() separately.

        Pages:
            in: ENTRANCE_CHECKED, ENTER_FORGOTTEN_HALL_DUNGEON
            out: page_main, in forgotten hall map
        """
        # Step 1: Enter dungeon
        self._click_enter_dungeon(skip_first_screenshot=skip_first_screenshot)

        # Step 2: Auto engage enemy
        logger.info('Dungeon entered, starting auto engage enemy')
        success = self.auto_engage_enemy(move_duration=8, timeout=15)

        if not success:
            logger.warning('Failed to auto-engage enemy')
            return

        # Step 3: Execute combat with standard battle end detection
        logger.info('Successfully engaged enemy, executing combat')

        from tasks.combat.assets.assets_combat_finish import COMBAT_AGAIN
        from tasks.forgotten_hall.assets.assets_forgotten_hall_ui import (
            BATTLE_FAILED,
            RETURN_TO_FORGOTTEN_HALL
        )
        from tasks.base.assets.assets_base_page import FORGOTTEN_HALL_CHECK

        def is_battle_end():
            """Check if battle has ended (success or failure)"""
            # Clear stuck record periodically (SRC standard pattern)
            if not hasattr(self, '_battle_end_stuck_timer'):
                self._battle_end_stuck_timer = Timer(10).start()

            if self._battle_end_stuck_timer.reached():
                logger.info('[is_battle_end] Clear stuck record (10s interval)')
                self.device.stuck_record_clear()
                self._battle_end_stuck_timer.reset()

            # Check all end conditions
            if self.appear(BATTLE_FAILED, interval=0.5):
                logger.info('[is_battle_end] BATTLE_FAILED detected')
                return True

            if self.appear(RETURN_TO_FORGOTTEN_HALL, interval=0.5):
                logger.info('[is_battle_end] RETURN_TO_FORGOTTEN_HALL detected')
                return True

            if self.appear(COMBAT_AGAIN, interval=0.5):
                logger.info('[is_battle_end] COMBAT_AGAIN detected')
                return True

            if self.appear(FORGOTTEN_HALL_CHECK, interval=0.5):
                logger.info('[is_battle_end] FORGOTTEN_HALL_CHECK detected')
                return True

            return False

        self.combat_execute(expected_end=is_battle_end)

    def auto_engage_enemy(self, move_duration=8, timeout=15, skip_first_screenshot=True):
        """
        Automatically move forward and engage enemy in forgotten hall dungeon.
        Uses simple forward movement with continuous enemy detection.

        Args:
            move_duration: How long to move forward (seconds), default 8
            timeout: Maximum time to spend trying to find enemy (seconds), default 15
            skip_first_screenshot: Whether to skip first screenshot

        Returns:
            bool: True if successfully engaged in combat, False otherwise

        Pages:
            in: DUNGEON_ENTER_CHECKED (just entered dungeon)
            out: is_combat_executing() or timeout
        """
        logger.hr('Auto engage enemy', level=1)
        logger.attr('MoveDuration', move_duration)
        logger.attr('Timeout', timeout)

        # Initialize timers
        move_timer = Timer(move_duration).start()
        timeout_timer = Timer(timeout).start()
        enemy_check_interval = Timer(0.3).start()
        movement_interval = Timer(0.5).start()

        # Phase 1: Move forward while detecting enemies
        logger.info('Phase 1: Moving forward and detecting enemies')
        with JoystickContact(self) as contact:
            while not move_timer.reached():
                if skip_first_screenshot:
                    skip_first_screenshot = False
                else:
                    self.device.screenshot()

                # Check if already in combat (early success)
                if self.is_combat_executing():
                    logger.info('Entered combat during movement')
                    return True

                # Enable 2x running
                self.handle_map_run_2x()

                # Set joystick to move forward (direction=0 means forward)
                if movement_interval.reached():
                    contact.set(direction=0, run=True)
                    movement_interval.reset()

                # Enemy detection
                if enemy_check_interval.reached():
                    self.aim.predict(self.device.image, enemy=True, item=False, show_log=False)
                    if self.aim.aimed_enemy:
                        logger.info(f'Enemy detected at {self.aim.aimed_enemy}')
                        # Click attack button
                        self.handle_map_A()
                    enemy_check_interval.reset()

                # Check timeout
                if timeout_timer.reached():
                    logger.warning('Auto engage timeout during movement phase')
                    break

        # Phase 2: Continue searching for enemy without movement
        logger.info('Phase 2: Stationary enemy search')
        while not timeout_timer.reached():
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # Check combat
            if self.is_combat_executing():
                logger.info('Entered combat after movement')
                return True

            # Keep detecting and attacking
            if enemy_check_interval.reached():
                self.aim.predict(self.device.image, enemy=True, item=False, show_log=False)
                if self.aim.aimed_enemy:
                    logger.info(f'Enemy detected at {self.aim.aimed_enemy}')
                    self.handle_map_A()
                enemy_check_interval.reset()

        # Phase 3: Fallback mechanism
        logger.warning('Auto engage enemy timeout, using combat_poor_try fallback')
        result = self.combat_poor_try()
        success = len(result) > 0
        if success:
            logger.info('Combat engaged via fallback mechanism')
        else:
            logger.warning('Failed to engage enemy even with fallback')
        return success
