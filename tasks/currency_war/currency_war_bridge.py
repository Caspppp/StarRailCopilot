"""
货币战争桥接层
负责连接 tools/currency_war/ 与主系统

参考 tasks/rogue/rogue.py 的调度逻辑
"""
from module.logger import logger
from tasks.base.ui import UI

from tools.currency_war.currency_war import CurrencyWar
from tools.currency_war.exception import CurrencyWarReachedWeeklyPointLimit


class CurrencyWarBridge(UI):
    """
    货币战争桥接类

    最小化桥接类，继承 UI 以获得界面导航能力
    负责：
    1. 更新任务状态
    2. 创建并调用核心执行器
    3. 处理调度逻辑
    """

    def run(self):
        """
        任务主入口

        遵循标准任务模式：
        1. 更新任务状态
        2. 执行核心逻辑
        3. 处理调度
        """
        # 更新任务状态
        self.config.update_battle_pass_quests()
        self.config.update_daily_quests()

        # 创建核心执行器（传递 config, device）
        executor = CurrencyWar(config=self.config, device=self.device)

        # 执行一次货币战争
        try:
            success = executor.run_once()
        except CurrencyWarReachedWeeklyPointLimit:
            logger.info('Reached weekly point limit, task completed')
            success = False

        # 调度逻辑（参考 Rogue）
        with self.config.multi_set():
            # 检查是否切换到其他任务
            if self.config.task_switched():
                self.config.task_stop()

            if success:
                logger.info('Currency War run success, scheduling next run')
                # 循环调用自己
                self.config.task_call('CurrencyWar')
            else:
                logger.info('Currency War completed or failed, delay until server update')
                # 延迟到服务器更新时间（周一4点）
                self.config.task_delay(server_update=True)
