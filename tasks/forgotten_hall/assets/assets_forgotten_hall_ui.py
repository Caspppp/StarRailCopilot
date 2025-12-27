from module.base.button import Button, ButtonWrapper

# This file was auto-generated, do not modify it manually. To generate:
# ``` python -m dev_tools.button_extract ```

DUNGEON_ENTER_CHECKED = ButtonWrapper(
    name='DUNGEON_ENTER_CHECKED',
    share=Button(
        file='./assets/share/forgotten_hall/ui/DUNGEON_ENTER_CHECKED.png',
        area=(29, 242, 43, 251),
        search=(9, 222, 63, 271),
        color=(173, 173, 173),
        button=(29, 242, 43, 251),
    ),
)
ENTER_FORGOTTEN_HALL_DUNGEON = ButtonWrapper(
    name='ENTER_FORGOTTEN_HALL_DUNGEON',
    share=Button(
        file='./assets/share/forgotten_hall/ui/ENTER_FORGOTTEN_HALL_DUNGEON.png',
        area=(953, 640, 1225, 676),
        search=(933, 620, 1245, 696),
        color=(217, 217, 219),
        button=(953, 640, 1225, 676),
    ),
)
ENTRANCE_CHECKED = ButtonWrapper(
    name='ENTRANCE_CHECKED',
    share=Button(
        file='./assets/share/forgotten_hall/ui/ENTRANCE_CHECKED.png',
        area=(44, 655, 60, 673),
        search=(24, 635, 80, 693),
        color=(156, 156, 158),
        button=(44, 655, 60, 673),
    ),
)
OCR_STAGE = ButtonWrapper(
    name='OCR_STAGE',
    share=Button(
        file='./assets/share/forgotten_hall/ui/OCR_STAGE.png',
        area=(0, 281, 1280, 581),
        search=(0, 261, 1280, 601),
        color=(29, 48, 92),
        button=(0, 0, 1000, 100),
    ),
)
SEAT_1 = ButtonWrapper(
    name='SEAT_1',
    share=Button(
        file='./assets/share/forgotten_hall/ui/SEAT_1.png',
        area=(957, 549, 966, 574),
        search=(937, 529, 986, 594),
        color=(77, 78, 87),
        button=(957, 549, 966, 574),
    ),
)
SEAT_2 = ButtonWrapper(
    name='SEAT_2',
    share=Button(
        file='./assets/share/forgotten_hall/ui/SEAT_2.png',
        area=(1034, 549, 1043, 574),
        search=(1014, 529, 1063, 594),
        color=(77, 77, 86),
        button=(1034, 549, 1043, 574),
    ),
)
SEAT_3 = ButtonWrapper(
    name='SEAT_3',
    share=Button(
        file='./assets/share/forgotten_hall/ui/SEAT_3.png',
        area=(1111, 549, 1120, 574),
        search=(1091, 529, 1140, 594),
        color=(76, 77, 85),
        button=(1111, 549, 1120, 574),
    ),
)
SEAT_4 = ButtonWrapper(
    name='SEAT_4',
    share=Button(
        file='./assets/share/forgotten_hall/ui/SEAT_4.png',
        area=(1188, 549, 1197, 574),
        search=(1168, 529, 1217, 594),
        color=(76, 77, 85),
        button=(1188, 549, 1197, 574),
    ),
)
TELEPORT = ButtonWrapper(
    name='TELEPORT',
    share=Button(
        file='./assets/share/forgotten_hall/ui/TELEPORT.png',
        area=(1018, 355, 1038, 375),
        search=(993, 176, 1088, 658),
        color=(80, 83, 85),
        button=(1018, 355, 1038, 375),
    ),
)
PRESET_TEAM = ButtonWrapper(
    name='PRESET_TEAM',
    share=Button(
        file='./assets/share/forgotten_hall/ui/PRESET_TEAM.png',
        area=(318, 83, 394, 108),
        search=(298, 63, 414, 128),
        color=(199, 195, 182),
        button=(318, 83, 394, 108),
    ),
)
# 预设编队面板已打开检测（新版本，更可靠的黑色背景区域检测）
PRESET_TEAM_PANEL_OPENED = ButtonWrapper(
    name='PRESET_TEAM_PANEL_OPENED',
    share=Button(
        file='./tools/forgotten_hall_navigator/assets/PRESET_TEAM_PANEL_OPENED.png',
        area=(263, 85, 450, 106),
        search=(243, 65, 470, 126),
        color=(0, 0, 0),
        button=(263, 85, 450, 106),
    ),
)
# 预设编队面板已打开检测（旧版本，保留作为备用）
PRESET_TEAM_OPENED = ButtonWrapper(
    name='PRESET_TEAM_OPENED',
    share=Button(
        file='./tools/forgotten_hall_navigator/assets/PRESET_TEAM_OPENED.png',
        area=(317, 85, 394, 105),
        search=(297, 65, 414, 125),
        color=(0, 0, 0),
        button=(317, 85, 394, 105),
    ),
)
# 第二关切换按钮 - 直接坐标点击
BATTLE_2_SWITCH = ButtonWrapper(
    name='BATTLE_2_SWITCH',
    share=Button(
        file='',
        area=(895, 525, 925, 595),
        search=(895, 525, 925, 595),
        color=(0, 0, 0),
        button=(895, 525, 925, 595),
    ),
)
# 清除已选配队按钮
CLEAR_TEAM = ButtonWrapper(
    name='CLEAR_TEAM',
    share=Button(
        file='./assets/share/forgotten_hall/ui/CLEAR_TEAM.png',
        area=(1194, 391, 1218, 408),
        search=(1174, 371, 1238, 428),
        color=(0, 0, 0),
        button=(1194, 391, 1218, 408),
    ),
)
# 上半关卡队伍槽位（空白状态检测）
# 使用完整屏幕截图作为模板，area 为屏幕坐标用于裁剪
TEAM_SLOT_BATTLE1_EMPTY = ButtonWrapper(
    name='TEAM_SLOT_BATTLE1_EMPTY',
    share=Button(
        file='./tools/forgotten_hall_navigator/assets/TEAM_SLOT_BATTLE1_EMPTY.png',
        area=(935, 435, 1231, 499),  # 从完整屏幕截图中裁剪的区域
        search=(915, 415, 1251, 519),  # 屏幕搜索区域（扩大20px）
        color=(0, 0, 0),
        button=(935, 435, 1231, 499),
    ),
)
# 下半关卡队伍槽位（空白状态检测）
# 使用完整屏幕截图作为模板，area 为屏幕坐标用于裁剪
TEAM_SLOT_BATTLE2_EMPTY = ButtonWrapper(
    name='TEAM_SLOT_BATTLE2_EMPTY',
    share=Button(
        file='./tools/forgotten_hall_navigator/assets/TEAM_SLOT_BATTLE2_EMPTY.png',
        area=(935, 529, 1231, 593),  # 从完整屏幕截图中裁剪的区域
        search=(915, 509, 1251, 613),  # 屏幕搜索区域（扩大20px）
        color=(0, 0, 0),
        button=(935, 529, 1231, 593),
    ),
)
