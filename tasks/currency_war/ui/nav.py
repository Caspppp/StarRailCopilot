"""
货币战争导航UI
参考模拟宇宙的导航实现
"""
from module.logger import logger
from tasks.base.page import page_guide, page_currency_war
from tasks.dungeon.ui.ui_rogue import DungeonRogueUI
from tasks.dungeon.keywords import KEYWORDS_DUNGEON_TAB
from tasks.currency_war.assets.assets_currency_war_ui import *
from tasks.rogue.assets.assets_rogue_weekly import REWARD_CLOSE


class CurrencyWarNav(DungeonRogueUI):
    """货币战争导航UI"""

    def currency_war_goto(self):
        """
        导航到货币战争入口（不点击传送按钮）

        Pages:
            in: Any
            out: page_guide, Simulated_Universe tab

        流程:
            1. 切换到"旷宇纷争"标签页（与模拟宇宙相同）
            2. 等待列表加载
        """
        logger.hr('Currency War goto', level=1)

        # 切换到"旷宇纷争"标签页（与模拟宇宙相同）
        self.dungeon_tab_goto(KEYWORDS_DUNGEON_TAB.Simulated_Universe)

        # 等待列表加载
        self._dungeon_wait_until_dungeon_list_loaded()

    def _currency_war_teleport(self, skip_first_screenshot=True):
        """
        点击传送按钮进入货币战争主界面

        Pages:
            in: page_guide, Simulated_Universe tab
            out: page_currency_war

        流程:
            1. 循环直到进入货币战争主界面
            2. 处理弹窗（奖励领取提示、积分更新、确认对话框）
            3. 查找并点击传送按钮
        """
        logger.info('Currency War teleport')
        self.interval_clear(page_guide.check_button)

        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 结束条件：到达货币战争主界面
            if self.appear(CURRENCY_WAR_MAIN_CHECK):
                logger.info('Arrived at currency war main page')
                break

            # 弹窗处理
            if self.appear_then_click(REWARD_CLOSE, interval=2):
                continue
            if self.handle_popup_confirm():
                continue

            # 点击传送按钮
            if self.appear(page_guide.check_button, interval=2):
                buttons = CURRENCY_WAR_TELEPORT.match_multi_template(self.device.image)
                if len(buttons):
                    logger.info(f'Found {len(buttons)} currency war teleport button(s)')
                    self.device.click(buttons[0])
                    continue

        self.interval_clear(page_guide.check_button)
