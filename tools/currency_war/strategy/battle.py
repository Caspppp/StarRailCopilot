"""
货币战争战斗执行逻辑
包括：买棋子、凑羁绊、升级、战斗
"""
from module.logger import logger
from module.base.timer import Timer
from module.base.button import ClickButton
from tools.currency_war.ui.ui import CurrencyWarUI
from tools.currency_war.exception import CurrencyWarBattleTimeout


class CurrencyWarBattle(CurrencyWarUI):
    """
    战斗执行逻辑

    核心流程：
    1. 准备阶段（多回合）：买棋子 → 升级 → 调整阵容
    2. 战斗阶段：自动战斗
    3. 结算
    """

    def currency_war_battle(self):
        """
        执行完整战斗流程
        """
        logger.hr('Currency War Battle', level=1)

        # 检查是否还在主界面（说明没有进入战斗准备状态）
        if self.is_page_currency_war_main():
            logger.error('Still on main page, difficulty selection not implemented')
            logger.error('Currency war battle logic is not fully implemented yet')
            from tools.currency_war.exception import CurrencyWarNotImplemented
            raise CurrencyWarNotImplemented('Difficulty selection and battle entry not implemented')

        from tasks.currency_war.assets.assets_currency_war_ui import (
            CURRENCY_WAR_BATTLE_FIGHT,
            CURRENCY_WAR_CONTINUE_CHALLENGE,
            CURRENCY_WAR_INVEST_POPUP_TITLE,
            CURRENCY_WAR_INVEST_CONFIRM,
            CURRENCY_WAR_INVEST_CONFIRM_BATTLE,
            CURRENCY_WAR_INVEST_UNDISCOVERED_OPTION_1,
            CURRENCY_WAR_INVEST_UNDISCOVERED_OPTION_2,
            CURRENCY_WAR_INVEST_UNDISCOVERED_OPTION_3,
            CURRENCY_WAR_SHOP_COLLAPSE,
            CURRENCY_WAR_EXIT,
            CURRENCY_WAR_GIVE_UP_AND_SETTLE,
            CURRENCY_WAR_SETTLE_NEXT,
            CURRENCY_WAR_SETTLE_NEXT_PAGE,
            CURRENCY_WAR_RETURN_TO_CURRENCY_WAR,
            CURRENCY_WAR_MAIN_CHECK,
        )

        def choose_investment_option():
            options = [
                (ClickButton(area=(177, 242, 333, 265), name='CURRENCY_WAR_INVEST_OPTION_1'),
                 CURRENCY_WAR_INVEST_UNDISCOVERED_OPTION_1),
                (ClickButton(area=(573, 242, 707, 267), name='CURRENCY_WAR_INVEST_OPTION_2'),
                 CURRENCY_WAR_INVEST_UNDISCOVERED_OPTION_2),
                (ClickButton(area=(958, 241, 1092, 266), name='CURRENCY_WAR_INVEST_OPTION_3'),
                 CURRENCY_WAR_INVEST_UNDISCOVERED_OPTION_3),
            ]

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

        # 1) 将备战席位棋子拖到前台区域（并确保上阵完成）
        deploy_timeout = Timer(25).start()
        first_try = True
        while not deploy_timeout.reached():
            if self.currency_war_deploy_bench_pieces_to_front(
                deploy_count=3,
                wait_timeout=10.0 if first_try else 3.0,
                wait_interval=0.4,
            ):
                break
            first_try = False
        else:
            logger.error('Deploy did not reach required count')
            raise CurrencyWarBattleTimeout

        # 2) 点击出战按钮并等待战斗结束：期间可点击“空白加速”（可消失，点不到也继续等）
        if not self.wait_until_appear(
            CURRENCY_WAR_BATTLE_FIGHT,
            timeout=15,
            interval=0.3,
            skip_first_screenshot=False,
        ):
            logger.error('Battle fight button not found')
            raise CurrencyWarBattleTimeout

        if not self.click_until_appear(
            CURRENCY_WAR_BATTLE_FIGHT,
            CURRENCY_WAR_CONTINUE_CHALLENGE,
            timeout=180,
            interval=0.5,
            click_interval=3.0,
            skip_first_screenshot=False,
        ):
            logger.error('Battle did not finish in time')
            raise CurrencyWarBattleTimeout

        # 3) 继续挑战 → 等待投资环境弹窗出现
        if not self.click_until_appear(
            CURRENCY_WAR_CONTINUE_CHALLENGE,
            [CURRENCY_WAR_INVEST_POPUP_TITLE, CURRENCY_WAR_INVEST_CONFIRM_BATTLE, CURRENCY_WAR_INVEST_CONFIRM],
            timeout=30,
            interval=0.3,
            click_interval=1.0,
            skip_first_screenshot=False,
        ):
            logger.error('Investment popup not found')
            raise CurrencyWarBattleTimeout

        # 部分关卡投资环境弹窗可能连续出现多次
        confirm_buttons = [CURRENCY_WAR_INVEST_CONFIRM_BATTLE, CURRENCY_WAR_INVEST_CONFIRM]
        max_investment_selections = 3
        for idx in range(max_investment_selections):
            if not self.wait_until_appear(
                [CURRENCY_WAR_INVEST_POPUP_TITLE, *confirm_buttons],
                timeout=8.0,
                interval=0.2,
                skip_first_screenshot=False,
            ):
                logger.error('Investment popup not found')
                raise CurrencyWarBattleTimeout

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
                    appear=[CURRENCY_WAR_SHOP_COLLAPSE, CURRENCY_WAR_EXIT],
                    disappear=confirm_btn,
                    timeout=20,
                    interval=0.2,
                    click_interval=1.0,
                    skip_first_screenshot=False,
                ):
                    logger.error('Investment confirm button not found')
                    raise CurrencyWarBattleTimeout
            else:
                logger.info('Investment confirm button not found, maybe auto-advance')

            # 等待进入商店/退出按钮出现，或出现下一次投资选择（弹窗可能延迟出现）
            if self.wait_until_appear(
                [CURRENCY_WAR_SHOP_COLLAPSE, CURRENCY_WAR_EXIT, *confirm_buttons],
                timeout=20.0,
                interval=0.2,
                skip_first_screenshot=False,
            ):
                self.device.screenshot()
                if self.appear(CURRENCY_WAR_SHOP_COLLAPSE) or self.appear(CURRENCY_WAR_EXIT):
                    break
                logger.info(f'Another investment selection detected ({idx + 2}/{max_investment_selections}), selecting again')
                continue

            self.device.screenshot()
            if self.appear(CURRENCY_WAR_INVEST_POPUP_TITLE, similarity=0.8):
                logger.info('Investment selection still present after waiting, retrying')
                continue

            break
        else:
            logger.error('Too many consecutive investment selections')
            raise CurrencyWarBattleTimeout

        # 5) 收起商店界面（让退出按钮出现）
        if not self.click_until_appear(
            CURRENCY_WAR_SHOP_COLLAPSE,
            CURRENCY_WAR_EXIT,
            timeout=20,
            interval=0.2,
            click_interval=1.0,
            skip_first_screenshot=False,
        ):
            logger.error('Exit button not found (shop collapse may have failed)')
            raise CurrencyWarBattleTimeout

        # 6) 退出 → 放弃并结算 → 结算页按钮链路
        # 退出菜单里的“暂时离开”容易被 POPUP_CONFIRM 误识别，所以这里在菜单阶段禁用通用弹窗处理。
        if not self.click_until_appear(
            CURRENCY_WAR_EXIT,
            lambda: self.appear(CURRENCY_WAR_GIVE_UP_AND_SETTLE, similarity=0.9),
            timeout=15,
            interval=0.2,
            click_interval=1.0,
            skip_first_screenshot=False,
            handle_popups=False,
        ):
            logger.error('Give up and settle button not found')
            raise CurrencyWarBattleTimeout

        from tasks.base.assets.assets_base_popup import POPUP_CONFIRM, POPUP_CANCEL, POPUP_SINGLE

        def is_confirm_dialog() -> bool:
            # 同时出现取消+确认，才视为真正的确认弹窗
            return self.appear(POPUP_CONFIRM) and self.appear(POPUP_CANCEL)

        give_up_click = ClickButton(area=(431, 518, 532, 540), name='CURRENCY_WAR_GIVE_UP_AND_SETTLE_CLICK')

        # Phase 1: 点击“放弃并结算”→ 等确认弹窗（或直接进入结算页）
        for _ in range(6):
            self.device.screenshot()

            if self.appear(CURRENCY_WAR_SETTLE_NEXT):
                break
            if is_confirm_dialog():
                break

            if not self.appear(CURRENCY_WAR_GIVE_UP_AND_SETTLE, similarity=0.9):
                # 菜单意外关闭：重新打开退出菜单
                self.click_until_appear(
                    CURRENCY_WAR_EXIT,
                    lambda: self.appear(CURRENCY_WAR_GIVE_UP_AND_SETTLE, similarity=0.9),
                    timeout=6,
                    interval=0.2,
                    click_interval=1.0,
                    skip_first_screenshot=False,
                    handle_popups=False,
                )
                continue

            self.device.click(give_up_click)

            # 等待弹窗/结算页出现；期间不自动点 POPUP_CONFIRM，避免误点“暂时离开”
            self.wait_until(
                appear=lambda: is_confirm_dialog() or self.appear(CURRENCY_WAR_SETTLE_NEXT),
                disappear=lambda: not self.appear(CURRENCY_WAR_GIVE_UP_AND_SETTLE, similarity=0.9),
                timeout=2.0,
                interval=0.15,
                skip_first_screenshot=False,
                handle_popups=False,
            )

        # Phase 2: 确认弹窗 → 点击确认 → 等结算页
        if not self.appear(CURRENCY_WAR_SETTLE_NEXT):
            self.device.screenshot()

        if is_confirm_dialog():
            if not self.click_until_appear(
                POPUP_CANCEL,
                CURRENCY_WAR_SETTLE_NEXT,
                timeout=30,
                interval=0.2,
                click_interval=1.0,
                skip_first_screenshot=False,
                handle_popups=False,
            ):
                logger.error('Settle next button not found after confirming give up')
                raise CurrencyWarBattleTimeout
        elif not self.appear(CURRENCY_WAR_SETTLE_NEXT):
            # 兜底：可能出现单按钮弹窗
            if self.appear_then_click(POPUP_SINGLE, interval=0.8):
                if not self.wait_until_appear(
                    CURRENCY_WAR_SETTLE_NEXT,
                    timeout=30,
                    interval=0.3,
                    skip_first_screenshot=False,
                    handle_popups=False,
                ):
                    logger.error('Settle next button not found')
                    raise CurrencyWarBattleTimeout
            else:
                logger.error('Give up flow did not reach confirm dialog or settle page')
                raise CurrencyWarBattleTimeout

        # 7) 结算页：下一步 → 下一页 → 返回货币战争
        if not self.click_until_appear(
            CURRENCY_WAR_SETTLE_NEXT,
            CURRENCY_WAR_SETTLE_NEXT_PAGE,
            timeout=30,
            interval=0.3,
            click_interval=1.0,
            skip_first_screenshot=False,
        ):
            logger.error('Settle next page button not found')
            raise CurrencyWarBattleTimeout

        if not self.click_until_appear(
            CURRENCY_WAR_SETTLE_NEXT_PAGE,
            CURRENCY_WAR_RETURN_TO_CURRENCY_WAR,
            timeout=30,
            interval=0.3,
            click_interval=1.0,
            skip_first_screenshot=False,
        ):
            logger.error('Return to currency war button not found')
            raise CurrencyWarBattleTimeout

        if not self.click_until_appear(
            CURRENCY_WAR_RETURN_TO_CURRENCY_WAR,
            CURRENCY_WAR_MAIN_CHECK,
            timeout=30,
            interval=0.3,
            click_interval=1.0,
            skip_first_screenshot=False,
        ):
            logger.error('Currency war main page not found after settle')
            raise CurrencyWarBattleTimeout

        # 8) 等待回到货币战争主界面
        self.wait_until_stable(CURRENCY_WAR_MAIN_CHECK, timeout=Timer(10))
        logger.info('Returned to currency war main page')
        return

    def _buy_pieces(self):
        """
        购买棋子策略
        """
        strategy = self.config.CurrencyWarStrategy_PieceStrategy
        logger.info(f'Using piece strategy: {strategy}')

        if strategy == 'auto_synergy':
            self._buy_auto_synergy()
        elif strategy == 'random':
            self._buy_random_pieces()
        else:
            logger.warning(f'Unknown strategy: {strategy}, using random')
            self._buy_random_pieces()

    def _buy_auto_synergy(self):
        """
        自动羁绊策略：
        1. 识别当前已有棋子和羁绊
        2. 寻找能凑成更高羁绊的棋子
        3. 优先购买能升级的棋子
        """
        logger.info('Auto synergy strategy')
        # TODO: 实现自动羁绊策略
        # 1. OCR识别商店中的棋子
        # 2. 计算哪些棋子能增强羁绊
        # 3. 购买最优选择

    def _buy_random_pieces(self):
        """
        随机购买策略：
        随机购买能买得起的棋子
        """
        logger.info('Random buy strategy')
        # TODO: 实现随机购买
        # 1. 获取当前金币数
        # 2. 随机选择一个能买得起的棋子
        # 3. 点击购买

    def _execute_auto_battle(self):
        """
        执行自动战斗
        等待战斗完成
        """
        logger.info('Executing auto battle')
        # TODO: 实现战斗执行
        # 1. 点击开始战斗按钮
        # 2. 等待战斗动画完成
        # 3. 识别战斗结果

    def _is_battle_finished(self):
        """
        检查战斗是否结束

        Returns:
            bool: 是否结束（胜利或失败）
        """
        # TODO: 实现结束检测
        # return self.appear(CURRENCY_WAR_VICTORY) or self.appear(CURRENCY_WAR_DEFEAT)
        return False
