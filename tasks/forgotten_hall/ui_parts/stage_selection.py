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

class ForgottenHallStageSelectionMixin:
    APOCALYPTIC_SHADOW_STAGE_BUTTON_AREA = (177, 626, 1102, 662)
    APOCALYPTIC_SHADOW_STAGE_COUNT = 4
    def apocalyptic_shadow_get_stage_button_areas(self) -> dict[int, tuple[int, int, int, int]]:
        """
        末日幻影（Apocalyptic Shadow）底部 1-4 关按钮区域划分。

        用户给定总区域：area=(177, 626, 1102, 662)
        该区域按水平均分为 4 段，分别对应 1-4 关。
        """
        raw_areas = self._split_area_horizontally(
            self.APOCALYPTIC_SHADOW_STAGE_BUTTON_AREA,
            self.APOCALYPTIC_SHADOW_STAGE_COUNT,
        )
        areas: dict[int, tuple[int, int, int, int]] = {}
        for idx, (x1, y1, x2, y2) in enumerate(raw_areas, start=1):
            pad_x = min(8, max(0, (x2 - x1) // 6))
            pad_y = min(4, max(0, (y2 - y1) // 6))
            areas[idx] = (x1 + pad_x, y1 + pad_y, x2 - pad_x, y2 - pad_y)
        return areas

    def apocalyptic_shadow_select_stage(self, stage_num: int, skip_first_screenshot=True, timeout: float = 8.0) -> bool:
        """
        在末日幻影选关界面点击指定关卡（1-4）。

        使用底部按钮区域中心点作为点击坐标，并等待 ENTRANCE_CHECKED。
        """
        from module.base.button import ClickButton

        areas = self.apocalyptic_shadow_get_stage_button_areas()
        if stage_num not in areas:
            logger.error(f'[ApocalypticShadow] Invalid stage: {stage_num}')
            return False

        x, y = self._area_center(areas[stage_num])
        click_button = ClickButton(
            area=(x - 4, y - 4, x + 4, y + 4),
            name=f'ApocalypticShadowStage_{stage_num}',
        )

        for attempt in range(1, 4):
            logger.info(f'[ApocalypticShadow] Select stage {stage_num} (attempt {attempt}/3)')

            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.handle_forgotten_hall_buff():
                continue

            self.device.click(click_button)

            wait = Timer(timeout).start()
            while not wait.reached():
                self.device.screenshot()
                if self.handle_forgotten_hall_buff():
                    continue
                if self.appear(ENTRANCE_CHECKED, interval=0.2):
                    logger.info(f'[ApocalypticShadow] Stage {stage_num} selected')
                    return True

        logger.error(f'[ApocalypticShadow] Failed to select stage {stage_num}')
        return False

    def stage_choose(self, dungeon: DungeonList, skip_first_screenshot=True, timeout: float = 20.0) -> bool:
        """
        Pages:
            in: page_forgotten_hall, FORGOTTEN_HALL_CHECK
                or page_guide, Survival_Index, Forgotten_Hall
            out: page_forgotten_hall, FORGOTTEN_HALL_CHECK, selected at the given dungeon tab
        """
        logger.info(f'Stage choose {dungeon}')
        if dungeon == KEYWORDS_DUNGEON_LIST.Memory_of_Chaos:
            check_button = MEMORY_OF_CHAOS_CHECK
            click_button = MEMORY_OF_CHAOS_CLICK
        elif dungeon == KEYWORDS_DUNGEON_LIST.The_Last_Vestiges_of_Towering_Citadel:
            check_button = LAST_VASTIGES_CHECK
            click_button = LAST_VASTIGES_CLICK
        else:
            logger.error(f'Choosing {dungeon} in forgotten hall is not supported')
            return False

        timeout_timer = Timer(timeout).start()
        while not timeout_timer.reached():
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # interval used in end condition
            # After clicking `click_button`, `click_button` appears, then screen goes black for a little while
            # interval prevents `check_button` being triggered in the next 0.3s
            if self.match_template_color(check_button, interval=0.3):
                logger.info(f'Stage chose at {dungeon}')
                return True
            if self.handle_forgotten_hall_buff():
                continue
            if self.appear_then_click(TELEPORT, interval=2):
                continue
            if self.match_template_color(click_button, interval=1):
                self.device.click(click_button)
                self.interval_reset(check_button)
                continue

        logger.error(f'Stage choose {dungeon} timeout after {timeout}s')
        return False

    def goto_stage_selection(self, dungeon: DungeonList):
        """
        只导航到深渊关卡选择界面，不选择任何关卡

        用于自动选关模式：进入后游戏会自动定格在最高可挑战关卡

        Args:
            dungeon: 深渊类型（Memory_of_Chaos 或 The_Last_Vestiges_of_Towering_Citadel）

        Returns:
            bool: 是否成功导航到选关界面
        """
        if self.appear(FORGOTTEN_HALL_CHECK):
            logger.info('Already in forgotten hall')
        else:
            self.ui_ensure(page_guide)
            from tools.forgotten_hall_navigator import TreasuresLightwardNavigator
            navigator = TreasuresLightwardNavigator()
            if not navigator.goto_forgotten_hall_from_guide(self.device):
                logger.error('Failed to navigate to Forgotten Hall')
                return False

        if not self.stage_choose(dungeon):
            return False
        return True

    def _wait_for_stage_list_loaded(self, timeout: float = 20.0, skip_first_screenshot=True) -> bool:
        """
        等待关卡列表加载完成（逐光捡金：虚构叙事 / 末日幻影也会复用同一套关卡列表OCR）

        Returns:
            bool: 是否在超时内加载成功
        """
        timeout_timer = Timer(timeout).start()
        while not timeout_timer.reached():
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.handle_forgotten_hall_buff():
                continue

            # 仍在外部界面时可能会看到传送按钮，补点击一次
            if self.appear_then_click(TELEPORT, interval=2):
                continue

            if self.appear(FORGOTTEN_HALL_CHECK):
                STAGE_LIST.load_rows(main=self)
                if STAGE_LIST.cur_buttons:
                    return True

        logger.warning('Wait stage list loaded timeout')
        return False

    def _wait_for_apocalyptic_shadow_loaded(self, timeout: float = 20.0, skip_first_screenshot=True) -> bool:
        """
        等待末日幻影选关界面加载完成。

        Returns:
            bool: 是否在超时内加载成功
        """
        from tasks.forgotten_hall.assets.assets_apocalyptic_shadow_ui import APOCALYPTIC_SHADOW_GOTO_CHALLENGE

        timeout_timer = Timer(timeout).start()
        while not timeout_timer.reached():
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.handle_forgotten_hall_buff():
                continue

            if self.appear_then_click(TELEPORT, interval=2):
                continue

            if self.match_template_color(STAGE_REWARD_BUTTON_LOWER, interval=0.5):
                return True

            if self.match_template_color(APOCALYPTIC_SHADOW_GOTO_CHALLENGE, interval=0.5):
                return True

        logger.warning('Wait apocalyptic shadow loaded timeout')
        return False

    def _new_treasures_lightward_navigator(self):
        from tools.forgotten_hall_navigator import TreasuresLightwardNavigator

        return TreasuresLightwardNavigator()

    def _handle_pure_fiction_start_story(self, navigator=None) -> bool:
        if navigator is None:
            navigator = self._new_treasures_lightward_navigator()
        return navigator.handle_pure_fiction_start_story(self.device)

    def _pure_fiction_stage_selection_ready(self, interval: float = 0.2) -> bool:
        if self.match_template_color(STAGE_REWARD_BUTTON_LOWER, interval=interval):
            return True

        # Newer Pure Fiction page may show a stable "进入故事" button at bottom-right.
        if self.match_template_color(PURE_FICTION_ENTER_STORY, interval=interval):
            return True

        # Backward compatibility for old versions / fallback.
        return (
            self.appear(PURE_FICTION_TEAM_BUTTON, interval=interval)
            or self.appear(PURE_FICTION_TEAM_TITLE, interval=interval)
        )

    def _wait_for_pure_fiction_loaded(
        self,
        timeout: float = 12.0,
        skip_first_screenshot=True,
        navigator=None,
        ready_stability: float = 2.0,
    ) -> bool:
        """
        等待虚构叙事选关界面加载完成，并处理中途延迟弹出的“开启故事”介绍页。

        Returns:
            bool: 是否在超时内加载成功
        """
        if navigator is None:
            navigator = self._new_treasures_lightward_navigator()

        timer = Timer(timeout).start()
        ready_timer = None
        start_story_handled = False
        while not timer.reached():
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.handle_forgotten_hall_buff():
                ready_timer = None
                continue

            if self._handle_pure_fiction_start_story(navigator=navigator):
                logger.info('[PureFiction] Start story handled while waiting for stage selection')
                start_story_handled = True
                ready_timer = None
                continue

            if self._pure_fiction_stage_selection_ready(interval=0.2):
                if start_story_handled or ready_stability <= 0:
                    logger.info('[PureFiction] Stage selection confirmed')
                    return True

                if ready_timer is None:
                    ready_timer = Timer(ready_stability).start()
                    continue

                if ready_timer.reached():
                    logger.info('[PureFiction] Stage selection confirmed stable')
                    return True
                continue

            ready_timer = None

        logger.warning('Wait pure fiction loaded timeout')
        return False

    def goto_stage_selection_by_dungeon_type(self, dungeon_type: str) -> bool:
        """
        根据配置中的 DungeonType/DungeonTypes 导航到对应模式的关卡选择界面

        Args:
            dungeon_type: Memory_of_Chaos / The_Last_Vestiges_of_Towering_Citadel / Pure_Fiction / Apocalyptic_Shadow
        """
        if dungeon_type == 'Memory_of_Chaos':
            return self.goto_stage_selection(KEYWORDS_DUNGEON_LIST.Memory_of_Chaos)
        if dungeon_type == 'The_Last_Vestiges_of_Towering_Citadel':
            return self.goto_stage_selection(KEYWORDS_DUNGEON_LIST.The_Last_Vestiges_of_Towering_Citadel)

        if dungeon_type in ('Pure_Fiction', 'Apocalyptic_Shadow'):
            # Fast path: already at target stage selection.
            # Pure Fiction/Apocalyptic Shadow stage selection pages are not part of the base UI page map,
            # so blindly calling ui_ensure(page_guide) would treat them as "Unknown ui page" and press BACK,
            # causing an unnecessary exit/re-enter loop.
            navigator = None
            self.device.screenshot()
            if self.handle_forgotten_hall_buff(interval=0):
                self.device.screenshot()

            if dungeon_type == 'Pure_Fiction':
                if self._pure_fiction_stage_selection_ready(interval=0):
                    logger.info('[PureFiction] Stage selection marker visible, confirming page state')
                    return self._wait_for_pure_fiction_loaded(
                        timeout=12.0,
                        skip_first_screenshot=True,
                    )

                navigator = self._new_treasures_lightward_navigator()
                if self._handle_pure_fiction_start_story(navigator=navigator):
                    logger.info('[PureFiction] Start story handled from current page')
                    if not self._wait_for_pure_fiction_loaded(
                        timeout=12.0,
                        skip_first_screenshot=True,
                        navigator=navigator,
                    ):
                        logger.error('Failed to load Pure Fiction stage selection after start story')
                        return False
                    return True

            if dungeon_type == 'Apocalyptic_Shadow':
                from tasks.forgotten_hall.assets.assets_apocalyptic_shadow_ui import APOCALYPTIC_SHADOW_GOTO_CHALLENGE

                if (
                    self.match_template_color(STAGE_REWARD_BUTTON_LOWER, interval=0)
                    or self.match_template_color(APOCALYPTIC_SHADOW_GOTO_CHALLENGE, interval=0)
                ):
                    logger.info('[ApocalypticShadow] Already at stage selection, skip navigation')
                    return True

            self.ui_ensure(page_guide)

            if navigator is None:
                navigator = self._new_treasures_lightward_navigator()
            if dungeon_type == 'Pure_Fiction':
                if not navigator.goto_pure_fiction_from_guide(self.device):
                    logger.error('Failed to navigate to Pure Fiction via Treasures Lightward')
                    return False
            else:
                if not navigator.goto_apocalyptic_shadow_from_guide(self.device):
                    logger.error('Failed to navigate to Apocalyptic Shadow via Treasures Lightward')
                    return False

            if dungeon_type == 'Pure_Fiction':
                # 虚构叙事为固定页面，不依赖 STAGE_LIST OCR
                if not self._wait_for_pure_fiction_loaded(
                    timeout=12.0,
                    skip_first_screenshot=True,
                    navigator=navigator,
                ):
                    logger.error('Failed to load Pure Fiction stage selection after navigation')
                    return False
                return True

            if dungeon_type == 'Apocalyptic_Shadow':
                if not self._wait_for_apocalyptic_shadow_loaded(timeout=20.0, skip_first_screenshot=True):
                    logger.error('Failed to load apocalyptic shadow stage selection after navigation')
                    return False
                return True

            if not self._wait_for_stage_list_loaded(timeout=20.0, skip_first_screenshot=True):
                logger.error('Failed to load stage list after navigation')
                return False
            return True

        logger.error(f'Unknown dungeon type: {dungeon_type}')
        return False

    def stage_goto_by_dungeon_type(
        self,
        dungeon_type: str,
        stage_keyword: ForgottenHallStage,
        team1_preset: int = None,
        team2_preset: int = None,
        team1_buff: int | str | list[str] | None = None,
        team2_buff: int | str | list[str] | None = None,
    ) -> bool:
        """
        根据 dungeon_type 导航到指定关卡并配置预设编队
        """
        if dungeon_type == 'Memory_of_Chaos':
            return self.stage_goto(
                KEYWORDS_DUNGEON_LIST.Memory_of_Chaos,
                stage_keyword,
                team1_preset=team1_preset,
                team2_preset=team2_preset,
            )
        if dungeon_type == 'The_Last_Vestiges_of_Towering_Citadel':
            return self.stage_goto(
                KEYWORDS_DUNGEON_LIST.The_Last_Vestiges_of_Towering_Citadel,
                stage_keyword,
                team1_preset=team1_preset,
                team2_preset=team2_preset,
            )

        if dungeon_type in ('Pure_Fiction', 'Apocalyptic_Shadow'):
            if not self.goto_stage_selection_by_dungeon_type(dungeon_type):
                return False

            if dungeon_type == 'Pure_Fiction':
                team1_buff = team1_buff or 1
                team2_buff = team2_buff or 1

            if dungeon_type == 'Pure_Fiction':
                stage_num = self.pure_fiction_resolve_stage_num(stage_keyword.id)
                logger.info(f'[PureFiction] Select stage: {stage_num}')
                if not self.pure_fiction_select_stage(stage_num):
                    return False
            elif dungeon_type == 'Apocalyptic_Shadow':
                stage_num = stage_keyword.id
                logger.info(f'[ApocalypticShadow] Select stage: {stage_num}')
                if not self.apocalyptic_shadow_select_stage(stage_num):
                    return False
            else:
                logger.info(f'Stage list select: {stage_keyword}')
                STAGE_LIST.select_row(stage_keyword, main=self)

            if team1_preset or team2_preset:
                logger.hr('Configure preset teams', level=1)
                if dungeon_type == 'Pure_Fiction':
                    if not self._configure_pure_fiction_preset_teams(
                        team1_preset=team1_preset,
                        team2_preset=team2_preset,
                    ):
                        logger.error('[PureFiction] Preset teams configuration failed')
                        return False
                else:
                    if not self._click_preset_team(timeout=15):
                        logger.error('Failed to open preset team panel')
                        return False
                    if not self._configure_preset_teams(team1_preset, team2_preset, verify_method='slot'):
                        logger.error('Preset teams configuration failed')
                        return False
                logger.info('Preset teams configuration completed')

            if dungeon_type == 'Pure_Fiction' and (team1_buff or team2_buff):
                logger.hr('Configure buffs', level=1)
                if not self._configure_pure_fiction_buffs(team1_buff=team1_buff, team2_buff=team2_buff):
                    logger.warning('[PureFiction] Buff configuration may have failed, continuing...')

            return True

        logger.error(f'Unknown dungeon type: {dungeon_type}')
        return False

    def stage_goto(self, dungeon: DungeonList, stage_keyword: ForgottenHallStage,
                   team1_preset: int = None, team2_preset: int = None):
        """
        导航到指定关卡并配置预设编队

        Args:
            dungeon: 深渊类型
            stage_keyword: 目标关卡
            team1_preset: 第一关使用的预设编队编号 (1-12, 1-based)
            team2_preset: 第二关使用的预设编队编号 (1-12, 1-based)

        Examples:
            self = ForgottenHallUI('alas')
            self.device.screenshot()
            self.stage_goto(KEYWORDS_DUNGEON_LIST.The_Last_Vestiges_of_Towering_Citadel,
                            KEYWORDS_FORGOTTEN_HALL_STAGE.Stage_8,
                            team1_preset=1, team2_preset=2)

        Returns:
            bool: 是否成功
        """
        if not dungeon in [
            KEYWORDS_DUNGEON_LIST.Memory_of_Chaos,
            KEYWORDS_DUNGEON_LIST.The_Last_Vestiges_of_Towering_Citadel,

        ]:
            logger.error(f'DungeonList Chosen is not a forgotten hall: {dungeon}')
            return False
        if dungeon == KEYWORDS_DUNGEON_LIST.Memory_of_Chaos and stage_keyword.id > 12:
            logger.error(f'This dungeon "{dungeon}" does not have stage that greater than 12. '
                         f'{stage_keyword.id} is chosen')
            return False

        if self.appear(FORGOTTEN_HALL_CHECK):
            logger.info('Already in forgotten hall')
        else:
            # ★ 关键修复：先确保在 Guide 页面（星际和平指南）
            self.ui_ensure(page_guide)

            # 使用独立导航器（逐光捡金 Tab → 忘却之庭 Nav）
            # 旧路径已废弃: Survival_Index Tab → Forgotten_Hall Nav
            from tools.forgotten_hall_navigator import TreasuresLightwardNavigator

            navigator = TreasuresLightwardNavigator()
            if not navigator.goto_forgotten_hall_from_guide(self.device):
                logger.error('Failed to navigate to Forgotten Hall via Treasures Lightward')
                logger.error('Navigation failed, please check if the game UI has changed')
                return False

            # 旧代码（保留作为参考，游戏版本回退时可恢复）:
            # self.dungeon_tab_goto(KEYWORDS_DUNGEON_TAB.Survival_Index)
            # self.dungeon_nav_goto(KEYWORDS_DUNGEON_NAV.Forgotten_Hall)

        if not self.stage_choose(dungeon):
            logger.error(f'Failed to choose dungeon stage tab: {dungeon}')
            return False
        logger.info(f'Stage list select: {stage_keyword}')
        if not STAGE_LIST.select_row(stage_keyword, main=self):
            logger.error(f'Failed to select stage row: {stage_keyword}')
            return False

        # 配置预设编队
        if team1_preset or team2_preset:
            logger.hr('Configure preset teams', level=1)

            if not self._click_preset_team(timeout=15):
                logger.error('Failed to open preset team panel')
                return False

            if not self._configure_preset_teams(team1_preset, team2_preset):
                logger.error('Preset teams configuration failed')
                return False

            logger.info('Preset teams configuration completed')

        return True

    def scan_all_stages(self, max_stage: int = 12) -> dict:
        """
        扫描所有关卡的星数状态

        通过左右滑动关卡列表，识别所有可见关卡的星数
        利用现有的 STAGE_LIST.load_rows() 和 OcrResultButton.star_count

        Args:
            max_stage: 最大关卡数（混沌回忆=12, 忘却之庭=15）

        Returns:
            dict[int, int]: {关卡编号: 星数} 映射
            例如: {1: 3, 2: 3, 3: 2, 4: 0, ...}

        Pages:
            in: FORGOTTEN_HALL_CHECK (关卡选择界面)
            out: FORGOTTEN_HALL_CHECK (关卡选择界面)
        """
        logger.hr('Scan all stages', level=2)
        stage_stars = {}
        scanned_stages = set()

        # 先滑动到最左边（第1关）
        logger.info('Scrolling to stage 1')
        stage_1 = KEYWORDS_FORGOTTEN_HALL_STAGE.Stage_1
        STAGE_LIST.insight_row(stage_1, main=self)

        # 分批扫描
        max_scroll_attempts = 5
        scroll_count = 0

        while len(scanned_stages) < max_stage and scroll_count < max_scroll_attempts:
            self.device.screenshot()
            STAGE_LIST.load_rows(main=self)

            # 从当前可见关卡中提取星数
            new_stages_found = False
            for button in STAGE_LIST.cur_buttons:
                if button.matched_keyword:
                    stage_num = button.matched_keyword.id
                    if stage_num not in scanned_stages and stage_num <= max_stage:
                        # 跳过未解锁的关卡
                        if getattr(button, 'is_locked', False):
                            logger.info(f'Stage {stage_num}: locked (skipped)')
                            scanned_stages.add(stage_num)
                            stage_stars[stage_num] = -1  # 标记为未解锁
                            new_stages_found = True
                            continue

                        star_count = button.star_count if button.star_count is not None else 0
                        stage_stars[stage_num] = star_count
                        scanned_stages.add(stage_num)
                        new_stages_found = True
                        logger.info(f'Stage {stage_num}: {star_count} stars')

            # 如果还没扫描完且有新发现，向右滑动
            if len(scanned_stages) < max_stage:
                if not new_stages_found:
                    # 没有新关卡，可能已经到头了
                    logger.info('No new stages found, stopping scan')
                    break
                logger.info(f'Scrolling right, scanned {len(scanned_stages)}/{max_stage} stages')
                STAGE_LIST.drag_page('right', main=self)
                self._wait_for_stage_list_loaded(timeout=5.0, skip_first_screenshot=False)
                scroll_count += 1

        # 填充未扫描到的关卡为0星
        for i in range(1, max_stage + 1):
            if i not in stage_stars:
                stage_stars[i] = 0
                logger.warning(f'Stage {i} not scanned, assuming 0 stars')

        logger.info(f'Scan complete: {stage_stars}')
        return stage_stars

    def detect_current_highest_stage(
        self,
        max_stage: int = 12,
        target_stars: int = 3,
        dungeon_type: str | None = None,
    ) -> tuple:
        """
        从当前可见区域检测最高可挑战关卡（不滑动）

        游戏进入选关页面时自动定格在最高解锁关卡，直接识别即可

        Args:
            max_stage: 最大关卡数（混沌回忆=12, 忘却之庭=15）
            target_stars: 目标星数（默认3）

        Returns:
            tuple[int, dict]: (起始关卡, {关卡号: 星数})
            起始关卡为-1表示全部完成
        """
        logger.hr('Detect current highest stage', level=2)
        stage_stars = {}

        if dungeon_type == 'Pure_Fiction':
            self.device.screenshot()
            image = self.device.image

            stage_stars = self.pure_fiction_scan_stage_stars(image=image)
            locked = self.pure_fiction_detect_locked_stages(image=image)
            for stage_num in locked:
                stage_stars[stage_num] = -1

            highest_unlocked = max(
                (stage_num for stage_num in range(1, max_stage + 1) if stage_stars.get(stage_num, 0) != -1),
                default=0,
            )

            logger.info(f'[PureFiction] Visible stages: {stage_stars}, Highest: {highest_unlocked}')

            if highest_unlocked <= 0:
                logger.warning('[PureFiction] No stages detected in current view')
                return (1, stage_stars)

            # 若所有可挑战的关卡都已达标，则认为完成
            for stage_num in range(highest_unlocked, 0, -1):
                stars = stage_stars.get(stage_num, 0)
                if stars >= 0 and stars < target_stars:
                    logger.info(f'[PureFiction] Starting stage: {stage_num} ({stars} stars, target: {target_stars})')
                    return (stage_num, stage_stars)

            return (-1, stage_stars)

        self.device.screenshot()
        STAGE_LIST.load_rows(main=self)

        highest_unlocked = 0
        for button in STAGE_LIST.cur_buttons:
            if not button.matched_keyword:
                continue

            stage_num = button.matched_keyword.id
            if stage_num > max_stage:
                continue

            if getattr(button, 'is_locked', False):
                stage_stars[stage_num] = -1
                continue

            star_count = button.star_count if button.star_count is not None else 0
            stage_stars[stage_num] = star_count
            logger.info(f'Stage {stage_num}: {star_count} stars')

            if stage_num > highest_unlocked:
                highest_unlocked = stage_num

        logger.info(f'Visible stages: {stage_stars}, Highest: {highest_unlocked}')

        # 判断起始关卡
        if not stage_stars:
            logger.warning('No stages detected in current view')
            return (1, {})

        if highest_unlocked == max_stage and stage_stars.get(max_stage, 0) >= target_stars:
            logger.info(f'Stage {max_stage} already has {target_stars}+ stars, task complete')
            return (-1, stage_stars)

        # 找最高的未达标关卡
        for stage_num in sorted(stage_stars.keys(), reverse=True):
            stars = stage_stars[stage_num]
            if stars >= 0 and stars < target_stars:
                logger.info(f'Starting stage: {stage_num} ({stars} stars, target: {target_stars})')
                return (stage_num, stage_stars)

        # 所有可见关卡已完成，往右滑动找更高关卡
        if highest_unlocked < max_stage:
            logger.info(f'All visible stages completed, scrolling right to find higher stages...')
            next_stage = highest_unlocked + 1
            if next_stage <= max_stage:
                next_stage_keyword = getattr(KEYWORDS_FORGOTTEN_HALL_STAGE, f'Stage_{next_stage}')
                STAGE_LIST.insight_row(next_stage_keyword, main=self)
                # 递归检测
                return self.detect_current_highest_stage(max_stage, target_stars, dungeon_type=dungeon_type)

        return (-1, stage_stars)

    def find_starting_stage(self, stage_stars: dict, target_stars: int = 3, max_stage: int = 12) -> int:
        """
        根据星数扫描结果确定起始挑战关卡

        逻辑：
        1. 如果最高关卡已达目标星数，返回 -1 (任务完成)
        2. 否则找到最高的未达目标星数的解锁关卡

        Args:
            stage_stars: scan_all_stages() 返回的星数映射
            target_stars: 目标星数（默认3）
            max_stage: 最大关卡数

        Returns:
            int: 起始关卡编号，-1 表示全部完成
        """
        # 检查最高关卡是否已完成
        if stage_stars.get(max_stage, 0) >= target_stars:
            logger.info(f'Stage {max_stage} already has {target_stars}+ stars, task complete')
            return -1

        # 从最高关卡向下找第一个可挑战的关卡
        # 关卡解锁条件：前一关已通关（星数>0）或是第1关
        for stage in range(max_stage, 0, -1):
            stars = stage_stars.get(stage, 0)

            # 跳过未解锁关卡（星数为-1）
            if stars == -1:
                logger.debug(f'Stage {stage} is locked, skipping')
                continue

            if stars < target_stars:
                # 检查是否解锁（前一关有星数>=0 或是第1关）
                prev_stars = stage_stars.get(stage - 1, 0)
                if stage == 1 or (prev_stars >= 0 and prev_stars > 0):
                    logger.info(f'Starting stage: {stage} (current: {stars} stars, target: {target_stars})')
                    return stage

        # 理论上不会到达这里
        logger.warning('No starting stage found, starting from stage 1')
        return 1

    def get_stage_star_count(self, stage_num: int) -> int:
        """
        获取指定关卡的当前星数

        在战斗结束返回关卡选择界面后调用，
        用于判断是否达成目标星数

        Args:
            stage_num: 关卡编号

        Returns:
            int: 星数 (0-3)，未找到返回 -1
        """
        # 确保关卡在视野内
        stage_keyword = getattr(KEYWORDS_FORGOTTEN_HALL_STAGE, f'Stage_{stage_num}')
        STAGE_LIST.insight_row(stage_keyword, main=self)

        self.device.screenshot()
        STAGE_LIST.load_rows(main=self)

        for button in STAGE_LIST.cur_buttons:
            if button.matched_keyword and button.matched_keyword.id == stage_num:
                star_count = button.star_count if button.star_count is not None else 0
                logger.info(f'Stage {stage_num} current stars: {star_count}')
                return star_count

        logger.warning(f'Stage {stage_num} not found in current view')
        return -1
