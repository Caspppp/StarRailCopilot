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

class ForgottenHallRewardMixin:
    def check_and_claim_rewards(self, skip_first_screenshot=True) -> bool:
        """
        检测并领取深渊奖励

        在关卡选择界面检测右下角的奖励提示，存在则点击进入并领取

        Returns:
            bool: 是否成功领取了奖励

        Pages:
            in: FORGOTTEN_HALL_CHECK (关卡选择界面)
            out: FORGOTTEN_HALL_CHECK (关卡选择界面)
        """
        from tasks.forgotten_hall.assets.assets_forgotten_hall_ui import (
            REWARD_INDICATOR, REWARD_CLAIM_BUTTON, REWARD_EXIT
        )

        logger.hr('Check rewards', level=2)

        if not skip_first_screenshot:
            self.device.screenshot()

        # 检测奖励提示按钮
        if not self.appear(REWARD_INDICATOR):
            logger.info('No reward indicator found')
            return False

        logger.info('Reward indicator detected, claiming rewards...')

        # 点击奖励提示进入奖励界面
        self.device.click(REWARD_INDICATOR)

        # 等待奖励界面加载并领取
        timeout = Timer(15).start()
        claimed = False
        reward_page_opened = False
        claim_interval = Timer(0.5)
        exit_interval = Timer(0.5)

        while not timeout.reached():
            self.device.screenshot()

            # 检测领取按钮
            if self.appear(REWARD_CLAIM_BUTTON, interval=1):
                reward_page_opened = True
                if claim_interval.reached():
                    logger.info('Claiming reward...')
                    self.device.click(REWARD_CLAIM_BUTTON)
                    claimed = True
                    claim_interval.reset()
                continue

            # 处理领取后的弹窗
            if self.handle_reward(interval=2):
                continue

            if self.handle_popup_confirm():
                continue

            if self.handle_popup_single():
                continue

            # 点击退出按钮返回深渊界面
            if self.appear(REWARD_EXIT, interval=2):
                reward_page_opened = True
                if exit_interval.reached():
                    logger.info('Clicking exit button to return to forgotten hall')
                    self.device.click(REWARD_EXIT)
                    exit_interval.reset()
                continue

            # 如果回到了关卡选择界面，说明领取完成。
            # 点击入口后的第一帧仍可能是关卡页，必须等到奖励页真正出现后再结束。
            if self.appear(FORGOTTEN_HALL_CHECK):
                if reward_page_opened or claimed:
                    if claimed:
                        logger.info('Rewards claimed successfully')
                    break

                logger.info('Waiting for reward page to open')
                continue

        return claimed
