import cv2
import numpy as np
import os
import time
from pponnxcr.predict_system import BoxedResult

from module.base.base import ModuleBase
from module.base.timer import Timer
from module.base.utils import area_offset, color_similarity_2d, crop, save_image
from module.logger.logger import logger
from module.ocr.keyword import Keyword
from module.ocr.ocr import Ocr, OcrResultButton
from module.ui.draggable_list import DraggableList
from tasks.base.assets.assets_base_page import FORGOTTEN_HALL_CHECK, MAP_EXIT
from tasks.base.assets.assets_base_popup import BUFF_Forgotten_Hall
from tasks.base.page import page_guide
from tasks.dungeon.keywords import DungeonList, KEYWORDS_DUNGEON_LIST, KEYWORDS_DUNGEON_NAV, KEYWORDS_DUNGEON_TAB
from tasks.dungeon.ui.ui import DungeonUI
from tasks.forgotten_hall.assets.assets_forgotten_hall_nav import *
from tasks.forgotten_hall.assets.assets_forgotten_hall_ui import *
from tasks.forgotten_hall.keywords import ForgottenHallStage, KEYWORDS_FORGOTTEN_HALL_STAGE
from tasks.forgotten_hall.team import ForgottenHallTeam
from tasks.map.control.joystick import MapControlJoystick


def detect_unlocked_text(image, search_area):
    """
    检测指定区域是否有"未解锁"文字

    "未解锁"文字是较暗的蓝紫色 (BGR: B=100-130, G=35-65, R=55-85)
    与关卡图标的亮紫色 (B=146-171) 区分

    Args:
        image: 原始图像 (BGR格式)
        search_area: 搜索区域 (x1, y1, x2, y2)

    Returns:
        bool: 是否检测到"未解锁"文字
    """
    x1, y1, x2, y2 = search_area

    # 边界检查
    h, w = image.shape[:2]
    x1 = max(0, x1)
    y1 = max(0, y1)
    x2 = min(w, x2)
    y2 = min(h, y2)

    if x2 <= x1 or y2 <= y1:
        return False

    # 裁剪区域
    crop_img = image[y1:y2, x1:x2]

    # 精确的"未解锁"文字颜色范围（排除关卡图标亮紫色）
    # BGR: B=100-130, G=35-65, R=55-85
    lower_unlock = np.array([100, 35, 55], dtype=np.uint8)
    upper_unlock = np.array([130, 65, 85], dtype=np.uint8)
    unlock_mask = cv2.inRange(crop_img, lower_unlock, upper_unlock)

    # 计算像素数量
    pixel_count = np.sum(unlock_mask > 0)

    # "未解锁"文字需要至少50个像素（排除关卡图标边缘误检）
    MIN_UNLOCK_PIXELS = 50

    return pixel_count >= MIN_UNLOCK_PIXELS


def scan_for_unlocked_stages(image, detected_boxes):
    """
    检测已识别关卡中哪些是未解锁的

    检查每个数字框下方的80x20区域是否有"未解锁"文字

    Args:
        image: 原始图像
        detected_boxes: 已检测到的数字区域 [(x1,y1,x2,y2), ...]

    Returns:
        unlocked_indices: 未解锁关卡的索引列表
    """
    if not detected_boxes:
        return []

    unlocked_indices = []

    for idx, box in enumerate(detected_boxes):
        x1, y1, x2, y2 = box
        center_x = (x1 + x2) // 2

        # 搜索区域：数字框下方80x20
        search_area = (
            center_x - 40,
            y2,
            center_x + 40,
            y2 + 20
        )

        if detect_unlocked_text(image, search_area):
            unlocked_indices.append(idx)
            logger.info(f"[ForgottenHallStageOcr] Stage at index {idx} is locked")

    if unlocked_indices:
        logger.info(f"[ForgottenHallStageOcr] Found {len(unlocked_indices)} locked stages: {unlocked_indices}")

    return unlocked_indices


class ForgottenHallStageOcr(Ocr):
    def _find_number(self, image):
        """
        识别关卡数字 - 使用纯白色提取 + 连通组件分析

        策略（来自测试脚本 test_stage_recognition.py）：
        1. 严格提取纯白色(255,255,255)像素 - 只提取数字本身
        2. 连通组件分析 - 检测单个字符
        3. 相邻字符合并 - 组成两位数（如"10"）
        4. 宽松的单字符过滤条件 - 适应不同大小的数字
        """
        raw = image.copy()
        area = OCR_STAGE.area
        image_crop = crop(raw, area, copy=False)

        # 【关键】严格提取纯白色(255,255,255)像素
        # 这比阈值二值化更精确，不会包含背景元素
        lower_white = np.array([255, 255, 255], dtype=np.uint8)
        upper_white = np.array([255, 255, 255], dtype=np.uint8)
        pure_white_mask = cv2.inRange(image_crop, lower_white, upper_white)

        # 使用连通组件分析代替轮廓检测
        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(
            pure_white_mask, connectivity=8
        )

        # 第一步：检测所有单个字符
        char_boxes = []

        for i in range(1, num_labels):  # 0 是背景
            x = stats[i, cv2.CC_STAT_LEFT]
            y = stats[i, cv2.CC_STAT_TOP]
            w = stats[i, cv2.CC_STAT_WIDTH]
            h = stats[i, cv2.CC_STAT_HEIGHT]
            comp_area = stats[i, cv2.CC_STAT_AREA]

            # 单字符过滤条件（更宽松，适应"1"等细长数字）
            # 宽度：5-50px（"1"很细，可能只有5-8px）
            # 高度：15-50px
            if not (5 <= w <= 50 and 15 <= h <= 50):
                continue

            # 宽高比：0.1-3.0（"1"非常细长）
            aspect_ratio = w / h if h > 0 else 0
            if not (0.1 <= aspect_ratio <= 3.0):
                continue

            # 面积：>130（"1"的面积约142）
            if comp_area < 130:
                continue

            # 位置过滤：必须在有效数字区域内
            # 排除左边栏和右下角的干扰元素
            if x < 100 or x > 1150:
                continue

            char_boxes.append({
                'x': x, 'y': y, 'w': w, 'h': h,
                'x1': x, 'y1': y, 'x2': x + w, 'y2': y + h
            })

        # 第二步：合并相邻字符成两位数
        # 按X坐标排序
        char_boxes.sort(key=lambda b: b['x'])

        rectangles = []
        debug_info = []
        used = [False] * len(char_boxes)

        for i, box1 in enumerate(char_boxes):
            if used[i]:
                continue

            # 尝试找到相邻的字符组成两位数
            merged = False
            for j in range(i + 1, len(char_boxes)):
                if used[j]:
                    continue

                box2 = char_boxes[j]

                # 判断是否相邻：
                # 1. Y坐标接近（同一行）- 允许15px差异
                # 2. X坐标间距合理（相邻数字）- 允许40px间距
                y_diff = abs(box1['y'] - box2['y'])
                x_gap = box2['x'] - box1['x2']

                if y_diff < 15 and 0 < x_gap < 40:
                    # 合并两个字符
                    merged_x1 = min(box1['x1'], box2['x1'])
                    merged_y1 = min(box1['y1'], box2['y1'])
                    merged_x2 = max(box1['x2'], box2['x2'])
                    merged_y2 = max(box1['y2'], box2['y2'])

                    # 转换为绝对坐标并添加padding
                    padding = 10
                    abs_x1 = max(0, merged_x1 + area[0] - padding)
                    abs_y1 = max(0, merged_y1 + area[1] - padding)
                    abs_x2 = min(raw.shape[1], merged_x2 + area[0] + padding)
                    abs_y2 = min(raw.shape[0], merged_y2 + area[1] + padding)

                    rectangles.append((abs_x1, abs_y1, abs_x2, abs_y2))
                    debug_info.append(f"merged({box1['x']},{box1['y']})+({box2['x']},{box2['y']})")
                    used[i] = used[j] = True
                    merged = True
                    break

            # 如果没有找到相邻字符，保留单个字符（如"7"、"8"、"9"）
            if not merged:
                padding = 10
                abs_x1 = max(0, box1['x1'] + area[0] - padding)
                abs_y1 = max(0, box1['y1'] + area[1] - padding)
                abs_x2 = min(raw.shape[1], box1['x2'] + area[0] + padding)
                abs_y2 = min(raw.shape[0], box1['y2'] + area[1] + padding)

                rectangles.append((abs_x1, abs_y1, abs_x2, abs_y2))
                debug_info.append(f"single({box1['x']},{box1['y']}) {box1['w']}x{box1['h']}")
                used[i] = True

        # 调试日志
        if len(rectangles) > 0:
            logger.info(f"[ForgottenHallStageOcr] Found {len(rectangles)} digit regions: {debug_info}")
        else:
            logger.warning(f"[ForgottenHallStageOcr] No digit regions found! Components: {num_labels-1}")

        return rectangles

    def pre_process(self, image):
        """
        对关卡数字图像进行预处理，提高OCR识别准确率

        使用纯白色提取策略（与 _find_number() 保持一致）：
        严格提取纯白色(255,255,255)像素，不包含任何背景元素

        Args:
            image (np.ndarray): BGR图像，形状 (height, width, 3)

        Returns:
            np.ndarray: 二值化图像（3通道），形状 (height, width, 3)
        """
        # 【关键】使用纯白色提取，与 _find_number() 保持一致
        lower_white = np.array([255, 255, 255], dtype=np.uint8)
        upper_white = np.array([255, 255, 255], dtype=np.uint8)
        pure_white_mask = cv2.inRange(image, lower_white, upper_white)

        # 转换为3通道图像（pponnxcr要求）
        binary_3ch = cv2.merge([pure_white_mask, pure_white_mask, pure_white_mask])

        return binary_3ch

    def matched_ocr(self, image, keyword_classes, direct_ocr=False) -> list[OcrResultButton]:
        if not isinstance(keyword_classes, list):
            keyword_classes = [keyword_classes]

        boxes = self._find_number(image)
        image_list = [crop(image, area) for area in boxes]
        results = self.ocr_multi_lines(image_list)

        # 直接使用数字位置，不再需要偏移
        # 之前的 area_offset(boxes[index], (-50, 0)) 是为了补偿星星定位的偏差
        # 现在直接识别数字，位置已经准确
        #
        # 修复：单数字补零，避免 Keyword.find 的 ID 匹配误判
        # 例如 OCR 识别出 '1' 会被错误匹配到 Stage_1 (id=1)
        # 而实际关卡名称是 '01', '02', ..., '10', '11' 等
        # 补零后 '1' -> '01'，就不会触发 ID 匹配逻辑
        def format_stage_text(text):
            # 只处理纯数字文本
            if text.isdigit():
                # 单数字补零
                if len(text) == 1:
                    return f'0{text}'
            return text

        results = [
            BoxedResult(boxes[index], image_list[index], format_stage_text(text), score)
            for index, (text, score) in enumerate(results)
        ]

        results = [self._product_button(result, keyword_classes, ignore_digit=False) for result in results]
        results = [result for result in results if result.is_keyword_matched]

        # 未解锁关卡检测 - 检测已识别关卡下方的"未解锁"文字
        if results and boxes:
            locked_indices = scan_for_unlocked_stages(image, boxes)
            if locked_indices:
                # 按X坐标排序boxes以匹配results顺序
                sorted_box_indices = sorted(range(len(boxes)), key=lambda i: boxes[i][0])

                # 找出锁定关卡对应的result索引
                locked_result_indices = set()
                for box_idx in locked_indices:
                    if box_idx < len(sorted_box_indices):
                        result_idx = sorted_box_indices.index(box_idx) if box_idx in sorted_box_indices else None
                        if result_idx is not None and result_idx < len(results):
                            locked_result_indices.add(result_idx)
                            logger.info(f"[ForgottenHallStageOcr] Stage {results[result_idx].matched_keyword} is locked")

                # 过滤掉锁定的关卡
                results = [r for i, r in enumerate(results) if i not in locked_result_indices]

        logger.attr(name=f'{self.name} matched', text=results)
        return results

    def _create_virtual_button(self, stage_num, existing_boxes, keyword_classes):
        """
        为未解锁关卡创建虚拟按钮

        Args:
            stage_num: 关卡编号
            existing_boxes: 已检测到的数字区域
            keyword_classes: 关键词类列表

        Returns:
            OcrResultButton 或 None
        """
        # 获取对应关卡关键词
        # Stage_X 是模块级变量，需要通过 KEYWORDS_FORGOTTEN_HALL_STAGE 访问
        keyword = getattr(KEYWORDS_FORGOTTEN_HALL_STAGE, f'Stage_{stage_num}', None)
        if not keyword:
            logger.warning(f"[ForgottenHallStageOcr] No keyword for Stage_{stage_num}")
            return None

        # 计算虚拟按钮位置（基于关卡间距）
        if not existing_boxes:
            return None

        sorted_boxes = sorted(existing_boxes, key=lambda b: b[0])

        # 计算平均间距
        if len(sorted_boxes) >= 2:
            spacings = []
            for i in range(len(sorted_boxes) - 1):
                spacing = sorted_boxes[i+1][0] - sorted_boxes[i][0]
                spacings.append(spacing)
            avg_spacing = sum(spacings) / len(spacings)
        else:
            avg_spacing = 150  # 默认间距

        # 基于最后一个已识别box计算位置
        # 需要考虑已识别关卡的数量来计算偏移
        last_box = sorted_boxes[-1]
        # 假设已识别的关卡是连续的，最后一个box对应 len(sorted_boxes) + 6 号关卡
        # （因为关卡从7开始，sorted_boxes[0]对应第7关）
        offset = stage_num - (len(sorted_boxes) + 6)
        virtual_x = int(last_box[0] + avg_spacing * offset)

        # 创建虚拟box
        virtual_box = (
            virtual_x,
            last_box[1],
            virtual_x + (last_box[2] - last_box[0]),
            last_box[3]
        )

        # 创建虚拟 BoxedResult
        virtual_boxed = BoxedResult(virtual_box, None, f'{stage_num:02d}', 1.0)

        # 创建 OcrResultButton
        result = self._product_button(virtual_boxed, keyword_classes, ignore_digit=False)

        if result.is_keyword_matched:
            logger.info(f"[ForgottenHallStageOcr] Created virtual button for Stage_{stage_num} at x={virtual_x}")
            return result

        return None


class DraggableStageList(DraggableList):
    def insight_row(self, row: Keyword, main: ModuleBase, skip_first_screenshot=True) -> bool:
        while 1:
            result = super().insight_row(row, main=main, skip_first_screenshot=skip_first_screenshot)
            if not result:
                if row == KEYWORDS_FORGOTTEN_HALL_STAGE.Stage_1:
                    # Must have stage 1, retry if not found
                    continue
                else:
                    return False

            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                main.device.screenshot()
            button = self.keyword2button(row)

            # end
            if button.button[0] > 0:
                break

            # Stage number is insight but button is not
            logger.info("Stage number is insight, swipe left a little bit to find the entrance")
            self.drag_vector = (0.2, 0.4)
            self.drag_page("left", main=main)
            self.drag_vector = DraggableList.drag_vector
        return True

    def is_row_selected(self, button: OcrResultButton, main: ModuleBase) -> bool:
        return main.appear(ENTRANCE_CHECKED)

    def load_rows(self, main: ModuleBase):
        if main.appear(MEMORY_OF_CHAOS_CHECK) or main.appear(LAST_VASTIGES_CHECK):
            return super().load_rows(main=main)
        else:
            logger.info('Not in forgotten hall, skip load_rows()')
            return


STAGE_LIST = DraggableStageList("ForgottenHallStageList", keyword_class=ForgottenHallStage,
                                ocr_class=ForgottenHallStageOcr, search_button=OCR_STAGE,
                                check_row_order=False, drag_direction="right")


class ForgottenHallUI(DungeonUI, ForgottenHallTeam):
    def stage_choose(self, dungeon: DungeonList, skip_first_screenshot=True):
        """
        Pages:
            in: page_forgotten_hall, FORGOTTEN_HALL_CHECK
                or page_guide, Survival_Index, Forgotten_Hall
            out: page_forgotten_hall, FORGOTTEN_HALL_CHECK, selected at the given dungeon tab
        """
        logger.info(f'Stage choose {dungeon}')
        if dungeon == KEYWORDS_DUNGEON_LIST.Memory_of_Chaos:
            check_button = MEMORY_OF_CHAOS_CHECK
            click_button = MEMORY_OF_CHAOS_CLICK
        elif dungeon == KEYWORDS_DUNGEON_LIST.The_Last_Vestiges_of_Towering_Citadel:
            check_button = LAST_VASTIGES_CHECK
            click_button = LAST_VASTIGES_CLICK
        else:
            logger.error(f'Choosing {dungeon} in forgotten hall is not supported')
            return

        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # interval used in end condition
            # After clicking `click_button`, `click_button` appears, then screen goes black for a little while
            # interval prevents `check_button` being triggered in the next 0.3s
            if self.match_template_color(check_button, interval=0.3):
                logger.info(f'Stage chose at {dungeon}')
                break
            if self.handle_forgotten_hall_buff():
                continue
            if self.appear_then_click(TELEPORT, interval=2):
                continue
            if self.match_template_color(click_button, interval=1):
                self.device.click(click_button)
                self.interval_reset(check_button)
                continue

    def stage_goto(self, dungeon: DungeonList, stage_keyword: ForgottenHallStage,
                   team1_preset: int = None, team2_preset: int = None):
        """
        导航到指定关卡并配置预设编队

        Args:
            dungeon: 深渊类型
            stage_keyword: 目标关卡
            team1_preset: 第一关使用的预设编队编号 (1-12, 1-based)
            team2_preset: 第二关使用的预设编队编号 (1-12, 1-based)

        Examples:
            self = ForgottenHallUI('alas')
            self.device.screenshot()
            self.stage_goto(KEYWORDS_DUNGEON_LIST.The_Last_Vestiges_of_Towering_Citadel,
                            KEYWORDS_FORGOTTEN_HALL_STAGE.Stage_8,
                            team1_preset=1, team2_preset=2)

        Returns:
            bool: 是否成功
        """
        if not dungeon in [
            KEYWORDS_DUNGEON_LIST.Memory_of_Chaos,
            KEYWORDS_DUNGEON_LIST.The_Last_Vestiges_of_Towering_Citadel,

        ]:
            logger.error(f'DungeonList Chosen is not a forgotten hall: {dungeon}')
            return False
        if dungeon == KEYWORDS_DUNGEON_LIST.Memory_of_Chaos and stage_keyword.id > 10:
            logger.error(f'This dungeon "{dungeon}" does not have stage that greater than 10. '
                         f'{stage_keyword.id} is chosen')
            return False

        if self.appear(FORGOTTEN_HALL_CHECK):
            logger.info('Already in forgotten hall')
        else:
            # ★ 关键修复：先确保在 Guide 页面（星际和平指南）
            self.ui_ensure(page_guide)

            # 使用独立导航器（逐光捡金 Tab → 忘却之庭 Nav）
            # 旧路径已废弃: Survival_Index Tab → Forgotten_Hall Nav
            from tools.forgotten_hall_navigator import TreasuresLightwardNavigator

            navigator = TreasuresLightwardNavigator()
            if not navigator.goto_forgotten_hall_from_guide(self.device):
                logger.error('Failed to navigate to Forgotten Hall via Treasures Lightward')
                logger.error('Navigation failed, please check if the game UI has changed')
                return False

            # 旧代码（保留作为参考，游戏版本回退时可恢复）:
            # self.dungeon_tab_goto(KEYWORDS_DUNGEON_TAB.Survival_Index)
            # self.dungeon_nav_goto(KEYWORDS_DUNGEON_NAV.Forgotten_Hall)

        self.stage_choose(dungeon)
        logger.info(f'Stage list select: {stage_keyword}')
        STAGE_LIST.select_row(stage_keyword, main=self)

        # 配置预设编队
        if team1_preset or team2_preset:
            self._click_preset_team()
            self._configure_preset_teams(team1_preset, team2_preset)

        return True

    def _click_preset_team(self, skip_first_screenshot=False):
        """点击预设编队按钮并验证面板已打开

        Pages:
            in: 关卡选择完成后
            out: 预设编队面板
        """
        logger.info('Click preset team button')
        timeout = Timer(5).start()
        interval = Timer(1)
        just_clicked = False  # 标记是否刚点击过

        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if timeout.reached():
                logger.warning('Click preset team timeout')
                break

            # 使用新的预设编队面板检测模板
            if self.appear(PRESET_TEAM_PANEL_OPENED):
                logger.info('Preset team panel opened')
                break

            # 如果刚点击过但检测失败，继续循环等待面板出现
            if just_clicked:
                logger.info('Waiting for preset team panel to appear...')
                just_clicked = False
                # 移除固定延迟，依靠循环检测（screenshot()间隔已提供适当延迟）
                continue

            # 点击预设编队按钮
            if interval.reached() and self.appear(PRESET_TEAM):
                logger.info(f'[DEBUG] Clicking PRESET_TEAM button')
                self.device.click(PRESET_TEAM)
                interval.reset()
                logger.info('Preset team button clicked')
                just_clicked = True
                continue

    def _verify_team_cleared(self, battle_num: int, timeout: float = 2.0) -> bool:
        """验证队伍已被清除（匹配空白模板）

        Args:
            battle_num: 1=上半, 2=下半
            timeout: 超时时间（秒）

        Returns:
            是否成功清除
        """
        button = TEAM_SLOT_BATTLE1_EMPTY if battle_num == 1 else TEAM_SLOT_BATTLE2_EMPTY

        timer = Timer(timeout).start()
        while not timer.reached():
            self.device.screenshot()
            if self.appear(button):
                logger.info(f'Battle {battle_num} team cleared successfully')
                return True
            self.device.sleep(0.2)

        logger.warning(f'Battle {battle_num} team clear verification failed')
        return False

    def _verify_team_selected(self, battle_num: int, timeout: float = 2.0) -> bool:
        """验证队伍已被选择（不匹配空白模板）

        Args:
            battle_num: 1=上半, 2=下半
            timeout: 超时时间（秒）

        Returns:
            是否成功选择
        """
        button = TEAM_SLOT_BATTLE1_EMPTY if battle_num == 1 else TEAM_SLOT_BATTLE2_EMPTY
        # 获取实际的 Button 对象（ButtonWrapper 包含多个 Button）
        actual_button = button.buttons[0]

        logger.info(f'[DEBUG] Start verifying battle {battle_num} team selection')

        # 给界面一个短暂的初始延迟，避免立即检测时界面尚未开始刷新
        self.device.sleep(0.2)

        # 保存验证开始时的截图
        self.device.screenshot()
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

            # Debug: 输出图像尺寸
            if loop_count == 1:
                logger.info(f'[DEBUG] Template image shape: {actual_button.image.shape}')
                logger.info(f'[DEBUG] Search region shape: {image.shape}')
                logger.info(f'[DEBUG] Search area: {actual_button.search}')
                logger.info(f'[DEBUG] Button area: {actual_button.area}')
                # 保存模板图像供检查
                save_image(actual_button.image,
                          f'./log/debug/team_verification/template_battle{battle_num}_{int(time.time()*1000)}.png')

            res = cv2.matchTemplate(actual_button.image, image, cv2.TM_CCOEFF_NORMED)
            _, similarity, _, point = cv2.minMaxLoc(res)
            last_similarity = similarity

            # Debug: 输出匹配结果的形状
            if loop_count == 1:
                logger.info(f'[DEBUG] Match result shape: {res.shape}')
                logger.info(f'[DEBUG] Match point: {point}')

            logger.info(f'[DEBUG] Battle {battle_num} verification loop {loop_count}: '
                       f'similarity={similarity:.4f}, threshold=0.85, '
                       f'elapsed={timer.current_time():.2f}s')

            # 判断是否匹配（使用默认阈值 0.85）
            if similarity <= 0.85:  # 不匹配空白模板，说明有队伍了
                logger.info(f'Battle {battle_num} team selected successfully '
                           f'(similarity={similarity:.4f} <= 0.85)')
                return True

            self.device.sleep(0.2)

        # 验证失败，保存详细信息
        logger.warning(f'[DEBUG] Battle {battle_num} team selection verification failed')
        logger.warning(f'[DEBUG] Final similarity: {last_similarity:.4f}, threshold: 0.85, '
                      f'loops: {loop_count}, timeout: {timeout}s')

        # 保存失败时的完整截图
        save_image(self.device.image,
                  f'./log/debug/team_verification/verify_failed_battle{battle_num}_{int(time.time()*1000)}.png')

        # 保存裁剪区域
        crop_image = crop(self.device.image, actual_button.search)
        save_image(crop_image,
                  f'./log/debug/team_verification/crop_battle{battle_num}_{int(time.time()*1000)}.png')

        return False

    def _configure_preset_teams(self, team1_preset: int = None, team2_preset: int = None):
        """配置两关的预设编队

        Args:
            team1_preset: 第一关使用的预设编队编号 (1-12, 1-based)
            team2_preset: 第二关使用的预设编队编号 (1-12, 1-based)
        """
        # ========== 在开始配置前，先清除所有已有队伍（只清除一次） ==========
        if team1_preset or team2_preset:
            logger.info('[DEBUG] Clear all existing team selections before configuration')
            self.device.click(CLEAR_TEAM)
            self.device.sleep(0.5)  # 等待清除完成

        # ========== 配置第一关队伍 ==========
        if team1_preset:
            logger.info(f'[DEBUG] Configuring battle 1 with preset team {team1_preset}')

            # 选择预设编队
            logger.info(f'[DEBUG] Select preset team {team1_preset} for battle 1')
            self.select_preset_team(team1_preset)
            # 移除固定延迟，直接进入验证（验证方法会处理等待）

            # 验证选择成功
            if not self._verify_team_selected(battle_num=1):
                logger.warning('[DEBUG] Battle 1 team selection verification failed')

        # ========== 切换到第二关并配置队伍 ==========
        if team2_preset:
            logger.info('[DEBUG] Switch to battle 2')
            self._click_battle_switch(2)
            # 移除固定延迟，让后续操作自适应

            # 直接选择预设编队（不需要再清除）
            logger.info(f'[DEBUG] Select preset team {team2_preset} for battle 2')
            self.select_preset_team(team2_preset)
            # 移除固定延迟，直接进入验证（验证方法会处理等待）

            # 验证选择成功
            if not self._verify_team_selected(battle_num=2):
                logger.warning('[DEBUG] Battle 2 team selection verification failed')

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

        # 等待稳定
        self.device.sleep(0.3)

        return True

    def _click_preset_team_slot(self, slot_index: int):
        """点击当前可见的第N个队伍槽位

        Args:
            slot_index: 槽位索引 (0, 1, 2)
        """
        from module.base.button import Button

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
        valid, total, top = self._get_preset_team_scroll_state()

        if not valid:
            # 无滚动条，队伍数 <= 3，直接点击
            if target < 3:
                self._click_preset_team_slot(target)
                return True
            else:
                logger.error(f'Target team {team_index} not available (only {total} teams)')
                return False

        # 检查目标队伍是否存在
        if target >= total:
            logger.error(f'Target team {team_index} not available (only {total} teams)')
            return False

        # 计算目标队伍在当前视图中的位置
        visible_index = target - top

        # 如果不在可见范围(0-2)，需要滚动
        if visible_index < 0 or visible_index > 2:
            logger.info(f'Target team not visible (visible_index={visible_index}), scrolling...')
            self._drag_preset_team_slider(target)
            self.device.screenshot()

            # 重新获取状态
            _, _, top = self._get_preset_team_scroll_state()
            visible_index = target - top

        # 点击对应槽位
        self._click_preset_team_slot(visible_index)
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
            self.device.sleep(0.5)

    def exit_dungeon(self, skip_first_screenshot=True):
        """
        Pages:
            in: page_main, in forgotten hall map
            out: page_forgotten_hall, FORGOTTEN_HALL_CHECK
        """
        logger.info('Exit dungeon')
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(FORGOTTEN_HALL_CHECK):
                logger.info("Forgotten hall dungeon exited")
                break

            if self.is_in_map_exit(interval=2):
                self.device.click(MAP_EXIT)
                continue
            if self.handle_popup_confirm():
                continue
            if self.handle_popup_single():
                continue

    def enter_forgotten_hall_dungeon(self, skip_first_screenshot=True):
        """
        called after team is set

        Pages:
            in: ENTRANCE_CHECKED, ENTER_FORGOTTEN_HALL_DUNGEON
            out: page_main, in forgotten hall map
        """
        interval = Timer(3)
        timeout = Timer(3)
        while 1:  # enter ui -> popup
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(BUFF_Forgotten_Hall):
                break
            if self.match_template_color(DUNGEON_ENTER_CHECKED):
                if timeout.reached():
                    logger.info('Wait dungeon BUFF_Forgotten_Hall timeout')
                    break
            else:
                timeout.reset()

            if interval.reached() and self.team_prepared():
                self.device.click(ENTER_FORGOTTEN_HALL_DUNGEON)
                interval.reset()

        joystick = MapControlJoystick(self.config, self.device)
        skip_first_screenshot = True
        while 1:  # pop up -> dungeon inside
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.match_template_color(DUNGEON_ENTER_CHECKED):
                logger.info("Forgotten hall dungeon entered")
                break
            joystick.handle_map_run_2x()
