import cv2
import numpy as np
import os
import time
from pponnxcr.predict_system import BoxedResult

from module.base.base import ModuleBase
from module.base.timer import Timer
from module.base.utils import area_offset, color_similarity_2d, crop, save_image
from module.logger.logger import logger, logger_debug
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
from tasks.map.control.control import MapControl
from tasks.map.control.joystick import JoystickContact, MapControlJoystick


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

    def _product_button(
            self,
            boxed_result: BoxedResult,
            keyword_classes,
            lang: str = None,
            ignore_punctuation=True,
            ignore_digit=True,
            star_count=None
    ) -> OcrResultButton:
        """
        重写父类方法，支持星级信息

        Args:
            boxed_result: OCR结果
            keyword_classes: 关键词类列表
            lang: 语言
            ignore_punctuation: 忽略标点
            ignore_digit: 忽略纯数字
            star_count: 星级数量（0-3）

        Returns:
            OcrResultButton: 包含星级信息的按钮对象
        """
        if not isinstance(keyword_classes, list):
            keyword_classes = [keyword_classes]

        matched_keyword = self._match_result(
            boxed_result.ocr_text,
            keyword_classes=keyword_classes,
            lang=lang,
            ignore_punctuation=ignore_punctuation,
            ignore_digit=ignore_digit,
        )
        button = OcrResultButton(boxed_result, matched_keyword, star_count=star_count)
        return button

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

        # 星级检测（新增）
        from tools.forgotten_hall_star_detector.star_detector import (
            detect_yellow_stars,
            cluster_stars_by_proximity,
            match_stars_to_stages
        )

        star_regions = detect_yellow_stars(image)
        star_clusters = cluster_stars_by_proximity(star_regions)
        stage_star_map = match_stars_to_stages(star_clusters, boxes)

        # 创建按钮并输出详细星级信息
        temp_results = []
        for index, result in enumerate(results):
            star_count = stage_star_map.get(index, 0)
            button = self._product_button(
                result,
                keyword_classes,
                ignore_digit=False,
                star_count=star_count
            )

            # 输出每一关的星级信息（仅输出匹配成功的关卡）
            if button.is_keyword_matched:
                stage_name = button.matched_keyword
                if star_count == 3:
                    logger.info(f'[ForgottenHallStageOcr] {stage_name}: ★★★ (已完成)')
                elif star_count > 0:
                    logger.info(f'[ForgottenHallStageOcr] {stage_name}: {"★" * star_count}{"☆" * (3 - star_count)}')
                else:
                    logger.info(f'[ForgottenHallStageOcr] {stage_name}: ☆☆☆ (未完成)')

            temp_results.append(button)

        results = [r for r in temp_results if r.is_keyword_matched]

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


class ForgottenHallUI(DungeonUI, ForgottenHallTeam, MapControl):
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
            logger.hr('Configure preset teams', level=1)

            # 点击预设编队按钮（增加超时，失败仅警告）
            self._click_preset_team(timeout=15)

            # 配置预设编队（增加等待和重试，失败仅警告）
            self._configure_preset_teams(team1_preset, team2_preset)

            logger.info('Preset teams configuration completed')

        return True

    def _click_preset_team(self, skip_first_screenshot=False, timeout=15):
        """点击预设编队按钮并等待面板打开

        Args:
            skip_first_screenshot: 是否跳过第一次截图
            timeout: 超时时间（秒），默认 15 秒

        Pages:
            in: 关卡选择完成后
            out: 预设编队面板
        """
        logger.info('Click preset team button')
        timeout_timer = Timer(timeout).start()
        interval = Timer(1.5)  # 点击间隔
        check_interval = 0.5  # 检测间隔缩短到 0.5 秒
        just_clicked = False  # 标记是否刚点击过

        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 超时检测 - 仅警告，不中断
            if timeout_timer.reached():
                logger.warning(f'Click preset team timeout after {timeout}s')
                logger.warning('Preset team panel may not have opened, but continuing...')
                break

            # 使用新的预设编队面板检测模板
            if self.appear(PRESET_TEAM_PANEL_OPENED):
                logger.info('Preset team panel opened successfully')
                break

            # 如果刚点击过但检测失败，继续循环等待面板出现
            if just_clicked:
                logger.info(f'Waiting for preset team panel (checking every {check_interval}s)...')
                self.device.sleep(check_interval)
                just_clicked = False
                continue

            # 点击预设编队按钮
            if interval.reached() and self.appear(PRESET_TEAM):
                logger.info('Clicking PRESET_TEAM button...')
                self.device.click(PRESET_TEAM)
                interval.reset()
                just_clicked = True
                continue

            # 持续检测（即使没有点击）
            self.device.sleep(check_interval)

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

        logger.debug(f'Start verifying battle {battle_num} team selection')

        # 给界面一个短暂的初始延迟，避免立即检测时界面尚未开始刷新
        self.device.sleep(0.2)

        # 保存验证开始时的截图（仅调试模式）
        self.device.screenshot()
        if logger_debug:
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

            # Debug: 输出图像尺寸（仅调试模式）
            if loop_count == 1:
                logger.debug(f'Template shape: {actual_button.image.shape}, search shape: {image.shape}')
                logger.debug(f'Search area: {actual_button.search}, button area: {actual_button.area}')
                # 保存模板图像供检查（仅调试模式）
                if logger_debug:
                    save_image(actual_button.image,
                              f'./log/debug/team_verification/template_battle{battle_num}_{int(time.time()*1000)}.png')

            res = cv2.matchTemplate(actual_button.image, image, cv2.TM_CCOEFF_NORMED)
            _, similarity, _, point = cv2.minMaxLoc(res)
            last_similarity = similarity

            # Debug: 输出匹配结果（仅调试模式）
            if loop_count == 1:
                logger.debug(f'Match result shape: {res.shape}, match point: {point}')

            logger.debug(f'Verification loop {loop_count}: similarity={similarity:.4f}, '
                        f'threshold=0.85, elapsed={timer.current_time():.2f}s')

            # 判断是否匹配（使用默认阈值 0.85）
            if similarity <= 0.85:  # 不匹配空白模板，说明有队伍了
                logger.info(f'Battle {battle_num} team selected successfully '
                           f'(similarity={similarity:.4f} <= 0.85)')
                return True

            self.device.sleep(0.2)

        # 验证失败，保存详细信息
        logger.warning(f'Battle {battle_num} team selection verification failed')
        logger.debug(f'Final similarity: {last_similarity:.4f}, threshold: 0.85, '
                    f'loops: {loop_count}, timeout: {timeout}s')

        # 保存失败时的完整截图（仅调试模式）
        if logger_debug:
            save_image(self.device.image,
                      f'./log/debug/team_verification/verify_failed_battle{battle_num}_{int(time.time()*1000)}.png')

            # 保存裁剪区域
            crop_image = crop(self.device.image, actual_button.search)
            save_image(crop_image,
                      f'./log/debug/team_verification/crop_battle{battle_num}_{int(time.time()*1000)}.png')

        return False

    def _verify_team_selected_with_retry(self, battle_num: int, max_retry=3, retry_delay=2):
        """验证队伍选择，失败后重试（最终失败仅警告）

        Args:
            battle_num: 关卡编号（1=上半，2=下半）
            max_retry: 最大重试次数，默认 3 次
            retry_delay: 重试间隔（秒），默认 2 秒
        """
        for attempt in range(1, max_retry + 1):
            logger.info(f'Verifying battle {battle_num} team selection (attempt {attempt}/{max_retry})...')

            # 调用现有的 _verify_team_selected() 方法
            if self._verify_team_selected(battle_num=battle_num):
                logger.info(f'Battle {battle_num} team selection verified successfully')
                return  # 验证成功，返回

            # 验证失败，准备重试
            if attempt < max_retry:
                logger.warning(f'Battle {battle_num} team verification failed, retrying in {retry_delay}s...')
                self.device.sleep(retry_delay)
            else:
                # 最终失败，仅警告不中断
                logger.warning(f'Battle {battle_num} team verification failed after {max_retry} attempts')
                logger.warning('Team may not be correctly selected, but continuing...')

    def _configure_preset_teams(self, team1_preset: int = None, team2_preset: int = None):
        """配置两关的预设编队（增加等待和验证，失败不中断）

        Args:
            team1_preset: 第一关使用的预设编队编号 (1-12, 1-based)
            team2_preset: 第二关使用的预设编队编号 (1-12, 1-based)
        """
        # ========== 在开始配置前，先清除所有已有队伍（只清除一次） ==========
        if team1_preset or team2_preset:
            logger.info('Clearing all existing team selections...')
            self.device.click(CLEAR_TEAM)

            # 新增：等待并验证清除成功
            timeout = Timer(5).start()  # 增加超时到 5 秒
            cleared = False
            while not timeout.reached():
                self.device.screenshot()
                if self.appear(TEAM_SLOT_BATTLE1_EMPTY):
                    logger.info('Team slots cleared successfully')
                    cleared = True
                    break
                self.device.sleep(0.5)  # 检测间隔 0.5 秒

            if not cleared:
                logger.warning('Team slots clear verification timeout, but continuing...')

        # ========== 配置第一关队伍 ==========
        if team1_preset:
            logger.info(f'Configuring battle 1 with preset team {team1_preset}')

            # 选择预设编队（内部已有重试逻辑）
            self.select_preset_team(team1_preset)

            # 等待并验证选择（增加重试）
            self._verify_team_selected_with_retry(battle_num=1, max_retry=3)

        # ========== 切换到第二关并配置队伍 ==========
        if team2_preset:
            logger.info('Switching to battle 2...')

            # 切换下半并等待验证
            self._click_battle_switch_with_wait(2, timeout=5)

            logger.info(f'Configuring battle 2 with preset team {team2_preset}')

            # 选择预设编队
            self.select_preset_team(team2_preset)

            # 等待并验证选择
            self._verify_team_selected_with_retry(battle_num=2, max_retry=3)

        logger.info('Preset teams configuration process completed')

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

    def _click_battle_switch_with_wait(self, battle_num: int, timeout=5):
        """切换到指定关卡并等待验证（失败不中断）

        Args:
            battle_num: 关卡编号（2=下半）
            timeout: 超时时间（秒），默认 5 秒
        """
        if battle_num == 2:
            logger.info('Clicking battle 2 switch...')
            self.device.click(BATTLE_2_SWITCH)

            # 等待并验证切换成功
            timer = Timer(timeout).start()
            switched = False

            while not timer.reached():
                self.device.screenshot()
                # 检测下半空白槽位出现
                if self.appear(TEAM_SLOT_BATTLE2_EMPTY):
                    logger.info('Successfully switched to battle 2')
                    switched = True
                    break
                self.device.sleep(0.5)  # 检测间隔 0.5 秒

            if not switched:
                logger.warning(f'Battle 2 switch verification timeout after {timeout}s')
                logger.warning('Switch may have failed, but continuing...')
        else:
            logger.warning(f'Unsupported battle number: {battle_num}')

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

    def detect_battle_result(self, timeout=10, skip_first_screenshot=True):
        """
        Detect battle result after combat_execute() completes

        Args:
            timeout: Maximum time to wait for result detection (seconds)
            skip_first_screenshot: Whether to skip first screenshot

        Returns:
            str: 'success', 'failure', or 'timeout'

        Pages:
            in: After combat_execute()
            out: COMBAT_AGAIN (success) or BATTLE_FAILED (failure)
        """
        from tasks.combat.assets.assets_combat_finish import COMBAT_AGAIN
        from tasks.forgotten_hall.assets.assets_forgotten_hall_ui import BATTLE_FAILED

        logger.hr('Detect battle result', level=2)
        timer = Timer(timeout).start()
        stuck_clear_timer = Timer(10).start()  # 每 10 秒清除一次 stuck record

        while not timer.reached():
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 定期清除 stuck record（遵循 SRC 官方模式，参考 tasks/login/login.py）
            # 解决 handle_combat_damage_change() 失效导致的 wait too long 问题
            if stuck_clear_timer.reached():
                logger.info('[detect_battle_result] Clear stuck record (10s interval)')
                self.device.stuck_record_clear()
                stuck_clear_timer.reset()

            # 使用 appear() + interval 替代 match_template_color()
            if self.appear(COMBAT_AGAIN, interval=0.5):
                logger.info('Battle succeeded - COMBAT_AGAIN detected')
                return 'success'

            if self.appear(BATTLE_FAILED, interval=0.5):
                logger.info('Battle failed - BATTLE_FAILED detected')
                return 'failure'

            self.device.sleep(0.5)

        logger.warning(f'Battle result detection timeout after {timeout}s')
        return 'timeout'

    def handle_battle_failure(self, skip_first_screenshot=False):
        """
        Handle battle failure screen and return to stage selection

        Args:
            skip_first_screenshot: Whether to skip first screenshot

        Returns:
            bool: True if successfully returned to stage selection

        Pages:
            in: BATTLE_FAILED screen
            out: FORGOTTEN_HALL_CHECK (stage selection)
        """
        from tasks.forgotten_hall.assets.assets_forgotten_hall_ui import RETURN_TO_FORGOTTEN_HALL

        logger.hr('Handle battle failure', level=2)
        timeout = Timer(10).start()
        clicked_return = False

        while not timeout.reached():
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # End condition: back at stage selection
            if self.appear(FORGOTTEN_HALL_CHECK):
                logger.info('Successfully returned to stage selection')
                self.device.screenshot()
                STAGE_LIST.load_rows(main=self)
                return True

            # Click return button using match_template_color for better detection
            if not clicked_return and self.match_template_color(RETURN_TO_FORGOTTEN_HALL, interval=2):
                self.device.click(RETURN_TO_FORGOTTEN_HALL)
                logger.info('Clicked return to forgotten hall button')
                clicked_return = True
                continue

        logger.error('Failed to return to stage selection after battle failure')
        return False

    def handle_battle_success(self):
        """
        Handle battle success by clicking through reward screens

        Returns:
            bool: True if successfully handled

        Pages:
            in: COMBAT_AGAIN screen
            out: FORGOTTEN_HALL_CHECK
        """
        from tasks.combat.assets.assets_combat_finish import COMBAT_AGAIN

        logger.hr('Handle battle success', level=2)
        timeout = Timer(15).start()

        while not timeout.reached():
            self.device.screenshot()

            if self.appear(FORGOTTEN_HALL_CHECK):
                logger.info('Battle success handled, returned to forgotten hall')
                return True

            if self.appear_then_click(COMBAT_AGAIN, interval=3):
                continue

            if self.handle_reward(interval=2):
                continue

            if self.handle_popup_confirm():
                continue
            if self.handle_popup_single():
                continue

            self.device.sleep(0.5)

        logger.warning('Battle success handling timeout')
        return True

    def enter_and_battle_with_retry(self, max_retries=3, skip_first_screenshot=True):
        """
        Enter dungeon, battle, and auto-retry on failure

        Args:
            max_retries: Maximum number of retry attempts
            skip_first_screenshot: Whether to skip first screenshot

        Returns:
            tuple: (success: bool, attempts_used: int)

        Pages:
            in: FORGOTTEN_HALL_CHECK (stage selection)
            out: FORGOTTEN_HALL_CHECK (after battle)
        """
        logger.hr('Enter dungeon with auto-retry enabled', level=1)
        logger.attr('MaxRetries', max_retries)

        for attempt in range(1, max_retries + 1):
            logger.hr(f'Battle Attempt {attempt}/{max_retries}', level=2)

            # Step 1: Enter dungeon
            logger.info(f'Attempt {attempt}: Entering dungeon')
            self.enter_forgotten_hall_dungeon(skip_first_screenshot=skip_first_screenshot)
            skip_first_screenshot = False

            # Step 2: Detect result
            logger.info(f'Attempt {attempt}: Detecting battle result')
            result = self.detect_battle_result(timeout=10)

            # Step 3: Handle result
            if result == 'success':
                logger.info(f'Battle succeeded on attempt {attempt}/{max_retries}')
                self.handle_battle_success()
                return (True, attempt)

            elif result == 'failure':
                logger.warning(f'Battle failed on attempt {attempt}/{max_retries}')

                if not self.handle_battle_failure():
                    logger.error(f'Failed to return to stage selection, cannot retry')
                    return (False, attempt)

                if attempt >= max_retries:
                    logger.error(f'Max retries ({max_retries}) exceeded, giving up')
                    return (False, attempt)

                logger.info(f'Waiting 2s before retry attempt {attempt+1}')
                self.device.sleep(2.0)
                continue

            else:  # timeout
                logger.error(f'Battle result detection timeout on attempt {attempt}')
                logger.info('Attempting to exit dungeon after timeout')
                self.exit_dungeon()

                if attempt >= max_retries:
                    logger.error(f'Max retries ({max_retries}) exceeded after timeout')
                    return (False, attempt)

                logger.info(f'Retrying after timeout, attempt {attempt+1}')
                self.device.sleep(2.0)
                continue

        logger.error('Unexpected exit from retry loop')
        return (False, max_retries)

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

        # Dungeon entered, start auto engage enemy
        logger.info('Dungeon entered, starting auto engage enemy')
        success = self.auto_engage_enemy(move_duration=8, timeout=15)
        if success:
            logger.info('Successfully engaged enemy, executing combat')

            # Define battle end detection function
            def is_battle_end():
                """Check if battle has ended (success or failure)"""
                try:
                    from tasks.combat.assets.assets_combat_finish import COMBAT_AGAIN
                    from tasks.forgotten_hall.assets.assets_forgotten_hall_ui import BATTLE_FAILED

                    # 定期清除 stuck record（遵循 SRC 官方模式，参考 tasks/login/login.py）
                    # 解决 handle_combat_damage_change() 失效导致的 wait too long 问题
                    if not hasattr(self, '_battle_end_stuck_timer'):
                        from module.base.timer import Timer
                        self._battle_end_stuck_timer = Timer(10).start()

                    if self._battle_end_stuck_timer.reached():
                        logger.info('[is_battle_end] Clear stuck record (10s interval)')
                        self.device.stuck_record_clear()
                        self._battle_end_stuck_timer.reset()

                    # 使用 appear() + interval 检测战斗结束
                    if self.appear(BATTLE_FAILED, interval=0.5):
                        logger.info('[is_battle_end] BATTLE_FAILED detected')
                        return True

                    if self.appear(COMBAT_AGAIN, interval=0.5):
                        logger.info('[is_battle_end] COMBAT_AGAIN detected')
                        return True

                    return False
                except Exception as e:
                    logger.error(f'[is_battle_end] Exception: {e}')
                    return False

            # Execute combat with custom end detection
            logger.info(f'[DEBUG] Passing expected_end={is_battle_end}, callable={callable(is_battle_end)}')
            self.combat_execute(expected_end=is_battle_end)
            logger.info('[DEBUG] combat_execute() returned')
        else:
            logger.warning('Failed to auto-engage enemy')

    def auto_engage_enemy(self, move_duration=8, timeout=15, skip_first_screenshot=True):
        """
        Automatically move forward and engage enemy in forgotten hall dungeon.
        Uses simple forward movement with continuous enemy detection.

        Args:
            move_duration: How long to move forward (seconds), default 8
            timeout: Maximum time to spend trying to find enemy (seconds), default 15
            skip_first_screenshot: Whether to skip first screenshot

        Returns:
            bool: True if successfully engaged in combat, False otherwise

        Pages:
            in: DUNGEON_ENTER_CHECKED (just entered dungeon)
            out: is_combat_executing() or timeout
        """
        logger.hr('Auto engage enemy', level=1)
        logger.attr('MoveDuration', move_duration)
        logger.attr('Timeout', timeout)

        # Initialize timers
        move_timer = Timer(move_duration).start()
        timeout_timer = Timer(timeout).start()
        enemy_check_interval = Timer(0.3).start()
        movement_interval = Timer(0.5).start()

        # Phase 1: Move forward while detecting enemies
        logger.info('Phase 1: Moving forward and detecting enemies')
        with JoystickContact(self) as contact:
            while not move_timer.reached():
                if skip_first_screenshot:
                    skip_first_screenshot = False
                else:
                    self.device.screenshot()

                # Check if already in combat (early success)
                if self.is_combat_executing():
                    logger.info('Entered combat during movement')
                    return True

                # Enable 2x running
                self.handle_map_run_2x()

                # Set joystick to move forward (direction=0 means forward)
                if movement_interval.reached():
                    contact.set(direction=0, run=True)
                    movement_interval.reset()

                # Enemy detection
                if enemy_check_interval.reached():
                    self.aim.predict(self.device.image, enemy=True, item=False, show_log=False)
                    if self.aim.aimed_enemy:
                        logger.info(f'Enemy detected at {self.aim.aimed_enemy}')
                        # Click attack button
                        self.handle_map_A()
                    enemy_check_interval.reset()

                # Check timeout
                if timeout_timer.reached():
                    logger.warning('Auto engage timeout during movement phase')
                    break

        # Phase 2: Continue searching for enemy without movement
        logger.info('Phase 2: Stationary enemy search')
        while not timeout_timer.reached():
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # Check combat
            if self.is_combat_executing():
                logger.info('Entered combat after movement')
                return True

            # Keep detecting and attacking
            if enemy_check_interval.reached():
                self.aim.predict(self.device.image, enemy=True, item=False, show_log=False)
                if self.aim.aimed_enemy:
                    logger.info(f'Enemy detected at {self.aim.aimed_enemy}')
                    self.handle_map_A()
                enemy_check_interval.reset()

        # Phase 3: Fallback mechanism
        logger.warning('Auto engage enemy timeout, using combat_poor_try fallback')
        result = self.combat_poor_try()
        success = len(result) > 0
        if success:
            logger.info('Combat engaged via fallback mechanism')
        else:
            logger.warning('Failed to engage enemy even with fallback')
        return success

    def scan_all_stages(self, max_stage: int = 12) -> dict:
        """
        扫描所有关卡的星数状态

        通过左右滑动关卡列表，识别所有可见关卡的星数
        利用现有的 STAGE_LIST.load_rows() 和 OcrResultButton.star_count

        Args:
            max_stage: 最大关卡数（混沌回忆=12, 忘却之庭=15）

        Returns:
            dict[int, int]: {关卡编号: 星数} 映射
            例如: {1: 3, 2: 3, 3: 2, 4: 0, ...}

        Pages:
            in: FORGOTTEN_HALL_CHECK (关卡选择界面)
            out: FORGOTTEN_HALL_CHECK (关卡选择界面)
        """
        logger.hr('Scan all stages', level=2)
        stage_stars = {}
        scanned_stages = set()

        # 先滑动到最左边（第1关）
        logger.info('Scrolling to stage 1')
        stage_1 = KEYWORDS_FORGOTTEN_HALL_STAGE.Stage_1
        STAGE_LIST.insight_row(stage_1, main=self)

        # 分批扫描
        max_scroll_attempts = 5
        scroll_count = 0

        while len(scanned_stages) < max_stage and scroll_count < max_scroll_attempts:
            self.device.screenshot()
            STAGE_LIST.load_rows(main=self)

            # 从当前可见关卡中提取星数
            new_stages_found = False
            for button in STAGE_LIST.cur_buttons:
                if button.matched_keyword:
                    stage_num = button.matched_keyword.id
                    if stage_num not in scanned_stages and stage_num <= max_stage:
                        star_count = button.star_count if button.star_count is not None else 0
                        stage_stars[stage_num] = star_count
                        scanned_stages.add(stage_num)
                        new_stages_found = True
                        logger.info(f'Stage {stage_num}: {star_count} stars')

            # 如果还没扫描完且有新发现，向右滑动
            if len(scanned_stages) < max_stage:
                if not new_stages_found:
                    # 没有新关卡，可能已经到头了
                    logger.info('No new stages found, stopping scan')
                    break
                logger.info(f'Scrolling right, scanned {len(scanned_stages)}/{max_stage} stages')
                STAGE_LIST.drag_page('right', main=self)
                self.device.sleep(0.5)
                scroll_count += 1

        # 填充未扫描到的关卡为0星
        for i in range(1, max_stage + 1):
            if i not in stage_stars:
                stage_stars[i] = 0
                logger.warning(f'Stage {i} not scanned, assuming 0 stars')

        logger.info(f'Scan complete: {stage_stars}')
        return stage_stars

    def find_starting_stage(self, stage_stars: dict, target_stars: int = 3, max_stage: int = 12) -> int:
        """
        根据星数扫描结果确定起始挑战关卡

        逻辑：
        1. 如果最高关卡已达目标星数，返回 -1 (任务完成)
        2. 否则找到最高的未达目标星数的解锁关卡

        Args:
            stage_stars: scan_all_stages() 返回的星数映射
            target_stars: 目标星数（默认3）
            max_stage: 最大关卡数

        Returns:
            int: 起始关卡编号，-1 表示全部完成
        """
        # 检查最高关卡是否已完成
        if stage_stars.get(max_stage, 0) >= target_stars:
            logger.info(f'Stage {max_stage} already has {target_stars}+ stars, task complete')
            return -1

        # 从最高关卡向下找第一个可挑战的关卡
        # 关卡解锁条件：前一关已通关（星数>0）或是第1关
        for stage in range(max_stage, 0, -1):
            stars = stage_stars.get(stage, 0)
            if stars < target_stars:
                # 检查是否解锁（前一关有星数或是第1关）
                if stage == 1 or stage_stars.get(stage - 1, 0) > 0:
                    logger.info(f'Starting stage: {stage} (current: {stars} stars, target: {target_stars})')
                    return stage

        # 理论上不会到达这里
        logger.warning('No starting stage found, starting from stage 1')
        return 1

    def get_stage_star_count(self, stage_num: int) -> int:
        """
        获取指定关卡的当前星数

        在战斗结束返回关卡选择界面后调用，
        用于判断是否达成目标星数

        Args:
            stage_num: 关卡编号

        Returns:
            int: 星数 (0-3)，未找到返回 -1
        """
        # 确保关卡在视野内
        stage_keyword = getattr(KEYWORDS_FORGOTTEN_HALL_STAGE, f'Stage_{stage_num}')
        STAGE_LIST.insight_row(stage_keyword, main=self)

        self.device.screenshot()
        STAGE_LIST.load_rows(main=self)

        for button in STAGE_LIST.cur_buttons:
            if button.matched_keyword and button.matched_keyword.id == stage_num:
                star_count = button.star_count if button.star_count is not None else 0
                logger.info(f'Stage {stage_num} current stars: {star_count}')
                return star_count

        logger.warning(f'Stage {stage_num} not found in current view')
        return -1
