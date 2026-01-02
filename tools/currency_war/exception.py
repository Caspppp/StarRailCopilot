"""
货币战争自定义异常
"""


class CurrencyWarReachedWeeklyPointLimit(Exception):
    """达到周常点数上限"""
    pass


class CurrencyWarBattleTimeout(Exception):
    """战斗超时"""
    pass


class CurrencyWarTeamNotPrepared(Exception):
    """队伍未准备"""
    pass


class CurrencyWarNotImplemented(Exception):
    """货币战争功能未实现"""
    pass
