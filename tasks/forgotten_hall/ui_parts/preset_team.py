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

class ForgottenHallPresetTeamMixin:
    def _configure_preset_teams_flow(
        self,
        team1_preset: int = None,
        team2_preset: int = None,
        *,
        mode_label: str = '',
        team_label: str = 'team',
        verify_method: str = 'slot',
        ensure_entry=None,
        focus_team=None,
        clear_all=None,
        clear_team=None,
        apply_team=None,
    ) -> None:
        """Shared preset team configuration flow for FH modes."""
        if not (team1_preset or team2_preset):
            return

        prefix = f'[{mode_label}] ' if mode_label else ''

        if ensure_entry and not ensure_entry():
            logger.warning(f'{prefix}Team selection entry may have failed, continuing...')

        if clear_all:
            logger.info(f'{prefix}Clearing existing team selections...')
            clear_all()
            if not self._verify_team_cleared(battle_num=1, timeout=5.0, method=verify_method):
                logger.warning(f'{prefix}Team slots clear verification timeout, but continuing...')
        elif clear_team:
            logger.info(f'{prefix}Clearing existing team selections...')
            for team_index in (1, 2):
                if focus_team and not focus_team(team_index):
                    logger.warning(f'{prefix}Failed to select {team_label} {team_index}, continuing...')
                if not clear_team(team_index):
                    logger.warning(
                        f'{prefix}{team_label.capitalize()} {team_index} may not be cleared, continuing...'
                    )

        def apply_one(team_index: int, preset_index: int) -> None:
            if not preset_index:
                return
            if focus_team and not focus_team(team_index):
                logger.warning(f'{prefix}Failed to select {team_label} {team_index}, continuing...')
            logger.info(f'{prefix}Configuring {team_label} {team_index} with preset team {preset_index}')

            if apply_team:
                if not apply_team(team_index, preset_index):
                    logger.warning(
                        f'{prefix}Failed to apply preset team for {team_label} {team_index}, continuing...'
                    )
                return

            self._click_preset_team(skip_first_screenshot=True, timeout=15)
            if not self.select_preset_team(preset_index):
                logger.warning(
                    f'{prefix}Failed to select preset team for {team_label} {team_index}, continuing...'
                )
            self._verify_team_selected_with_retry(
                battle_num=team_index,
                max_retry=3,
                method=verify_method,
            )

        apply_one(1, team1_preset)
        apply_one(2, team2_preset)
        logger.info(f'{prefix}Preset teams configuration process completed')

    def _click_preset_team(self, skip_first_screenshot=False, timeout=15):
        """点击预设编队按钮并等待面板打开

        Args:
            skip_first_screenshot: 是否跳过第一次截图
            timeout: 超时时间（秒），默认 15 秒

        Pages:
            in: 关卡选择完成后
            out: 预设编队面板
        """
        logger.info('Click preset team button')
        timeout_timer = Timer(timeout).start()
        interval = Timer(1.5)  # 点击间隔

        from module.base.button import ClickButton

        pf_preset_tab_click = ClickButton(
            area=PURE_FICTION_PRESET_TAB_UNSELECTED.buttons[0]._button,
            name='PURE_FICTION_PRESET_TAB',
        )

        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 超时检测 - 仅警告，不中断
            if timeout_timer.reached():
                logger.warning(f'Click preset team timeout after {timeout}s')
                logger.warning('Preset team panel may not have opened, but continuing...')
                break

            # 使用新的预设编队面板检测模板
            if (
                self.appear(PRESET_TEAM_PANEL_OPENED, similarity=0.8)
                or self.appear(PRESET_TEAM_OPENED, similarity=0.8)
            ):
                logger.info('Preset team panel opened successfully')
                break

            # Pure Fiction: click the "预设编队" tab on the left roster panel.
            if self.appear(PURE_FICTION_PRESET_TAB_SELECTED, interval=0):
                logger.info('Pure Fiction preset tab already selected')
                continue

            if (self.appear(PURE_FICTION_PRESET_ICON, interval=0) or self.appear(PURE_FICTION_CLEAR_ICON, interval=0)):
                # Only click when tab is currently unselected, to avoid toggling or redundant clicks.
                if self.appear(PURE_FICTION_PRESET_TAB_UNSELECTED, interval=0) and interval.reached():
                    logger.info('Clicking PURE_FICTION_PRESET_TAB...')
                    self.device.click(pf_preset_tab_click)
                    interval.reset()
                    continue

            # 点击预设编队按钮
            if interval.reached() and self.appear(PRESET_TEAM):
                logger.info('Clicking PRESET_TEAM button...')
                self.device.click(PRESET_TEAM)
                interval.reset()
                continue

    def _count_empty_seats(self) -> int:
        seats = (SEAT_1, SEAT_2, SEAT_3, SEAT_4)
        empty_count = 0
        for seat in seats:
            if self.appear(seat, interval=0):
                empty_count += 1
        return empty_count

    def _verify_team_cleared(self, battle_num: int, timeout: float = 2.0, method: str = 'slot') -> bool:
        """验证队伍已被清除

        Args:
            battle_num: 1=上半, 2=下半
            timeout: 超时时间（秒）
            method: slot=使用 TEAM_SLOT_BATTLE*_EMPTY 模板, seat=使用 SEAT_* 空位模板

        Returns:
            是否成功清除
        """
        if method == 'seat':
            timer = Timer(timeout).start()
            while not timer.reached():
                self.device.screenshot()
                empty_count = self._count_empty_seats()
                if empty_count >= 4:
                    logger.info(f'Battle {battle_num} team cleared successfully (empty_seats={empty_count})')
                    return True
            logger.warning(f'Battle {battle_num} team clear verification failed (seat)')
            return False

        button = TEAM_SLOT_BATTLE1_EMPTY if battle_num == 1 else TEAM_SLOT_BATTLE2_EMPTY

        timer = Timer(timeout).start()
        while not timer.reached():
            self.device.screenshot()
            if self.appear(button):
                logger.info(f'Battle {battle_num} team cleared successfully')
                return True

        logger.warning(f'Battle {battle_num} team clear verification failed')
        return False

    def _verify_team_selected(self, battle_num: int, timeout: float = 2.0, method: str = 'slot') -> bool:
        """验证队伍已被选择

        Args:
            battle_num: 1=上半, 2=下半
            timeout: 超时时间（秒）
            method: slot=使用 TEAM_SLOT_BATTLE*_EMPTY 模板, seat=使用 SEAT_* 空位模板

        Returns:
            是否成功选择
        """
        if method == 'seat':
            timer = Timer(timeout).start()
            while not timer.reached():
                self.device.screenshot()
                empty_count = self._count_empty_seats()
                if empty_count <= 3:
                    logger.info(f'Battle {battle_num} team selected successfully (empty_seats={empty_count})')
                    return True
            logger.warning(f'Battle {battle_num} team selection verification failed (seat)')
            return False

        button = TEAM_SLOT_BATTLE1_EMPTY if battle_num == 1 else TEAM_SLOT_BATTLE2_EMPTY
        # 获取实际的 Button 对象（ButtonWrapper 包含多个 Button）
        actual_button = button.buttons[0]

        logger.debug(f'Start verifying battle {battle_num} team selection')

        # 保存验证开始时的截图（仅调试模式）
        self.device.screenshot()
        if logger_debug:
            os.makedirs('./log/debug/team_verification', exist_ok=True)
            save_image(self.device.image,
                      f'./log/debug/team_verification/verify_start_battle{battle_num}_{int(time.time()*1000)}.png')

        timer = Timer(timeout).start()
        loop_count = 0
        last_similarity = 0.0

        while not timer.reached():
            loop_count += 1
            self.device.screenshot()

            # 获取匹配相似度
            image = crop(self.device.image, actual_button.search, copy=False)

            # Debug: 输出图像尺寸（仅调试模式）
            if loop_count == 1:
                logger.debug(f'Template shape: {actual_button.image.shape}, search shape: {image.shape}')
                logger.debug(f'Search area: {actual_button.search}, button area: {actual_button.area}')
                # 保存模板图像供检查（仅调试模式）
                if logger_debug:
                    save_image(actual_button.image,
                              f'./log/debug/team_verification/template_battle{battle_num}_{int(time.time()*1000)}.png')

            res = cv2.matchTemplate(actual_button.image, image, cv2.TM_CCOEFF_NORMED)
            _, similarity, _, point = cv2.minMaxLoc(res)
            last_similarity = similarity

            # Debug: 输出匹配结果（仅调试模式）
            if loop_count == 1:
                logger.debug(f'Match result shape: {res.shape}, match point: {point}')

            logger.debug(f'Verification loop {loop_count}: similarity={similarity:.4f}, '
                        f'threshold=0.85, elapsed={timer.current_time():.2f}s')

            # 判断是否匹配（使用默认阈值 0.85）
            if similarity <= 0.85:  # 不匹配空白模板，说明有队伍了
                logger.info(f'Battle {battle_num} team selected successfully '
                           f'(similarity={similarity:.4f} <= 0.85)')
                return True

        # 验证失败，保存详细信息
        logger.warning(f'Battle {battle_num} team selection verification failed')
        logger.debug(f'Final similarity: {last_similarity:.4f}, threshold: 0.85, '
                    f'loops: {loop_count}, timeout: {timeout}s')

        # 保存失败时的完整截图（仅调试模式）
        if logger_debug:
            save_image(self.device.image,
                      f'./log/debug/team_verification/verify_failed_battle{battle_num}_{int(time.time()*1000)}.png')

            # 保存裁剪区域
            crop_image = crop(self.device.image, actual_button.search)
            save_image(crop_image,
                      f'./log/debug/team_verification/crop_battle{battle_num}_{int(time.time()*1000)}.png')

        return False

    def _verify_team_selected_with_retry(
        self,
        battle_num: int,
        max_retry=3,
        retry_delay=2,
        method: str = 'slot',
    ):
        """验证队伍选择，失败后重试（最终失败仅警告）

        Args:
            battle_num: 关卡编号（1=上半，2=下半）
            max_retry: 最大重试次数，默认 3 次
            retry_delay: 重试间隔（秒，当前不做固定等待）
            method: slot=使用 TEAM_SLOT_BATTLE*_EMPTY 模板, seat=使用 SEAT_* 空位模板
        """
        _ = retry_delay
        for attempt in range(1, max_retry + 1):
            logger.info(f'Verifying battle {battle_num} team selection (attempt {attempt}/{max_retry})...')

            # 调用现有的 _verify_team_selected() 方法
            if self._verify_team_selected(battle_num=battle_num, method=method):
                logger.info(f'Battle {battle_num} team selection verified successfully')
                return  # 验证成功，返回

            # 验证失败，准备重试
            if attempt < max_retry:
                logger.warning(f'Battle {battle_num} team verification failed, retrying...')
            else:
                # 最终失败，仅警告不中断
                logger.warning(f'Battle {battle_num} team verification failed after {max_retry} attempts')
                logger.warning('Team may not be correctly selected, but continuing...')

    def _configure_preset_teams(
        self,
        team1_preset: int = None,
        team2_preset: int = None,
        verify_method: str = 'slot',
    ):
        """配置两关的预设编队（增加等待和验证，失败不中断）

        Args:
            team1_preset: 第一关使用的预设编队编号 (1-12, 1-based)
            team2_preset: 第二关使用的预设编队编号 (1-12, 1-based)
            verify_method: slot=使用 TEAM_SLOT_BATTLE*_EMPTY 模板, seat=使用 SEAT_* 空位模板
        """

        def focus_team(team_index: int) -> bool:
            if team_index == 2:
                logger.info('Switching to battle 2...')
                self._click_battle_switch_with_wait(2, timeout=5, verify_method=verify_method)
            return True

        self._configure_preset_teams_flow(
            team1_preset=team1_preset,
            team2_preset=team2_preset,
            team_label='battle',
            verify_method=verify_method,
            focus_team=focus_team,
            clear_all=lambda: self.device.click(CLEAR_TEAM),
        )

    # ========== 预设编队滚动条检测与选择 ==========
    # 几何常量
    PRESET_TEAM_SCROLLBAR_ROI = (477, 130, 483, 669)  # 滚动条区域
    PRESET_TEAM_HEIGHT = 160  # 单个队伍高度
    PRESET_TEAM_GAP = 12      # 队伍间距
    PRESET_TEAM_PITCH = 172   # height + gap
    PRESET_TEAM_VIEW_HEIGHT = 548  # 可见区域高度
    PRESET_TEAM_TOP_Y = 130   # 列表顶部Y坐标

    def _get_preset_team_scroll_thumb(self, image) -> tuple:
        """检测预设编队滚动条滑块

        通过亮度阈值检测滑块位置

        Args:
            image: 截图图像 (BGR格式)

        Returns:
            (valid, y_top, y_bottom, track_top, track_bottom)
            - valid: 是否检测到有效滑块
            - y_top, y_bottom: 滑块顶部和底部的绝对Y坐标
            - track_top, track_bottom: 轨道顶部和底部Y坐标
        """
        x1, y1, x2, y2 = self.PRESET_TEAM_SCROLLBAR_ROI
        crop_img = image[y1:y2, x1:x2]

        if crop_img.size == 0:
            return (False, 0, 0, y1, y2)

        # 灰度化
        gray = cv2.cvtColor(crop_img, cv2.COLOR_BGR2GRAY)

        # 二值化（亮度阈值150）
        _, bin_img = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)

        # 行求和
        row_sum = bin_img.sum(axis=1)
        h = row_sum.shape[0]

        # 找最长连续亮区
        max_len = 0
        best = (0, 0)
        run_len = 0
        run_start = 0

        for i in range(h):
            if row_sum[i] > 0:
                if run_len == 0:
                    run_start = i
                run_len += 1
            else:
                if run_len > max_len:
                    max_len = run_len
                    best = (run_start, i - 1)
                run_len = 0

        # 处理最后一个运行
        if run_len > max_len:
            max_len = run_len
            best = (run_start, h - 1)

        # 有效性检查：滑块最小高度6px
        if max_len < 6:
            return (False, 0, 0, y1, y2)

        # 返回绝对坐标
        y_top = y1 + best[0]
        y_bottom = y1 + best[1]
        return (True, y_top, y_bottom, y1, y2)

    def _get_preset_team_scroll_state(self) -> tuple:
        """获取预设编队滚动状态

        Returns:
            (valid, total_teams, top_team_index)
            - valid: 是否检测到有效滑块
            - total_teams: 总队伍数（从滑块大小反推）
            - top_team_index: 当前顶部队伍索引 (0-based)
        """
        valid, y_top, y_bot, t_top, t_bot = self._get_preset_team_scroll_thumb(
            self.device.image
        )

        if not valid:
            # 无滚动条 = 队伍数 <= 3，全部可见
            return (False, 3, 0)

        H_track = t_bot - t_top  # 轨道高度
        h = y_bot - y_top + 1    # 滑块高度

        # 滑块正规化
        y_norm = (y_top - t_top) / max(H_track - h, 1.0)  # 位置 0-1
        h_norm = h / max(H_track, 1.0)                     # 大小 0-1

        # 从滑块大小反推总队伍数
        # h_norm ≈ 可见队伍数 / 总队伍数
        visible_teams = 3.2
        N_total = int(round(visible_teams / max(h_norm, 0.1)))
        N_total = max(4, min(12, N_total))  # 限制在4-12范围

        # 计算当前顶部队伍索引
        max_scroll_teams = max(N_total - 3, 0)
        k_top = int(round(y_norm * max_scroll_teams))

        logger.info(f'Preset team scroll state: total={N_total}, top={k_top}, y_norm={y_norm:.2f}')
        return (True, N_total, k_top)

    def _drag_preset_team_slider(self, target_team: int) -> bool:
        """拖动滑块到目标队伍位置

        Args:
            target_team: 目标队伍索引 (0-based)

        Returns:
            是否成功拖动
        """
        # 获取当前滑块状态
        self.device.screenshot()
        valid, y_top, y_bot, t_top, t_bot = self._get_preset_team_scroll_thumb(
            self.device.image
        )
        if not valid:
            logger.warning('No scrollbar detected for preset team')
            return False

        # 计算几何参数
        H_track = float(t_bot - t_top)
        h = float(y_bot - y_top + 1)

        # 获取总队伍数
        _, N_total, _ = self._get_preset_team_scroll_state()

        # 计算目标滑块位置
        max_scroll_teams = max(N_total - 3, 0)
        target_top = max(0, min(max_scroll_teams, target_team))
        s_target = target_top / max(max_scroll_teams, 1.0)  # 目标位置 0-1

        # 计算目标Y坐标
        y_target_top = t_top + s_target * (H_track - h)

        # 获取滑块中心坐标
        x1, y1, x2, y2 = self.PRESET_TEAM_SCROLLBAR_ROI
        cx = (x1 + x2) // 2
        cy_now = int((y_top + y_bot) / 2)
        cy_target = int(y_target_top + h / 2.0)

        logger.info(f'Drag preset team slider: {cy_now} -> {cy_target}')

        # 执行拖动
        self.device.drag(
            (cx, cy_now), (cx, cy_target),
            name="PRESET_TEAM_SLIDER_DRAG"
        )

        stable_timer = Timer(1.0).start()
        last_pos = None
        stable_count = 0
        while not stable_timer.reached():
            self.device.screenshot()
            valid_now, y_top_now, y_bot_now, _, _ = self._get_preset_team_scroll_thumb(
                self.device.image
            )
            if not valid_now:
                continue
            pos = (y_top_now, y_bot_now)
            if pos == last_pos:
                stable_count += 1
                if stable_count >= 2:
                    break
            else:
                stable_count = 0
                last_pos = pos

        return True

    def _click_preset_team_slot(self, slot_index: int) -> bool:
        """点击当前可见的第N个队伍槽位

        Args:
            slot_index: 槽位索引 (0, 1, 2)
        """
        from module.base.button import Button

        if slot_index not in (0, 1, 2):
            logger.error(f'Invalid preset team slot index: {slot_index}')
            return False

        y_base = self.PRESET_TEAM_TOP_Y + slot_index * self.PRESET_TEAM_PITCH
        y_center = y_base + self.PRESET_TEAM_HEIGHT // 2
        x_center = (32 + 463) // 2  # 列表区域中心X

        # 创建临时按钮用于点击（device.click需要Button对象）
        click_area = (x_center - 20, y_center - 20, x_center + 20, y_center + 20)
        button = Button(
            file='',
            area=click_area,
            search=click_area,
            color=(0, 0, 0),
            button=click_area
        )

        logger.info(f'Click preset team slot {slot_index} at ({x_center}, {y_center})')
        self.device.click(button)
        return True

    def select_preset_team(self, team_index: int) -> bool:
        """选择指定编号的预设编队

        Args:
            team_index: 预设编队编号 (1-12, 1-based)

        Returns:
            是否成功选择
        """
        # 参数验证
        if team_index < 1 or team_index > 12:
            logger.error(f'Invalid preset team index: {team_index}, must be 1-12')
            return False

        target = team_index - 1  # 转为0-based
        logger.info(f'Select preset team {team_index}')

        # 获取当前滚动状态
        self.device.screenshot()
        valid, total, _ = self._get_preset_team_scroll_state()

        if not valid:
            # 无滚动条，队伍数 <= 3，直接点击
            if target < 3:
                return self._click_preset_team_slot(target)
            else:
                logger.error(f'Target team {team_index} not available (only {total} teams)')
                return False

        # 检查目标队伍是否存在
        if target >= total:
            logger.error(f'Target team {team_index} not available (only {total} teams)')
            return False

        # 预设编队列表每屏可见 3 个槽位。
        # 通过“目标队伍索引”推导目标滚动到的顶部索引与点击槽位，避免依赖 top 计算导致 -1/3 之类的越界点击。
        desired_top = max(0, min(target, total - 3))
        slot_index = target - desired_top

        logger.info(f'Preset team scroll target: top={desired_top}, slot={slot_index}')
        if not self._drag_preset_team_slider(desired_top):
            logger.warning('Preset team slider drag may have failed, continuing...')
        self.device.screenshot()

        if not self._click_preset_team_slot(slot_index):
            return False

        logger.info(f'Selected preset team {team_index}')
        return True

    def _click_battle_switch(self, battle_num: int):
        """点击切换到第N关

        Args:
            battle_num: 关卡编号 (1 或 2)
        """
        if battle_num == 2:
            logger.info('Switch to battle 2')
            self.device.click(BATTLE_2_SWITCH)

    def _click_battle_switch_with_wait(self, battle_num: int, timeout=5, verify_method: str = 'slot'):
        """切换到指定关卡并等待验证（失败不中断）

        Args:
            battle_num: 关卡编号（2=下半）
            timeout: 超时时间（秒），默认 5 秒
            verify_method: slot=使用 TEAM_SLOT_BATTLE2_EMPTY 模板, seat=仅等待画面刷新
        """
        if battle_num == 2:
            logger.info('Clicking battle 2 switch...')
            self.device.click(BATTLE_2_SWITCH)

            if verify_method == 'seat':
                # Pure Fiction team UI may not match TEAM_SLOT_BATTLE*_EMPTY templates reliably.
                settle = Timer(min(timeout, 1.0), count=3).start()
                while not settle.reached():
                    self.device.screenshot()
                return

            # 等待并验证切换成功
            timer = Timer(timeout).start()
            switched = False

            while not timer.reached():
                self.device.screenshot()
                # 检测下半空白槽位出现
                if self.appear(TEAM_SLOT_BATTLE2_EMPTY):
                    logger.info('Successfully switched to battle 2')
                    switched = True
                    break

            if not switched:
                logger.warning(f'Battle 2 switch verification timeout after {timeout}s')
                logger.warning('Switch may have failed, but continuing...')
        else:
            logger.warning(f'Unsupported battle number: {battle_num}')
