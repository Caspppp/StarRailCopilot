"""
Currency War UI按钮资源定义
This file was manually created for currency war navigation
"""
from module.base.button import Button, ButtonWrapper

# 货币战争传送按钮（导航页面的"前往"按钮）
CURRENCY_WAR_TELEPORT = ButtonWrapper(
    name='CURRENCY_WAR_TELEPORT',
    share=Button(
        file='./assets/share/currency_war/ui/TELEPORT.png',
        area=(1011, 609, 1081, 627),
        search=(991, 589, 1101, 647),
        color=(153, 154, 157),
        button=(1011, 609, 1081, 627),
    ),
)

# 货币战争主界面检查按钮（"开始"按钮，用于验证是否在主界面）
CURRENCY_WAR_MAIN_CHECK = ButtonWrapper(
    name='CURRENCY_WAR_MAIN_CHECK',
    share=Button(
        file='./assets/share/currency_war/ui/MAIN_CHECK.png',
        area=(900, 634, 1101, 662),
        search=(880, 614, 1121, 682),
        color=(167, 169, 184),
        button=(900, 634, 1101, 662),
    ),
)

# 开始货币战争按钮（点击后进入博弈模式选择）
# 与 CURRENCY_WAR_MAIN_CHECK 相同，复用定义
CURRENCY_WAR_START = CURRENCY_WAR_MAIN_CHECK

# 奖励指示器（红点）- 出现时表示有奖励可领取
REWARD_INDICATOR = ButtonWrapper(
    name='REWARD_INDICATOR',
    share=Button(
        file='./assets/share/currency_war/ui/REWARD_INDICATOR.png',
        area=(343, 612, 354, 628),
        search=(323, 592, 374, 648),
        color=(216, 83, 82),  # Red indicator
        button=(343, 612, 354, 628),
    ),
)

# 积分显示区域（用于OCR识别和点击进入奖励界面）
OCR_CURRENCY_WAR_POINTS = ButtonWrapper(
    name='OCR_CURRENCY_WAR_POINTS',
    share=Button(
        file='./assets/share/currency_war/ui/REWARD_INDICATOR.png',  # Reuse existing asset
        area=(181, 656, 264, 682),
        search=(161, 636, 284, 702),
        color=(255, 255, 255),  # White text color
        button=(181, 656, 264, 682),  # Click to open reward screen
    ),
)

# 领取全部奖励按钮
CLAIM_ALL_BUTTON = ButtonWrapper(
    name='CLAIM_ALL_BUTTON',
    share=Button(
        file='./assets/share/currency_war/ui/CLAIM_ALL_BUTTON.png',
        area=(969, 490, 1079, 513),
        search=(949, 470, 1099, 533),
        color=(182, 144, 69),  # Golden color
        button=(969, 490, 1079, 513),
    ),
)

# 奖励界面关闭按钮（返回主界面）
CURRENCY_WAR_REWARD_CLOSE = ButtonWrapper(
    name='CURRENCY_WAR_REWARD_CLOSE',
    share=Button(
        file='./assets/share/currency_war/ui/REWARD_CLOSE.png',
        area=(1141, 179, 1171, 209),
        search=(1121, 159, 1191, 229),
        color=(72, 73, 77),
        button=(1141, 179, 1171, 209),
    ),
)

# 超频博弈模式按钮
CURRENCY_WAR_OVERCLOCK_MODE = ButtonWrapper(
    name='CURRENCY_WAR_OVERCLOCK_MODE',
    share=Button(
        file='./assets/share/currency_war/ui/OVERCLOCK_MODE.png',
        area=(75, 318, 179, 343),
        search=(55, 298, 199, 363),
        color=(119, 124, 131),
        button=(75, 318, 179, 343),
    ),
)

# 进入超频博弈按钮
CURRENCY_WAR_OVERCLOCK_ENTER = ButtonWrapper(
    name='CURRENCY_WAR_OVERCLOCK_ENTER',
    share=Button(
        file='./assets/share/currency_war/ui/OVERCLOCK_ENTER.png',
        area=(983, 629, 1107, 649),
        search=(963, 609, 1127, 669),
        color=(169, 169, 169),
        button=(983, 629, 1107, 649),
    ),
)

# 超频博弈开始对局按钮
CURRENCY_WAR_OVERCLOCK_START_BATTLE = ButtonWrapper(
    name='CURRENCY_WAR_OVERCLOCK_START_BATTLE',
    share=Button(
        file='./assets/share/currency_war/ui/OVERCLOCK_START_BATTLE.png',
        area=(1050, 633, 1130, 654),
        search=(1030, 613, 1150, 674),
        color=(157, 156, 156),
        button=(1050, 633, 1130, 654),
    ),
)

# 超频博弈下一步按钮（BOSS信息/位面信息等）
CURRENCY_WAR_OVERCLOCK_NEXT = ButtonWrapper(
    name='CURRENCY_WAR_OVERCLOCK_NEXT',
    share=Button(
        file='./assets/share/currency_war/ui/OVERCLOCK_NEXT.png',
        area=(975, 648, 1036, 669),
        search=(955, 628, 1056, 689),
        color=(203, 203, 203),
        button=(975, 648, 1036, 669),
    ),
)

# 投资环境确认按钮（首次进入时）
CURRENCY_WAR_INVEST_CONFIRM = ButtonWrapper(
    name='CURRENCY_WAR_INVEST_CONFIRM',
    share=Button(
        file='./assets/share/currency_war/ui/INVEST_CONFIRM.png',
        area=(716, 647, 768, 671),
        search=(696, 627, 788, 691),
        color=(196, 196, 196),
        button=(716, 647, 768, 671),
    ),
)

# 投资环境确认按钮（战斗后）
CURRENCY_WAR_INVEST_CONFIRM_BATTLE = ButtonWrapper(
    name='CURRENCY_WAR_INVEST_CONFIRM_BATTLE',
    share=Button(
        file='./assets/share/currency_war/ui/INVEST_CONFIRM_BATTLE.png',
        area=(635, 648, 676, 668),
        search=(615, 628, 696, 688),
        color=(171, 171, 171),
        button=(635, 648, 676, 668),
    ),
)

# 投资环境"未解锁/未收录"标识（用于优先选择开图鉴）
CURRENCY_WAR_INVEST_UNDISCOVERED_OPTION_1 = ButtonWrapper(
    name='CURRENCY_WAR_INVEST_UNDISCOVERED_OPTION_1',
    share=Button(
        file='./assets/share/currency_war/ui/INVEST_UNDISCOVERED.png',
        area=(0, 0, 19, 17),
        # 标记实际出现在三个标签右上角
        search=(355, 98, 438, 183),
        color=(255, 255, 255),
        button=(177, 242, 333, 265),
    ),
)
CURRENCY_WAR_INVEST_UNDISCOVERED_OPTION_2 = ButtonWrapper(
    name='CURRENCY_WAR_INVEST_UNDISCOVERED_OPTION_2',
    share=Button(
        file='./assets/share/currency_war/ui/INVEST_UNDISCOVERED.png',
        area=(0, 0, 19, 17),
        search=(740, 97, 823, 182),
        color=(255, 255, 255),
        button=(573, 242, 707, 267),
    ),
)
CURRENCY_WAR_INVEST_UNDISCOVERED_OPTION_3 = ButtonWrapper(
    name='CURRENCY_WAR_INVEST_UNDISCOVERED_OPTION_3',
    share=Button(
        file='./assets/share/currency_war/ui/INVEST_UNDISCOVERED.png',
        area=(0, 0, 19, 17),
        search=(1123, 97, 1206, 182),
        color=(255, 255, 255),
        button=(958, 241, 1092, 266),
    ),
)

# 出战 / 点击空白加速按钮（战斗开始后也可能用于加速）
CURRENCY_WAR_BATTLE_FIGHT = ButtonWrapper(
    name='CURRENCY_WAR_BATTLE_FIGHT',
    share=Button(
        file='./assets/share/currency_war/ui/BATTLE_FIGHT.png',
        area=(1171, 467, 1221, 495),
        search=(1151, 447, 1241, 515),
        color=(87, 106, 132),
        button=(1171, 467, 1221, 495),
    ),
)

# 继续挑战按钮（战斗结束后）
CURRENCY_WAR_CONTINUE_CHALLENGE = ButtonWrapper(
    name='CURRENCY_WAR_CONTINUE_CHALLENGE',
    share=Button(
        file='./assets/share/currency_war/ui/CONTINUE_CHALLENGE.png',
        area=(598, 644, 681, 667),
        search=(578, 624, 701, 687),
        color=(183, 179, 169),
        button=(598, 644, 681, 667),
    ),
)

# 投资环境选择弹窗标题（用于等待弹窗出现）
CURRENCY_WAR_INVEST_POPUP_TITLE = ButtonWrapper(
    name='CURRENCY_WAR_INVEST_POPUP_TITLE',
    share=Button(
        file='./assets/share/currency_war/ui/INVEST_POPUP_TITLE.png',
        area=(555, 50, 725, 79),
        search=(535, 30, 745, 99),
        color=(137, 134, 227),
        button=(555, 50, 725, 79),
    ),
)

# 商店收起按钮（收起商店界面，露出退出按钮）
CURRENCY_WAR_SHOP_COLLAPSE = ButtonWrapper(
    name='CURRENCY_WAR_SHOP_COLLAPSE',
    share=Button(
        file='./assets/share/currency_war/ui/SHOP_COLLAPSE.png',
        area=(1171, 645, 1213, 666),
        search=(1151, 625, 1233, 686),
        color=(70, 70, 70),
        button=(1171, 645, 1213, 666),
    ),
)

# 退出按钮
CURRENCY_WAR_EXIT = ButtonWrapper(
    name='CURRENCY_WAR_EXIT',
    share=Button(
        file='./assets/share/currency_war/ui/SHOP_EXIT.png',
        area=(32, 23, 61, 51),
        search=(12, 3, 81, 71),
        color=(100, 100, 114),
        button=(32, 23, 61, 51),
    ),
)

# 放弃并结算按钮
CURRENCY_WAR_GIVE_UP_AND_SETTLE = ButtonWrapper(
    name='CURRENCY_WAR_GIVE_UP_AND_SETTLE',
    share=Button(
        file='./assets/share/currency_war/ui/GIVE_UP_AND_SETTLE.png',
        area=(431, 518, 532, 540),
        search=(411, 498, 552, 560),
        color=(160, 160, 160),
        button=(431, 518, 532, 540),
    ),
)

# 结算页下一步按钮
CURRENCY_WAR_SETTLE_NEXT = ButtonWrapper(
    name='CURRENCY_WAR_SETTLE_NEXT',
    share=Button(
        file='./assets/share/currency_war/ui/SETTLE_NEXT.png',
        area=(610, 648, 670, 668),
        search=(590, 628, 690, 688),
        color=(185, 183, 183),
        button=(610, 648, 670, 668),
    ),
)

# 结算页下一页按钮
CURRENCY_WAR_SETTLE_NEXT_PAGE = ButtonWrapper(
    name='CURRENCY_WAR_SETTLE_NEXT_PAGE',
    share=Button(
        file='./assets/share/currency_war/ui/SETTLE_NEXT_PAGE.png',
        area=(609, 650, 670, 671),
        search=(589, 630, 690, 691),
        color=(186, 184, 184),
        button=(609, 650, 670, 671),
    ),
)

# 返回货币战争按钮（回到货币战争主页面）
CURRENCY_WAR_RETURN_TO_CURRENCY_WAR = ButtonWrapper(
    name='CURRENCY_WAR_RETURN_TO_CURRENCY_WAR',
    share=Button(
        file='./assets/share/currency_war/ui/RETURN_TO_CURRENCY_WAR.png',
        area=(579, 649, 700, 671),
        search=(559, 629, 720, 691),
        color=(160, 159, 159),
        button=(579, 649, 700, 671),
    ),
)

# 前台区域空格子模板（4个）
CURRENCY_WAR_FRONT_EMPTY_1 = ButtonWrapper(
    name='CURRENCY_WAR_FRONT_EMPTY_1',
    share=Button(
        file='./assets/share/currency_war/ui/FRONT_EMPTY_1.png',
        area=(454, 214, 524, 306),
        search=(434, 194, 544, 326),
        color=(56, 64, 131),
        button=(454, 214, 524, 306),
    ),
)
CURRENCY_WAR_FRONT_EMPTY_2 = ButtonWrapper(
    name='CURRENCY_WAR_FRONT_EMPTY_2',
    share=Button(
        file='./assets/share/currency_war/ui/FRONT_EMPTY_2.png',
        area=(556, 214, 626, 306),
        search=(536, 194, 646, 326),
        color=(57, 66, 134),
        button=(556, 214, 626, 306),
    ),
)
CURRENCY_WAR_FRONT_EMPTY_3 = ButtonWrapper(
    name='CURRENCY_WAR_FRONT_EMPTY_3',
    share=Button(
        file='./assets/share/currency_war/ui/FRONT_EMPTY_3.png',
        area=(656, 214, 726, 306),
        search=(636, 194, 746, 326),
        color=(56, 64, 129),
        button=(656, 214, 726, 306),
    ),
)
CURRENCY_WAR_FRONT_EMPTY_4 = ButtonWrapper(
    name='CURRENCY_WAR_FRONT_EMPTY_4',
    share=Button(
        file='./assets/share/currency_war/ui/FRONT_EMPTY_4.png',
        area=(757, 214, 827, 306),
        search=(737, 194, 847, 326),
        color=(55, 63, 128),
        button=(757, 214, 827, 306),
    ),
)

# 备战席位“角色棋子”标记（格子右上角的白色像素）
CURRENCY_WAR_BENCH_PIECE_MARKER = ButtonWrapper(
    name='CURRENCY_WAR_BENCH_PIECE_MARKER',
    share=Button(
        file='./assets/share/currency_war/ui/BENCH_PIECE_MARKER.png',
        area=(0, 0, 9, 9),
        search=(0, 0, 9, 9),
        color=(255, 255, 255),
        button=(0, 0, 9, 9),
    ),
)

# 备战席位空格子模板（共9个，模板内容一致）
_CURRENCY_WAR_BENCH_EMPTY_AREA = (0, 0, 96, 111)

CURRENCY_WAR_BENCH_EMPTY_1 = ButtonWrapper(
    name='CURRENCY_WAR_BENCH_EMPTY_1',
    share=Button(
        file='./assets/share/currency_war/ui/BENCH_EMPTY_PATCH.png',
        area=_CURRENCY_WAR_BENCH_EMPTY_AREA,
        search=(138, 522, 274, 673),
        color=(31, 31, 44),
        button=_CURRENCY_WAR_BENCH_EMPTY_AREA,
    ),
)
CURRENCY_WAR_BENCH_EMPTY_2 = ButtonWrapper(
    name='CURRENCY_WAR_BENCH_EMPTY_2',
    share=Button(
        file='./assets/share/currency_war/ui/BENCH_EMPTY_PATCH.png',
        area=_CURRENCY_WAR_BENCH_EMPTY_AREA,
        search=(242, 522, 378, 673),
        color=(31, 32, 44),
        button=_CURRENCY_WAR_BENCH_EMPTY_AREA,
    ),
)
CURRENCY_WAR_BENCH_EMPTY_3 = ButtonWrapper(
    name='CURRENCY_WAR_BENCH_EMPTY_3',
    share=Button(
        file='./assets/share/currency_war/ui/BENCH_EMPTY_PATCH.png',
        area=_CURRENCY_WAR_BENCH_EMPTY_AREA,
        search=(346, 522, 482, 673),
        color=(31, 32, 44),
        button=_CURRENCY_WAR_BENCH_EMPTY_AREA,
    ),
)
CURRENCY_WAR_BENCH_EMPTY_4 = ButtonWrapper(
    name='CURRENCY_WAR_BENCH_EMPTY_4',
    share=Button(
        file='./assets/share/currency_war/ui/BENCH_EMPTY_PATCH.png',
        area=_CURRENCY_WAR_BENCH_EMPTY_AREA,
        search=(450, 522, 586, 673),
        color=(31, 32, 44),
        button=_CURRENCY_WAR_BENCH_EMPTY_AREA,
    ),
)
CURRENCY_WAR_BENCH_EMPTY_5 = ButtonWrapper(
    name='CURRENCY_WAR_BENCH_EMPTY_5',
    share=Button(
        file='./assets/share/currency_war/ui/BENCH_EMPTY_PATCH.png',
        area=_CURRENCY_WAR_BENCH_EMPTY_AREA,
        search=(554, 522, 690, 673),
        color=(31, 32, 44),
        button=_CURRENCY_WAR_BENCH_EMPTY_AREA,
    ),
)
CURRENCY_WAR_BENCH_EMPTY_6 = ButtonWrapper(
    name='CURRENCY_WAR_BENCH_EMPTY_6',
    share=Button(
        file='./assets/share/currency_war/ui/BENCH_EMPTY_PATCH.png',
        area=_CURRENCY_WAR_BENCH_EMPTY_AREA,
        search=(658, 522, 794, 673),
        color=(31, 32, 44),
        button=_CURRENCY_WAR_BENCH_EMPTY_AREA,
    ),
)
CURRENCY_WAR_BENCH_EMPTY_7 = ButtonWrapper(
    name='CURRENCY_WAR_BENCH_EMPTY_7',
    share=Button(
        file='./assets/share/currency_war/ui/BENCH_EMPTY_PATCH.png',
        area=_CURRENCY_WAR_BENCH_EMPTY_AREA,
        search=(762, 522, 898, 673),
        color=(31, 32, 44),
        button=_CURRENCY_WAR_BENCH_EMPTY_AREA,
    ),
)
CURRENCY_WAR_BENCH_EMPTY_8 = ButtonWrapper(
    name='CURRENCY_WAR_BENCH_EMPTY_8',
    share=Button(
        file='./assets/share/currency_war/ui/BENCH_EMPTY_PATCH.png',
        area=_CURRENCY_WAR_BENCH_EMPTY_AREA,
        search=(866, 522, 1002, 673),
        color=(31, 32, 44),
        button=_CURRENCY_WAR_BENCH_EMPTY_AREA,
    ),
)
CURRENCY_WAR_BENCH_EMPTY_9 = ButtonWrapper(
    name='CURRENCY_WAR_BENCH_EMPTY_9',
    share=Button(
        file='./assets/share/currency_war/ui/BENCH_EMPTY_PATCH.png',
        area=_CURRENCY_WAR_BENCH_EMPTY_AREA,
        search=(970, 522, 1106, 673),
        color=(31, 32, 44),
        button=_CURRENCY_WAR_BENCH_EMPTY_AREA,
    ),
)
