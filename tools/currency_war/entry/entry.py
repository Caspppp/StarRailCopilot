"""
货币战争进入/退出逻辑
参考 tasks/rogue/entry/entry.py
"""
from module.logger import logger
from tasks.currency_war.ui.nav import CurrencyWarNav
from tasks.currency_war.assets.assets_currency_war_ui import CURRENCY_WAR_MAIN_CHECK
from tools.currency_war.ui.ui import CurrencyWarUI
from tools.currency_war.exception import CurrencyWarReachedWeeklyPointLimit


class CurrencyWarEntry(CurrencyWarNav, CurrencyWarUI):
    """
    处理货币战争界面的进入和退出
    继承CurrencyWarNav以获得导航能力
    """

    def check_stop_condition(self):
        """
        检查是否应该停止任务

        Raises:
            CurrencyWarReachedWeeklyPointLimit: 达到周常点数上限

        停止条件检查逻辑：
        1. DebugMode=True → 总是运行
        2. 周常点数过期 → 重置点数，继续运行
        3. 周常点数已满：
           a. WeeklyFarming=True → 继续刷材料
           b. 否则 → 抛出异常，停止任务
        """
        logger.info(f'CurrencyWarWorld_UseImmersifier={self.config.CurrencyWarWorld_UseImmersifier}')
        logger.info(f'CurrencyWarWorld_WeeklyFarming={self.config.CurrencyWarWorld_WeeklyFarming}')

        # 调试模式总是运行
        if self.config.CurrencyWarDebug_DebugMode:
            logger.info('Debug mode enabled, skip stop condition check')
            return

        # 检查周常点数是否过期（周一4点重置）
        stored = self.config.stored.CurrencyWarWeeklyPoints
        if stored.is_expired():
            logger.info('Weekly points expired, resetting to 0/18000')
            stored.set(0, total=18000)

        # 检查是否达到上限
        if stored.is_full():
            logger.info(f'Weekly points full: {stored.value}/{stored.total}')

            if self.config.CurrencyWarWorld_WeeklyFarming:
                logger.info('WeeklyFarming enabled, continue to farm materials')
                return

            raise CurrencyWarReachedWeeklyPointLimit

        logger.info(f'Weekly points: {stored.value}/{stored.total}')

    def currency_war_enter(self):
        """
        进入货币战争界面

        Pages:
            in: page_main
            out: page_currency_war (main interface, difficulty select)

        流程:
            1. 检查停止条件
            2. 导航到货币战争入口（进入标签页）
            3. 点击传送按钮进入主界面
            4. 等待主界面稳定
            5. TODO: 后续实现难度选择和开始对局
        """
        logger.hr('Currency War Enter', level=1)

        # 1. 检查停止条件
        self.check_stop_condition()

        self.device.screenshot()
        # 0. 容错：若上一次运行停留在奖励界面，先尝试关闭回到主界面
        from module.base.timer import Timer
        from tasks.currency_war.assets.assets_currency_war_ui import (
            CLAIM_ALL_BUTTON,
            CURRENCY_WAR_REWARD_CLOSE,
        )
        from tasks.base.assets.assets_base_page import CLOSE

        if self.appear(CLAIM_ALL_BUTTON) or self.appear(CURRENCY_WAR_REWARD_CLOSE):
            logger.info('Detected currency war reward page, trying to return to main interface')
            closed = False
            if self.appear(CURRENCY_WAR_REWARD_CLOSE):
                closed = self.click_until_appear(
                    CURRENCY_WAR_REWARD_CLOSE,
                    CURRENCY_WAR_MAIN_CHECK,
                    timeout=12,
                    interval=0.2,
                    click_interval=1.0,
                    skip_first_screenshot=True,
                )
            if not closed:
                self.click_until_appear(
                    CLOSE,
                    CURRENCY_WAR_MAIN_CHECK,
                    timeout=12,
                    interval=0.2,
                    click_interval=1.0,
                    skip_first_screenshot=False,
                )
            self.wait_until_stable(CURRENCY_WAR_MAIN_CHECK, timeout=Timer(3))
            self.device.screenshot()

        if self.is_page_currency_war_main():
            logger.info('Already on currency war main interface, skip navigation')
            self.wait_until_stable(CURRENCY_WAR_MAIN_CHECK)
        else:
            # 2. 导航到货币战争入口（进入标签页）
            self.currency_war_goto()

            # 3. 点击传送按钮进入主界面
            self._currency_war_teleport()

            # 4. 等待主界面稳定
            self.wait_until_stable(CURRENCY_WAR_MAIN_CHECK)
            logger.info('Entered currency war main interface')

        # 5. 主界面奖励领取 & 周常点数同步（可能触发停止条件）
        self.currency_war_reward_claim()

        # 6. 点击开始按钮进入货币战争
        if self.currency_war_start():
            # 7. 选择“超频博弈模式”并进入
            if self.currency_war_overclock_enter():
                # 8. 开始对局 → 过信息页 → 投资环境3选1 → 确认进入
                self.currency_war_overclock_prepare()

        # 8. TODO: 后续实现难度选择和开始对局
        # difficulty = self.config.CurrencyWarWorld_Difficulty
        # logger.info(f'Select difficulty: {difficulty}')
        # self._select_difficulty(difficulty)

    def currency_war_start(self, skip_first_screenshot=True) -> bool:
        """
        在货币战争主界面点击“开始”按钮

        Pages:
            in: page_currency_war (main interface)

        Returns:
            bool: 是否成功点击并离开主界面（若无法判断离开则返回 False）
        """
        from module.base.timer import Timer
        from tasks.currency_war.assets.assets_currency_war_ui import (
            CURRENCY_WAR_END_AND_SETTLE,
            CURRENCY_WAR_GIVE_UP_AND_SETTLE_CONFIRM,
            CURRENCY_WAR_RETURN_TO_CURRENCY_WAR,
            CURRENCY_WAR_START,
            CURRENCY_WAR_MAIN_CHECK,
            CURRENCY_WAR_OVERCLOCK_MODE,
            CURRENCY_WAR_OVERCLOCK_ENTER,
            CURRENCY_WAR_SETTLE_NEXT,
            CURRENCY_WAR_SETTLE_NEXT_PAGE,
        )

        logger.hr('Currency War Start', level=2)
        self.interval_clear(CURRENCY_WAR_START)

        timeout = Timer(8).start()
        clicked = False

        while not timeout.reached():
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 已进入模式选择界面
            if self.appear(CURRENCY_WAR_OVERCLOCK_MODE) or self.appear(CURRENCY_WAR_OVERCLOCK_ENTER):
                logger.info('Arrived at currency war mode selection')
                return True

            # 存在未完成对局：结束并结算 → 放弃并结算 → 回到主界面再重新开始
            unfinished_match_ui = (
                self.appear(CURRENCY_WAR_END_AND_SETTLE)
                or self.appear(CURRENCY_WAR_GIVE_UP_AND_SETTLE_CONFIRM)
                or self.appear(CURRENCY_WAR_SETTLE_NEXT)
                or self.appear(CURRENCY_WAR_SETTLE_NEXT_PAGE)
                or self.appear(CURRENCY_WAR_RETURN_TO_CURRENCY_WAR)
            )
            if unfinished_match_ui:
                logger.info('Detected unfinished currency war match, settling first')
                if self.currency_war_abandon_and_settle_unfinished_match(skip_first_screenshot=True):
                    timeout.reset()
                    clicked = False
                    self.interval_clear(CURRENCY_WAR_START)
                    skip_first_screenshot = True
                    continue
                logger.warning('Unfinished match detected but failed to settle')
                continue

            # 已离开主界面
            if not self.appear(CURRENCY_WAR_MAIN_CHECK):
                logger.info('Left currency war main page')
                return True

            # 弹窗处理
            if self.handle_popup_confirm():
                continue
            if self.handle_popup_single():
                continue

            # 点击开始按钮
            if self.appear_then_click(CURRENCY_WAR_START, interval=1):
                clicked = True
                self.wait_until(
                    appear=[CURRENCY_WAR_OVERCLOCK_MODE, CURRENCY_WAR_OVERCLOCK_ENTER],
                    disappear=CURRENCY_WAR_MAIN_CHECK,
                    timeout=1.2,
                    interval=0.2,
                    skip_first_screenshot=False,
                )
                continue

        if clicked:
            logger.warning('Clicked start but still on currency war main page')
        else:
            logger.warning('Start button not found on currency war main page')

        return False

    def currency_war_abandon_and_settle_unfinished_match(self, skip_first_screenshot: bool = True) -> bool:
        """
        处理未完成对局：
            1) 点击“结束并结算”
            2) 点击“放弃并结算”
            3) 挑战失败结算页：下一步 → 下一页 → 返回货币战争 → 回到主界面

        Returns:
            bool: 是否成功回到货币战争主界面
        """
        from module.base.timer import Timer
        from tasks.currency_war.assets.assets_currency_war_ui import (
            CURRENCY_WAR_END_AND_SETTLE,
            CURRENCY_WAR_GIVE_UP_AND_SETTLE_CONFIRM,
            CURRENCY_WAR_MAIN_CHECK,
            CURRENCY_WAR_RETURN_TO_CURRENCY_WAR,
            CURRENCY_WAR_SETTLE_NEXT,
            CURRENCY_WAR_SETTLE_NEXT_PAGE,
        )

        logger.hr('Currency War Unfinished Match', level=2)

        if not skip_first_screenshot:
            self.device.screenshot()

        if self.appear(CURRENCY_WAR_END_AND_SETTLE):
            if not self.click_until_appear(
                CURRENCY_WAR_END_AND_SETTLE,
                [CURRENCY_WAR_GIVE_UP_AND_SETTLE_CONFIRM, CURRENCY_WAR_SETTLE_NEXT],
                timeout=25,
                interval=0.2,
                click_interval=1.0,
                skip_first_screenshot=True,
            ):
                logger.warning('End and settle button not responding')
                return False

        if self.appear(CURRENCY_WAR_GIVE_UP_AND_SETTLE_CONFIRM):
            if not self.click_until_appear(
                CURRENCY_WAR_GIVE_UP_AND_SETTLE_CONFIRM,
                CURRENCY_WAR_SETTLE_NEXT,
                timeout=35,
                interval=0.2,
                click_interval=1.0,
                skip_first_screenshot=True,
            ):
                logger.warning('Give up and settle button not responding')
                return False

        if not self.appear(CURRENCY_WAR_SETTLE_NEXT):
            if not self.wait_until_appear(
                CURRENCY_WAR_SETTLE_NEXT,
                timeout=35,
                interval=0.3,
                skip_first_screenshot=False,
            ):
                logger.warning('Settle next button not found')
                return False

        if not self.click_until_appear(
            CURRENCY_WAR_SETTLE_NEXT,
            CURRENCY_WAR_SETTLE_NEXT_PAGE,
            timeout=35,
            interval=0.3,
            click_interval=1.0,
            skip_first_screenshot=False,
        ):
            logger.warning('Settle next page button not found')
            return False

        if not self.click_until_appear(
            CURRENCY_WAR_SETTLE_NEXT_PAGE,
            CURRENCY_WAR_RETURN_TO_CURRENCY_WAR,
            timeout=35,
            interval=0.3,
            click_interval=1.0,
            skip_first_screenshot=False,
        ):
            logger.warning('Return to currency war button not found')
            return False

        if not self.click_until_appear(
            CURRENCY_WAR_RETURN_TO_CURRENCY_WAR,
            CURRENCY_WAR_MAIN_CHECK,
            timeout=35,
            interval=0.3,
            click_interval=1.0,
            skip_first_screenshot=False,
        ):
            logger.warning('Main page not found after settle')
            return False

        self.wait_until_stable(CURRENCY_WAR_MAIN_CHECK, timeout=Timer(10))
        logger.info('Returned to currency war main page (unfinished match settled)')
        return True

    def currency_war_overclock_enter(self, skip_first_screenshot=True) -> bool:
        """
        在博弈模式选择界面选择“超频博弈模式”并点击进入

        Returns:
            bool: 是否成功点击进入（若无法判断进入结果则返回 False）
        """
        from module.base.timer import Timer
        from tasks.currency_war.assets.assets_currency_war_ui import (
            CURRENCY_WAR_OVERCLOCK_MODE,
            CURRENCY_WAR_OVERCLOCK_ENTER,
            CURRENCY_WAR_OVERCLOCK_START_BATTLE,
            CURRENCY_WAR_OVERCLOCK_NEXT,
            CURRENCY_WAR_INVEST_CONFIRM,
        )

        logger.hr('Currency War Overclock', level=2)
        self.interval_clear(CURRENCY_WAR_OVERCLOCK_MODE)
        self.interval_clear(CURRENCY_WAR_OVERCLOCK_ENTER)

        timeout = Timer(10).start()
        clicked_mode = False

        while not timeout.reached():
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 弹窗处理
            if self.handle_popup_confirm():
                continue
            if self.handle_popup_single():
                continue

            # 先选模式，再点进入
            if self.appear_then_click(CURRENCY_WAR_OVERCLOCK_MODE, interval=1):
                clicked_mode = True
                continue

            if self.appear_then_click(CURRENCY_WAR_OVERCLOCK_ENTER, interval=1):
                if self.wait_until_appear(
                    [CURRENCY_WAR_OVERCLOCK_START_BATTLE, CURRENCY_WAR_OVERCLOCK_NEXT, CURRENCY_WAR_INVEST_CONFIRM],
                    timeout=6.0,
                    interval=0.2,
                    skip_first_screenshot=False,
                ):
                    return True
                continue

        if clicked_mode:
            logger.warning('Overclock mode selected but enter button not found')
        else:
            logger.warning('Overclock mode selection not found')

        return False

    def currency_war_overclock_prepare(self, skip_first_screenshot=True) -> bool:
        """
        超频博弈：开始对局并完成开局前置流程

        流程:
            1. 点击“开始对局”
            2. 等待BOSS信息加载，点击“下一步”
            3. 位面信息页点击“下一步”
            4. 点击空白处继续
            5. 投资环境3选1：优先选择带“未解锁/未收录”标识的选项
            6. 点击确认，进入游戏界面

        Returns:
            bool: 是否完成进入游戏前置流程（无法判断进入结果时返回 False）
        """
        from module.base.timer import Timer
        from module.base.button import ClickButton
        from tasks.currency_war.assets.assets_currency_war_ui import (
            CURRENCY_WAR_BATTLE_FIGHT,
            CURRENCY_WAR_OVERCLOCK_START_BATTLE,
            CURRENCY_WAR_OVERCLOCK_NEXT,
            CURRENCY_WAR_INVEST_POPUP_TITLE,
            CURRENCY_WAR_INVEST_TITLE_START,
            CURRENCY_WAR_INVEST_CONFIRM,
            CURRENCY_WAR_INVEST_CONFIRM_BATTLE,
            CURRENCY_WAR_INVEST_UNDISCOVERED_OPTION_1,
            CURRENCY_WAR_INVEST_UNDISCOVERED_OPTION_2,
            CURRENCY_WAR_INVEST_UNDISCOVERED_OPTION_3,
        )

        logger.hr('Currency War Overclock Prepare', level=2)
        self.interval_clear([
            CURRENCY_WAR_OVERCLOCK_START_BATTLE,
            CURRENCY_WAR_OVERCLOCK_NEXT,
            CURRENCY_WAR_INVEST_CONFIRM,
            CURRENCY_WAR_INVEST_CONFIRM_BATTLE,
        ])

        confirm_buttons = [CURRENCY_WAR_INVEST_CONFIRM, CURRENCY_WAR_INVEST_CONFIRM_BATTLE]

        def click_blank_to_continue():
            # 避免点击屏幕中间（可能误点投资选项）
            blank = ClickButton(area=(20, 340, 80, 400), name='CURRENCY_WAR_BLANK_CONTINUE')
            self.device.click(blank)
            self.wait_until_appear(
                [*confirm_buttons, CURRENCY_WAR_OVERCLOCK_NEXT],
                timeout=1.2,
                interval=0.2,
                skip_first_screenshot=False,
            )

        # 1. 点击开始对局（若已进入信息页则跳过）
        if not self.click_until_appear(
            CURRENCY_WAR_OVERCLOCK_START_BATTLE,
            [CURRENCY_WAR_OVERCLOCK_NEXT, CURRENCY_WAR_INVEST_CONFIRM],
            timeout=20,
            interval=0.2,
            click_interval=1.2,
            skip_first_screenshot=skip_first_screenshot,
        ):
            logger.warning('Overclock start battle button no response')

        # 2) 通过信息页/点击空白页，直到进入投资环境选择页
        timeout = Timer(45).start()
        while not timeout.reached():
            self.device.screenshot()

            if self.handle_popup_confirm():
                continue
            if self.handle_popup_single():
                continue

            # 已进入投资环境选择页：无需再点"空白继续"
            # 检测开局标题（投资环境）或战斗后标题（请选择投资策略）或确认按钮
            if (self.appear(CURRENCY_WAR_INVEST_TITLE_START, similarity=0.8) or
                self.appear(CURRENCY_WAR_INVEST_POPUP_TITLE, similarity=0.8) or
                self.appear(CURRENCY_WAR_INVEST_CONFIRM) or
                self.appear(CURRENCY_WAR_INVEST_CONFIRM_BATTLE)):
                logger.info('Investment selection page detected')
                break

            # 优先点“下一步”，否则点空白处继续
            if self.appear(CURRENCY_WAR_OVERCLOCK_NEXT):
                if self.appear_then_click(CURRENCY_WAR_OVERCLOCK_NEXT, interval=1):
                    self.wait_until_appear(
                        [CURRENCY_WAR_OVERCLOCK_NEXT, CURRENCY_WAR_INVEST_CONFIRM],
                        timeout=1.2,
                        interval=0.2,
                        skip_first_screenshot=False,
                    )
                continue

            click_blank_to_continue()
        else:
            logger.warning('Investment confirm page not found after starting battle')

        options = [
            (ClickButton(area=(177, 242, 333, 265), name='CURRENCY_WAR_INVEST_OPTION_1'),
             CURRENCY_WAR_INVEST_UNDISCOVERED_OPTION_1),
            (ClickButton(area=(573, 242, 707, 267), name='CURRENCY_WAR_INVEST_OPTION_2'),
             CURRENCY_WAR_INVEST_UNDISCOVERED_OPTION_2),
            (ClickButton(area=(958, 241, 1092, 266), name='CURRENCY_WAR_INVEST_OPTION_3'),
             CURRENCY_WAR_INVEST_UNDISCOVERED_OPTION_3),
        ]

        def choose_investment_option():
            chosen = False
            scan = Timer(2).start()
            while not scan.reached() and not chosen:
                self.device.screenshot()
                for click_btn, undiscovered_btn in options:
                    if self.match_template_luma(undiscovered_btn, similarity=0.75):
                        logger.info(f'Choosing undiscovered investment option: {click_btn}')
                        self.device.click(click_btn)
                        chosen = True
                        break

            if not chosen:
                logger.info('No undiscovered investment option found, choosing option 2 (middle)')
                self.device.click(options[1][0])

        # 6. 投资环境选择可能会连续出现多次（部分关卡会额外多出一次选择）
        max_investment_selections = 3
        for idx in range(max_investment_selections):
            # 确保弹窗按钮已出现（避免误判在过渡动画中）
            # 检测三种可能的界面标识：开局标题、战斗后标题、确认按钮
            if not self.wait_until_appear(
                [CURRENCY_WAR_INVEST_TITLE_START, CURRENCY_WAR_INVEST_POPUP_TITLE, *confirm_buttons],
                timeout=8.0,
                interval=0.2,
                skip_first_screenshot=False,
            ):
                logger.warning('Investment selection popup not found')
                return False

            choose_investment_option()

            # 部分投资选择无“确认”按钮，会直接跳到下一页；因此只在确认按钮出现时才点击
            if self.wait_until_appear(
                confirm_buttons,
                timeout=4.0,
                interval=0.2,
                skip_first_screenshot=False,
            ):
                self.device.screenshot()
                confirm_btn = (
                    CURRENCY_WAR_INVEST_CONFIRM_BATTLE
                    if self.appear(CURRENCY_WAR_INVEST_CONFIRM_BATTLE)
                    else CURRENCY_WAR_INVEST_CONFIRM
                )
                if not self.click_until(
                    confirm_btn,
                    appear=CURRENCY_WAR_BATTLE_FIGHT,
                    disappear=confirm_btn,
                    timeout=15,
                    interval=0.2,
                    click_interval=1.0,
                    skip_first_screenshot=False,
                ):
                    logger.warning('Investment confirm button not found')
                    return False
            else:
                logger.info('Investment confirm button not found, maybe auto-advance')

            # 等待进入战斗界面，或出现下一次投资选择（第二次弹窗可能延迟出现）
            if self.wait_until_appear(
                [CURRENCY_WAR_BATTLE_FIGHT, *confirm_buttons],
                timeout=20.0,
                interval=0.2,
                skip_first_screenshot=False,
            ):
                self.device.screenshot()
                if self.appear(CURRENCY_WAR_BATTLE_FIGHT):
                    return True
                logger.info(f'Another investment selection detected ({idx + 2}/{max_investment_selections}), selecting again')
                continue

            # 无法判断进入结果，默认认为已通过投资选择
            self.device.screenshot()
            if (self.appear(CURRENCY_WAR_INVEST_TITLE_START, similarity=0.8) or
                self.appear(CURRENCY_WAR_INVEST_POPUP_TITLE, similarity=0.8)):
                logger.info('Investment selection still present after waiting, retrying')
                continue

            logger.info('Investment selection result unclear, assuming entered game')
            return True

        logger.warning('Too many consecutive investment selections')
        return False

    def currency_war_leave(self):
        """
        退出货币战争界面

        Pages:
            in: Any currency war page
            out: page_main
        """
        logger.hr('Currency War Leave', level=1)
        # TODO: 实现退出逻辑
        # self.ui_goto(page_main)
        logger.info('TODO: Leave currency war and return to main')

    def currency_war_reward_claim(self):
        """
        领取货币战争奖励并更新周常点数

        流程:
            1. OCR当前点数
            2. 检测奖励指示器（红点）
            3. 点击进入奖励界面
            4. 循环领取所有奖励（15秒超时）
            5. 处理弹窗
            6. OCR更新后的点数
            7. 更新存储的周常点数
            8. 检查18000上限

        Pages:
            in: CURRENCY_WAR_MAIN_CHECK
            out: CURRENCY_WAR_MAIN_CHECK

        Returns:
            bool: 是否成功领取奖励

        Raises:
            CurrencyWarReachedWeeklyPointLimit: 达到18000点上限且WeeklyFarming=False
        """
        from module.base.timer import Timer
        from tasks.currency_war.assets.assets_currency_war_ui import (
            OCR_CURRENCY_WAR_POINTS,
            CLAIM_ALL_BUTTON,
            CURRENCY_WAR_MAIN_CHECK,
            CURRENCY_WAR_REWARD_CLOSE,
        )
        from tasks.base.assets.assets_base_page import CLOSE

        logger.hr('Currency War Reward', level=2)

        # 1. OCR当前点数（奖励前）
        self.device.screenshot()
        points_before = self.ocr_currency_war_points()
        logger.info(f'Points before claiming: {points_before}/18000')
        self._update_weekly_points_with_ocr(points_before)

        # 2. 检测奖励指示器
        if not self.has_reward_indicator():
            logger.info('No reward indicator found, skip reward claiming')
            self.check_stop_condition()
            return False

        logger.info('Reward indicator detected, claiming rewards...')

        # 3. 点击奖励区域进入奖励界面
        self.device.click(OCR_CURRENCY_WAR_POINTS)
        self.wait_until_appear(
            [CLAIM_ALL_BUTTON, CURRENCY_WAR_REWARD_CLOSE, CLOSE],
            timeout=3.0,
            interval=0.2,
            skip_first_screenshot=False,
        )

        # 4. 循环领取奖励（带超时保护）
        timeout = Timer(15).start()
        claimed = False

        while not timeout.reached():
            self.device.screenshot()

            # 点击领取按钮
            if self.appear(CLAIM_ALL_BUTTON, interval=1):
                logger.info('Claiming rewards...')
                self.device.click(CLAIM_ALL_BUTTON)
                claimed = True
                self.wait_until_disappear(
                    CLAIM_ALL_BUTTON,
                    timeout=1.5,
                    interval=0.2,
                    skip_first_screenshot=False,
                )
                continue

            # 处理领取后的弹窗
            if self.handle_reward(interval=2):
                continue

            if self.handle_popup_confirm():
                continue

            if self.handle_popup_single():
                continue

            # 检查是否回到主界面（奖励领取完成）
            if self.appear(CURRENCY_WAR_MAIN_CHECK):
                if claimed:
                    logger.info('Rewards claimed successfully')
                break

            # 货币战争奖励界面关闭按钮（返回主界面）
            if self.appear_then_click(CURRENCY_WAR_REWARD_CLOSE, interval=2):
                logger.info('Clicking currency war reward close button to return')
                self.wait_until_appear(
                    CURRENCY_WAR_MAIN_CHECK,
                    timeout=2.0,
                    interval=0.2,
                    skip_first_screenshot=False,
                )
                continue

            # 点击关闭按钮
            if self.appear(CLOSE, interval=2):
                logger.info('Clicking close button to return')
                self.device.click(CLOSE)
                self.wait_until_appear(
                    CURRENCY_WAR_MAIN_CHECK,
                    timeout=2.0,
                    interval=0.2,
                    skip_first_screenshot=False,
                )
                continue

        # 5. 超时检查
        if timeout.reached() and not claimed:
            logger.warning('Reward claiming timeout')
            self.check_stop_condition()
            return False

        # 6. 等待回到主界面
        self.wait_until_stable(CURRENCY_WAR_MAIN_CHECK, timeout=Timer(3))
        self.device.screenshot()
        if not self.appear(CURRENCY_WAR_MAIN_CHECK):
            logger.warning('Still not on currency war main page after reward claiming, trying to close reward page')
            closed = False
            if self.appear(CURRENCY_WAR_REWARD_CLOSE):
                closed = self.click_until_appear(
                    CURRENCY_WAR_REWARD_CLOSE,
                    CURRENCY_WAR_MAIN_CHECK,
                    timeout=12,
                    interval=0.2,
                    click_interval=1.0,
                    skip_first_screenshot=True,
                )
            if not closed:
                self.click_until_appear(
                    CLOSE,
                    CURRENCY_WAR_MAIN_CHECK,
                    timeout=12,
                    interval=0.2,
                    click_interval=1.0,
                    skip_first_screenshot=False,
                )
            self.wait_until_stable(CURRENCY_WAR_MAIN_CHECK, timeout=Timer(3))

        # 7. OCR更新后的点数
        self.device.screenshot()
        points_after = self.ocr_currency_war_points()
        earned_points = points_after - points_before

        logger.info(f'Points after claiming: {points_after}/18000 (+{earned_points})')

        # 8. 更新周常点数（使用OCR直接值，避免累积误差）
        self._update_weekly_points_with_ocr(points_after)

        # 9. 重新检查停止条件（周常点数/沉浸器/周刷开关）
        self.check_stop_condition()

        return claimed

    def _update_weekly_points(self, earned_points):
        """
        更新周常点数（增量方式，保留备用）

        Args:
            earned_points: 本次获得的点数
        """
        stored = self.config.stored.CurrencyWarWeeklyPoints
        current = stored.value
        total = stored.total

        new_value = min(current + earned_points, total)
        stored.value = new_value

        logger.info(f'Weekly points: {new_value}/{total} (+{earned_points})')

    def _update_weekly_points_with_ocr(self, ocr_points):
        """
        使用OCR识别的点数直接更新周常点数

        Args:
            ocr_points: OCR识别到的当前点数

        Notes:
            相比增量更新（current + earned），直接使用OCR结果更准确
            因为OCR是从游戏界面读取的真实数据
        """
        stored = self.config.stored.CurrencyWarWeeklyPoints
        old_value = stored.value

        stored.value = min(ocr_points, 18000)  # 上限18000
        stored.total = 18000

        diff = stored.value - old_value
        logger.info(f'Weekly points updated: {stored.value}/18000 (+{diff})')
