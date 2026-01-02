"""
货币战争核心逻辑
参考 tasks/rogue/rogue.py 架构
"""
from module.exception import RequestHumanTakeover
from module.logger import logger

from tools.currency_war.entry.entry import CurrencyWarEntry
from tools.currency_war.strategy.battle import CurrencyWarBattle
from tools.currency_war.exception import (
    CurrencyWarReachedWeeklyPointLimit,
    CurrencyWarTeamNotPrepared,
    CurrencyWarBattleTimeout,
    CurrencyWarNotImplemented
)


class CurrencyWar(CurrencyWarEntry, CurrencyWarBattle):
    """
    货币战争主执行类

    继承：
    - CurrencyWarEntry: 进入/退出界面、停止条件检查
    - CurrencyWarBattle: 战斗执行逻辑

    执行流程：
    1. 进入货币战争界面
    2. 选择难度
    3. 执行战斗（买棋子→凑羁绊→自动战斗）
    4. 领取奖励
    """

    def currency_war_once(self):
        """
        执行一次完整的货币战争

        Returns:
            bool: 是否成功完成

        Raises:
            CurrencyWarReachedWeeklyPointLimit: 达到周常点数上限
            RequestHumanTakeover: 需要人工介入
        """
        try:
            # 1. 进入货币战争界面
            self.currency_war_enter()
        except CurrencyWarTeamNotPrepared:
            logger.error('Team not prepared, please prepare your team first')
            raise RequestHumanTakeover
        except CurrencyWarReachedWeeklyPointLimit:
            logger.hr('Reached currency war weekly point limit')
            raise

        try:
            # 2. 执行战斗流程
            self.currency_war_battle()
        except CurrencyWarNotImplemented as e:
            logger.error(f'Currency war not fully implemented: {e}')
            logger.error('Please wait for feature completion or implement missing parts')
            return False
        except CurrencyWarBattleTimeout:
            logger.error('Battle timeout, leaving currency war')
            self.currency_war_leave()
            return False

        # 3. 领取奖励
        self.currency_war_reward_claim()

        return True

    def run_once(self):
        """
        外部调用接口
        供桥接层调用

        Returns:
            bool: 是否成功完成
        """
        return self.currency_war_once()
