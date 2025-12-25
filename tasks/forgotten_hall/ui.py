import cv2
import numpy as np
from pponnxcr.predict_system import BoxedResult

from module.base.base import ModuleBase
from module.base.timer import Timer
from module.base.utils import area_offset, color_similarity_2d, crop
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

    def stage_goto(self, dungeon: DungeonList, stage_keyword: ForgottenHallStage):
        """
        Examples:
            self = ForgottenHallUI('alas')
            self.device.screenshot()
            self.stage_goto(KEYWORDS_DUNGEON_LIST.The_Last_Vestiges_of_Towering_Citadel,
                            KEYWORDS_FORGOTTEN_HALL_STAGE.Stage_8)
        """
        if not dungeon in [
            KEYWORDS_DUNGEON_LIST.Memory_of_Chaos,
            KEYWORDS_DUNGEON_LIST.The_Last_Vestiges_of_Towering_Citadel,

        ]:
            logger.error(f'DungeonList Chosen is not a forgotten hall: {dungeon}')
            return
        if dungeon == KEYWORDS_DUNGEON_LIST.Memory_of_Chaos and stage_keyword.id > 10:
            logger.error(f'This dungeon "{dungeon}" does not have stage that greater than 10. '
                         f'{stage_keyword.id} is chosen')
            return

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
                return

            # 旧代码（保留作为参考，游戏版本回退时可恢复）:
            # self.dungeon_tab_goto(KEYWORDS_DUNGEON_TAB.Survival_Index)
            # self.dungeon_nav_goto(KEYWORDS_DUNGEON_NAV.Forgotten_Hall)

        self.stage_choose(dungeon)
        logger.info(f'Stage list select: {stage_keyword}')
        STAGE_LIST.select_row(stage_keyword, main=self)

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
