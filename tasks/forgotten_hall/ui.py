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
from tasks.base.assets.assets_base_page import CLOSE, FORGOTTEN_HALL_CHECK, MAP_EXIT
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


def detect_unlocked_text(image, search_area, ocr_model=None, save_debug=False, debug_index=0):
    """
    检测指定区域是否有"未解锁"文字

    使用OCR直接识别文字，比颜色检测更准确

    Args:
        image: 原始图像 (BGR格式)
        search_area: 搜索区域 (x1, y1, x2, y2)
        ocr_model: OCR模型实例（可选，用于复用）
        save_debug: 是否保存调试图像
        debug_index: 调试序号

    Returns:
        bool: 是否检测到"未解锁"文字
    """
    from module.ocr.models import TextSystem

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

    # 区域太小，跳过OCR
    if crop_img.shape[0] < 5 or crop_img.shape[1] < 5:
        return False

    # 保存调试图像
    if save_debug or logger_debug:
        os.makedirs('./log/debug/unlock_detector', exist_ok=True)
        timestamp = int(time.time() * 1000)

        # 保存裁剪区域
        crop_path = f'./log/debug/unlock_detector/{timestamp}_idx{debug_index}_crop.png'
        save_image(crop_img, crop_path)

        # 保存标注了检测区域的完整图像
        marked_img = image.copy()
        cv2.rectangle(marked_img, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.putText(marked_img, f'#{debug_index}', (x1, y1-5),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
        full_path = f'./log/debug/unlock_detector/{timestamp}_idx{debug_index}_full.png'
        save_image(marked_img, full_path)

        logger.info(f'[UnlockDetector] Debug images saved: {timestamp}_idx{debug_index}_*.png')

    # 使用OCR识别文字
    if ocr_model is None:
        ocr_model = TextSystem('zhs')  # 中文简体模型

    try:
        # ocr_single_line 返回 (text, score) 元组
        text, score = ocr_model.ocr_single_line(crop_img)
        logger.debug(f'[UnlockDetector] OCR result at idx{debug_index}: "{text}" (score={score:.2f})')

        # 检查是否包含"未解锁"或"锁"
        if text and ('未解锁' in text or '锁' in text or 'unlock' in text.lower()):
            logger.info(f'[UnlockDetector] Detected locked stage at idx{debug_index}: "{text}"')
            return True
        elif not text:
            logger.debug(f'[UnlockDetector] No text recognized at idx{debug_index}')
    except Exception as e:
        logger.warning(f'[UnlockDetector] OCR failed at idx{debug_index}: {e}')

    return False


def scan_for_unlocked_stages(image, detected_boxes, save_debug=False):
    """
    检测已识别关卡中哪些是未解锁的

    检查每个数字框下方的区域是否有"未解锁"文字

    Args:
        image: 原始图像
        detected_boxes: 已检测到的数字区域 [(x1,y1,x2,y2), ...]
        save_debug: 是否保存调试图像

    Returns:
        unlocked_indices: 未解锁关卡的索引列表
    """
    from module.ocr.models import TextSystem

    if not detected_boxes:
        return []

    # 创建OCR模型实例复用，提高性能
    ocr_model = TextSystem('zhs')  # 中文简体模型
    unlocked_indices = []

    for idx, box in enumerate(detected_boxes):
        x1, y1, x2, y2 = box
        center_x = (x1 + x2) // 2

        # 搜索区域：数字框下方80x20区域
        search_area = (
            center_x - 40,  # 左边界
            y2,              # 数字框底部
            center_x + 40,   # 右边界
            y2 + 20          # 向下延伸20px
        )

        if detect_unlocked_text(image, search_area, ocr_model=ocr_model,
                               save_debug=save_debug, debug_index=idx):
            unlocked_indices.append(idx)

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

            # 单字符过滤条件
            # 宽度：3-50px
            # 高度：10-50px
            if not (3 <= w <= 50 and 10 <= h <= 50):
                continue

            # 宽高比：0.1-3.0（"1"非常细长）
            aspect_ratio = w / h if h > 0 else 0
            if not (0.1 <= aspect_ratio <= 3.0):
                continue

            # 面积：>30（过滤水晶边缘等小干扰）
            if comp_area < 30:
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
                # 2. X坐标间距合理（相邻数字）- 允许-5到50px间距
                #    负值表示重叠，0表示相连，正值表示间隔
                y_diff = abs(box1['y'] - box2['y'])
                x_gap = box2['x'] - box1['x2']

                if y_diff < 15 and -5 <= x_gap <= 50:
                    # 合并两个字符
                    merged_x1 = min(box1['x1'], box2['x1'])
                    merged_y1 = min(box1['y1'], box2['y1'])
                    merged_x2 = max(box1['x2'], box2['x2'])
                    merged_y2 = max(box1['y2'], box2['y2'])

                    # 转换为绝对坐标并添加padding
                    padding = 20
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
                padding = 20
                abs_x1 = max(0, box1['x1'] + area[0] - padding)
                abs_y1 = max(0, box1['y1'] + area[1] - padding)
                abs_x2 = min(raw.shape[1], box1['x2'] + area[0] + padding)
                abs_y2 = min(raw.shape[0], box1['y2'] + area[1] + padding)

                rectangles.append((abs_x1, abs_y1, abs_x2, abs_y2))
                debug_info.append(f"single({box1['x']},{box1['y']}) {box1['w']}x{box1['h']}")
                used[i] = True

        # 调试日志
        if len(rectangles) > 0:
            logger.info(f"[ForgottenHallStageOcr] Found {len(rectangles)} digit regions")
            for i, (info, rect) in enumerate(zip(debug_info, rectangles)):
                logger.info(f"  Region {i+1}: {info} -> box={rect}")
        else:
            logger.warning(f"[ForgottenHallStageOcr] No digit regions found! Components: {num_labels-1}")

        return rectangles

    def pre_process(self, image):
        """
        对关卡数字图像进行预处理，提高OCR识别准确率

        不进行预处理，直接返回原始图像
        （测试发现纯白色提取会导致某些数字识别失败）

        Args:
            image (np.ndarray): BGR图像，形状 (height, width, 3)

        Returns:
            np.ndarray: 原始图像
        """
        # 不进行预处理，直接返回原始图像
        return image

    def filter_consecutive_stages(self, results):
        """
        过滤掉不连续的孤立关卡号

        通过检测最长连续序列，自动过滤误识别的孤立数字。
        例如：[9, 7, 10, 11, 12] → [9, 10, 11, 12]（移除孤立的7）

        Args:
            results: 已通过keyword匹配的OcrResultButton列表

        Returns:
            过滤后的结果列表（只保留最长连续序列）

        Examples:
            >>> # 场景1：单个孤立数字
            >>> [9, 7, 10, 11, 12] → [9, 10, 11, 12]
            >>>
            >>> # 场景2：多个孤立数字
            >>> [5, 8, 9, 10, 11] → [8, 9, 10, 11]
            >>>
            >>> # 场景3：无连续数字（全部保留）
            >>> [1, 3, 5, 7] → [1, 3, 5, 7]
            >>>
            >>> # 场景4：正常连续（无过滤）
            >>> [9, 10, 11, 12] → [9, 10, 11, 12]
        """
        if len(results) <= 1:
            return results

        # 提取关卡号（stage_id, result）元组列表
        stage_ids = [(r.matched_keyword.id, r) for r in results]
        stage_ids.sort(key=lambda x: x[0])  # 按关卡号排序

        # 找出所有连续序列
        sequences = []
        current_seq = [stage_ids[0]]

        for i in range(1, len(stage_ids)):
            prev_id = stage_ids[i-1][0]
            curr_id = stage_ids[i][0]

            if curr_id == prev_id + 1:  # 连续
                current_seq.append(stage_ids[i])
            else:  # 不连续，开始新序列
                sequences.append(current_seq)
                current_seq = [stage_ids[i]]

        sequences.append(current_seq)  # 添加最后一个序列

        # 找到最长序列（如果有多个相同长度，选数字较大的）
        longest_seq = max(sequences, key=lambda seq: (len(seq), seq[0][0]))

        # 如果最长序列长度 <= 1，说明没有连续数字，全部保留
        if len(longest_seq) <= 1:
            logger.info('[Continuity Filter] No consecutive sequence found, keeping all results')
            return results

        # 提取保留的结果
        kept_ids = {stage_id for stage_id, _ in longest_seq}
        filtered_results = [r for r in results if r.matched_keyword.id in kept_ids]

        # 日志记录被过滤的数字
        removed_ids = [stage_id for stage_id, _ in stage_ids
                       if stage_id not in kept_ids]
        if removed_ids:
            logger.warning(f'[Continuity Filter] Removed isolated stages: {removed_ids}')
            logger.info(f'[Continuity Filter] Kept consecutive sequence: {sorted(kept_ids)}')

        return filtered_results

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

        # 连续性过滤 - 移除孤立的误识别数字
        results = self.filter_consecutive_stages(results)

        # 未解锁关卡检测 - 标记未解锁关卡但不过滤（保留用于导航）
        # 先初始化所有关卡为已解锁
        for result in results:
            result.is_locked = False

        if results and boxes:
            locked_indices = scan_for_unlocked_stages(image, boxes, save_debug=logger_debug)
            if locked_indices:
                # 按X坐标排序boxes以匹配results顺序
                sorted_box_indices = sorted(range(len(boxes)), key=lambda i: boxes[i][0])

                # 标记锁定关卡（不过滤）
                for box_idx in locked_indices:
                    if box_idx < len(sorted_box_indices):
                        result_idx = sorted_box_indices.index(box_idx) if box_idx in sorted_box_indices else None
                        if result_idx is not None and result_idx < len(results):
                            # 动态添加 is_locked 属性
                            results[result_idx].is_locked = True
                            logger.info(f"[ForgottenHallStageOcr] Stage {results[result_idx].matched_keyword} is locked (marked, not filtered)")

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
    def insight_row(self, row: Keyword, main: ModuleBase, skip_first_screenshot=True, max_retries: int = 10) -> bool:
        """
        导航使指定关卡行可见

        Args:
            row: 目标关卡关键词
            main: 模块实例
            skip_first_screenshot: 是否跳过首次截图
            max_retries: 最大重试次数，防止无限循环

        Returns:
            bool: 关卡是否可见且可访问
        """
        retry_count = 0
        slide_count = 0
        max_slides = 5

        while retry_count < max_retries:
            result = super().insight_row(row, main=main, skip_first_screenshot=skip_first_screenshot)
            if not result:
                if row == KEYWORDS_FORGOTTEN_HALL_STAGE.Stage_1:
                    retry_count += 1
                    logger.warning(f'Stage_1 not found, retry {retry_count}/{max_retries}')
                    continue
                else:
                    return False

            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                main.device.screenshot()
            button = self.keyword2button(row)

            # end - 按钮完全可见
            if button.button[0] > 0:
                break

            # 关卡编号可见但按钮不可见，向左滑动
            slide_count += 1
            if slide_count > max_slides:
                logger.warning(f'Max slides ({max_slides}) reached, stopping')
                return False

            logger.info(f"Stage visible, swipe left ({slide_count}/{max_slides})")
            self.drag_vector = (0.2, 0.4)
            self.drag_page("left", main=main)
            self.drag_vector = DraggableList.drag_vector

        if retry_count >= max_retries:
            logger.error(f'Failed to find {row} after {max_retries} retries')
            return False

        return True

    def is_row_selected(self, button: OcrResultButton, main: ModuleBase) -> bool:
        return main.appear(ENTRANCE_CHECKED)

    def load_rows(self, main: ModuleBase):
        if main.appear(FORGOTTEN_HALL_CHECK) or main.appear(MEMORY_OF_CHAOS_CHECK) or main.appear(LAST_VASTIGES_CHECK):
            return super().load_rows(main=main)
        else:
            logger.info('Not in forgotten hall, skip load_rows()')
            return


STAGE_LIST = DraggableStageList("ForgottenHallStageList", keyword_class=ForgottenHallStage,
                                ocr_class=ForgottenHallStageOcr, search_button=OCR_STAGE,
                                check_row_order=False, drag_direction="right")


class ForgottenHallUI(DungeonUI, ForgottenHallTeam, MapControl):
    PURE_FICTION_DETECTION_AREA = (505, 187, 1214, 568)
    PURE_FICTION_STAGE_STAR_AREAS: dict[int, tuple[int, int, int, int]] = {
        1: (548, 420, 622, 444),
        2: (805, 225, 879, 249),
        3: (933, 540, 1007, 564),
        4: (1136, 353, 1211, 377),
    }
    PURE_FICTION_STAGE_LOCKED_TEXT_AREAS: dict[int, tuple[int, int, int, int]] = {
        2: (827, 224, 895, 253),
        3: (954, 539, 1022, 568),
        4: (1158, 353, 1226, 382),
    }
    PURE_FICTION_STAR_SEGMENTS = 3
    PURE_FICTION_STAR_MIN_PIXELS = 8
    PURE_FICTION_BUFF_OPTION_AREA = (543, 106, 1253, 633)
    PURE_FICTION_BUFF_OPTION_COUNT = 3

    APOCALYPTIC_SHADOW_STAGE_BUTTON_AREA = (177, 626, 1102, 662)
    APOCALYPTIC_SHADOW_STAGE_COUNT = 4

    @staticmethod
    def _area_center(area: tuple[int, int, int, int]) -> tuple[int, int]:
        x1, y1, x2, y2 = area
        return ((x1 + x2) // 2, (y1 + y2) // 2)

    @staticmethod
    def _point_in_area(point: tuple[int, int], area: tuple[int, int, int, int]) -> bool:
        x, y = point
        x1, y1, x2, y2 = area
        return x1 <= x <= x2 and y1 <= y <= y2

    @staticmethod
    def _split_area_horizontally(area: tuple[int, int, int, int], segments: int) -> list[tuple[int, int, int, int]]:
        x1, y1, x2, y2 = area
        if segments <= 0:
            return []

        total_w = x2 - x1
        base_w = total_w // segments
        remainder = total_w % segments

        areas: list[tuple[int, int, int, int]] = []
        cur_x = x1
        for i in range(segments):
            seg_w = base_w + (1 if i < remainder else 0)
            seg_x1 = cur_x
            seg_x2 = cur_x + seg_w
            areas.append((seg_x1, y1, seg_x2, y2))
            cur_x = seg_x2
        return areas

    @staticmethod
    def _split_area_vertically(area: tuple[int, int, int, int], segments: int) -> list[tuple[int, int, int, int]]:
        x1, y1, x2, y2 = area
        if segments <= 0:
            return []

        total_h = y2 - y1
        base_h = total_h // segments
        remainder = total_h % segments

        areas: list[tuple[int, int, int, int]] = []
        cur_y = y1
        for i in range(segments):
            seg_h = base_h + (1 if i < remainder else 0)
            seg_y1 = cur_y
            seg_y2 = cur_y + seg_h
            areas.append((x1, seg_y1, x2, seg_y2))
            cur_y = seg_y2
        return areas

    def _get_pure_fiction_buff_option_areas(self) -> dict[int, tuple[int, int, int, int]]:
        raw_areas = self._split_area_vertically(
            self.PURE_FICTION_BUFF_OPTION_AREA,
            self.PURE_FICTION_BUFF_OPTION_COUNT,
        )
        padded: dict[int, tuple[int, int, int, int]] = {}
        for idx, (x1, y1, x2, y2) in enumerate(raw_areas, start=1):
            pad_x = min(16, max(0, (x2 - x1) // 10))
            pad_y = min(16, max(0, (y2 - y1) // 10))
            padded[idx] = (x1 + pad_x, y1 + pad_y, x2 - pad_x, y2 - pad_y)
        return padded

    @staticmethod
    def _count_star_segments(mask: np.ndarray, segments: int, min_pixels: int) -> int:
        if mask.size == 0 or segments <= 0:
            return 0

        height, width = mask.shape[:2]
        if width <= 0 or height <= 0:
            return 0

        seg_w = max(1, width // segments)
        count = 0
        for idx in range(segments):
            seg_x1 = idx * seg_w
            seg_x2 = width if idx == segments - 1 else min(width, (idx + 1) * seg_w)
            if cv2.countNonZero(mask[:, seg_x1:seg_x2]) >= min_pixels:
                count += 1

        return min(count, segments)

    def pure_fiction_scan_stage_stars(self, image=None) -> dict[int, int]:
        """
        扫描虚构叙事（Pure Fiction）固定页面的四关黄星数量。

        仅在给定区域内检测黄星，并按每关固定星星区域统计。
        固定星位时不做连通域过滤，直接分三段统计黄星像素。
        """
        if image is None:
            self.device.screenshot()
            image = self.device.image

        lower_yellow = np.array([239, 184, 97], dtype=np.uint8)
        upper_yellow = np.array([255, 214, 127], dtype=np.uint8)

        x1, y1, x2, y2 = self.PURE_FICTION_DETECTION_AREA
        h, w = image.shape[:2]
        x1 = max(0, x1)
        y1 = max(0, y1)
        x2 = min(w, x2)
        y2 = min(h, y2)

        if x2 <= x1 or y2 <= y1:
            logger.warning('[PureFiction] Invalid detection area, falling back to 0 stars')
            return {stage_num: 0 for stage_num in self.PURE_FICTION_STAGE_STAR_AREAS}

        crop_img = image[y1:y2, x1:x2]
        yellow_mask = cv2.inRange(crop_img, lower_yellow, upper_yellow)
        stage_stars: dict[int, int] = {}

        for stage_num, area in self.PURE_FICTION_STAGE_STAR_AREAS.items():
            ax1, ay1, ax2, ay2 = area
            rx1 = max(0, ax1 - x1)
            ry1 = max(0, ay1 - y1)
            rx2 = min(yellow_mask.shape[1], ax2 - x1)
            ry2 = min(yellow_mask.shape[0], ay2 - y1)

            if rx2 <= rx1 or ry2 <= ry1:
                stage_stars[stage_num] = 0
                continue

            area_mask = yellow_mask[ry1:ry2, rx1:rx2]
            count = self._count_star_segments(
                area_mask,
                self.PURE_FICTION_STAR_SEGMENTS,
                self.PURE_FICTION_STAR_MIN_PIXELS,
            )
            stage_stars[stage_num] = count

        logger.info(f'[PureFiction] Stage stars: {stage_stars}')
        return stage_stars

    def pure_fiction_detect_locked_stages(self, image=None) -> set[int]:
        """
        检测虚构叙事各关卡是否显示“未解锁”（固定坐标）。

        Returns:
            set[int]: 被检测为锁定的关卡编号集合（2-4）
        """
        from module.ocr.models import TextSystem

        if image is None:
            self.device.screenshot()
            image = self.device.image

        ocr_model = TextSystem('zhs')
        locked: set[int] = set()
        for stage_num, area in self.PURE_FICTION_STAGE_LOCKED_TEXT_AREAS.items():
            if detect_unlocked_text(
                image,
                area,
                ocr_model=ocr_model,
                save_debug=logger_debug,
                debug_index=stage_num,
            ):
                locked.add(stage_num)

        if locked:
            logger.info(f'[PureFiction] Locked stages: {sorted(locked)}')
        return locked

    def pure_fiction_resolve_stage_num(self, prefer_stage_num: int, image=None) -> int:
        """
        从 prefer_stage_num 开始向下回退，返回当前可挑战的最高关卡编号（4→3→2→1）。
        """
        prefer_stage_num = int(prefer_stage_num)
        prefer_stage_num = min(max(prefer_stage_num, 1), 4)

        locked = self.pure_fiction_detect_locked_stages(image=image)
        for stage_num in range(prefer_stage_num, 1, -1):
            if stage_num not in locked:
                return stage_num
        return 1

    def pure_fiction_next_stage_to_challenge(self, image=None) -> tuple[int, dict[int, int]]:
        """
        选择虚构叙事下一关要挑战的关卡。

        规则（最高可挑战难度）：
        - 优先挑战第4关；若检测到“未解锁”，则回退到第3关
        - 依次类推回退到第2关/第1关
        """
        if image is None:
            self.device.screenshot()
            image = self.device.image

        stage_stars = self.pure_fiction_scan_stage_stars(image=image)
        locked = self.pure_fiction_detect_locked_stages(image=image)
        for stage_num in locked:
            stage_stars[stage_num] = -1

        if stage_stars.get(4, 0) > 0:
            return -1, stage_stars

        stage_num = self.pure_fiction_resolve_stage_num(4, image=image)
        return stage_num, stage_stars

    def pure_fiction_get_stage_star_count(self, stage_num: int, image=None) -> int:
        stage_stars = self.pure_fiction_scan_stage_stars(image=image)
        return stage_stars.get(stage_num, 0)

    def pure_fiction_select_stage(self, stage_num: int, skip_first_screenshot=True, timeout: float = 8.0) -> bool:
        """
        在虚构叙事固定页面点击指定关卡。

        当前使用每关星星区域中心点作为点击坐标，并等待 ENTRANCE_CHECKED。
        """
        from module.base.button import ClickButton

        if stage_num not in self.PURE_FICTION_STAGE_STAR_AREAS:
            logger.error(f'[PureFiction] Invalid stage: {stage_num}')
            return False

        x, y = self._area_center(self.PURE_FICTION_STAGE_STAR_AREAS[stage_num])
        click_button = ClickButton(
            area=(x - 4, y - 4, x + 4, y + 4),
            name=f'PureFictionStage_{stage_num}',
        )

        for attempt in range(1, 4):
            logger.info(f'[PureFiction] Select stage {stage_num} (attempt {attempt}/3)')

            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.handle_forgotten_hall_buff():
                continue

            self.device.click(click_button)

            wait = Timer(timeout).start()
            while not wait.reached():
                self.device.screenshot()
                if self.handle_forgotten_hall_buff():
                    continue
                if self.appear(ENTRANCE_CHECKED, interval=0.2):
                    logger.info(f'[PureFiction] Stage {stage_num} selected')
                    return True
                if self.appear(PURE_FICTION_TEAM_BUTTON, interval=0.2):
                    logger.info(f'[PureFiction] Stage {stage_num} selected (team button detected)')
                    return True
                if self.appear(PURE_FICTION_TEAM_TITLE, interval=0.2):
                    logger.info(f'[PureFiction] Stage {stage_num} selected (title detected)')
                    return True

        logger.error(f'[PureFiction] Failed to select stage {stage_num}')
        return False

    def _enter_pure_fiction_team_selection(self, skip_first_screenshot=True, timeout: float = 10.0) -> bool:
        """
        进入虚构叙事选队界面（点击“队伍”按钮），确保预设编队按钮可见。
        """
        logger.info('[PureFiction] Enter team selection')
        timer = Timer(timeout).start()
        interval = Timer(1.2)

        while not timer.reached():
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.handle_forgotten_hall_buff():
                continue

            if self.appear(PRESET_TEAM, interval=0.2):
                logger.info('[PureFiction] Team selection ready (preset button visible)')
                return True

            if self.appear(PURE_FICTION_TEAM_BUTTON, interval=0.2):
                if interval.reached():
                    logger.info('[PureFiction] Clicking team button')
                    self.device.click(PURE_FICTION_TEAM_BUTTON)
                    interval.reset()
                continue

            if self.appear(PURE_FICTION_TEAM_TITLE, interval=0.2):
                self.device.sleep(0.3)
                continue

            self.device.sleep(0.3)

        logger.warning('[PureFiction] Enter team selection timeout')
        return False

    def _wait_for_pure_fiction_buff_panel(self, skip_first_screenshot=True, timeout: float = 6.0) -> bool:
        timer = Timer(timeout).start()
        while not timer.reached():
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(PURE_FICTION_BUFF_APPLY, interval=0.2):
                return True

            self.device.sleep(0.2)

        return False

    def _select_pure_fiction_buff_option(self, buff_index: int) -> bool:
        from module.base.button import ClickButton

        areas = self._get_pure_fiction_buff_option_areas()
        area = areas.get(buff_index)
        if area is None:
            logger.error(f'[PureFiction] Invalid buff index: {buff_index}')
            return False

        x, y = self._area_center(area)
        click_button = ClickButton(
            area=(x - 6, y - 6, x + 6, y + 6),
            name=f'PureFictionBuff_{buff_index}',
        )
        logger.info(f'[PureFiction] Select buff option {buff_index}')
        self.device.click(click_button)
        self.device.sleep(0.3)
        return True

    def _click_pure_fiction_buff_apply(self, skip_first_screenshot=True, timeout: float = 6.0) -> bool:
        timer = Timer(timeout).start()
        while not timer.reached():
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(PURE_FICTION_BUFF_APPLY, interval=0.2):
                logger.info('[PureFiction] Click buff apply')
                self.device.click(PURE_FICTION_BUFF_APPLY)
                return True

            self.device.sleep(0.2)

        logger.warning('[PureFiction] Buff apply button not found')
        return False

    def _exit_pure_fiction_buff_panel(self, skip_first_screenshot=True, timeout: float = 6.0) -> bool:
        logger.info('[PureFiction] Exit buff panel')
        timer = Timer(timeout).start()
        while not timer.reached():
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if not self.appear(PURE_FICTION_BUFF_APPLY, interval=0.2):
                return True

            self.device.click(CLOSE)

            if (self.appear(PURE_FICTION_TEAM1_BUFF, interval=0.2)
                    or self.appear(PURE_FICTION_TEAM2_BUFF, interval=0.2)
                    or self.appear(PRESET_TEAM, interval=0.2)):
                return True

            self.device.sleep(0.2)

        logger.warning('[PureFiction] Exit buff panel timeout')
        return False

    def _select_pure_fiction_team_buff(self, team_index: int, buff_index: int, timeout: float = 8.0) -> bool:
        if buff_index <= 0:
            return True

        if team_index not in (1, 2):
            logger.error(f'[PureFiction] Invalid team index: {team_index}')
            return False

        if not self._enter_pure_fiction_team_selection(timeout=8.0):
            logger.warning('[PureFiction] Team selection not ready for buff selection')
            return False

        button = PURE_FICTION_TEAM1_BUFF if team_index == 1 else PURE_FICTION_TEAM2_BUFF
        logger.info(f'[PureFiction] Open buff panel for team {team_index}')

        panel_opened = False
        timer = Timer(timeout).start()
        interval = Timer(1.2)
        while not timer.reached():
            self.device.screenshot()

            if self.handle_forgotten_hall_buff():
                continue

            if self.appear(PURE_FICTION_BUFF_APPLY, interval=0.2):
                panel_opened = True
                break

            if self.appear(button, interval=0.2) and interval.reached():
                self.device.click(button)
                interval.reset()
                continue

            self.device.sleep(0.2)

        if not panel_opened:
            logger.warning(f'[PureFiction] Buff panel not opened for team {team_index}')
            return False

        if not self._select_pure_fiction_buff_option(buff_index):
            return False

        self._click_pure_fiction_buff_apply()
        self._exit_pure_fiction_buff_panel()
        return True

    def _configure_pure_fiction_buffs(self, team1_buff: int = None, team2_buff: int = None) -> bool:
        success = True
        if team1_buff:
            if not self._select_pure_fiction_team_buff(team_index=1, buff_index=team1_buff):
                success = False
        if team2_buff:
            if not self._select_pure_fiction_team_buff(team_index=2, buff_index=team2_buff):
                success = False
        return success

    def apocalyptic_shadow_get_stage_button_areas(self) -> dict[int, tuple[int, int, int, int]]:
        """
        末日幻影（Apocalyptic Shadow）底部 1-4 关按钮区域划分。

        用户给定总区域：area=(177, 626, 1102, 662)
        该区域按水平均分为 4 段，分别对应 1-4 关。
        """
        raw_areas = self._split_area_horizontally(
            self.APOCALYPTIC_SHADOW_STAGE_BUTTON_AREA,
            self.APOCALYPTIC_SHADOW_STAGE_COUNT,
        )
        areas: dict[int, tuple[int, int, int, int]] = {}
        for idx, (x1, y1, x2, y2) in enumerate(raw_areas, start=1):
            pad_x = min(8, max(0, (x2 - x1) // 6))
            pad_y = min(4, max(0, (y2 - y1) // 6))
            areas[idx] = (x1 + pad_x, y1 + pad_y, x2 - pad_x, y2 - pad_y)
        return areas

    def apocalyptic_shadow_select_stage(self, stage_num: int, skip_first_screenshot=True, timeout: float = 8.0) -> bool:
        """
        在末日幻影选关界面点击指定关卡（1-4）。

        使用底部按钮区域中心点作为点击坐标，并等待 ENTRANCE_CHECKED。
        """
        from module.base.button import ClickButton

        areas = self.apocalyptic_shadow_get_stage_button_areas()
        if stage_num not in areas:
            logger.error(f'[ApocalypticShadow] Invalid stage: {stage_num}')
            return False

        x, y = self._area_center(areas[stage_num])
        click_button = ClickButton(
            area=(x - 4, y - 4, x + 4, y + 4),
            name=f'ApocalypticShadowStage_{stage_num}',
        )

        for attempt in range(1, 4):
            logger.info(f'[ApocalypticShadow] Select stage {stage_num} (attempt {attempt}/3)')

            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.handle_forgotten_hall_buff():
                continue

            self.device.click(click_button)

            wait = Timer(timeout).start()
            while not wait.reached():
                self.device.screenshot()
                if self.handle_forgotten_hall_buff():
                    continue
                if self.appear(ENTRANCE_CHECKED, interval=0.2):
                    logger.info(f'[ApocalypticShadow] Stage {stage_num} selected')
                    return True

        logger.error(f'[ApocalypticShadow] Failed to select stage {stage_num}')
        return False

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

    def goto_stage_selection(self, dungeon: DungeonList):
        """
        只导航到深渊关卡选择界面，不选择任何关卡

        用于自动选关模式：进入后游戏会自动定格在最高可挑战关卡

        Args:
            dungeon: 深渊类型（Memory_of_Chaos 或 The_Last_Vestiges_of_Towering_Citadel）

        Returns:
            bool: 是否成功导航到选关界面
        """
        if self.appear(FORGOTTEN_HALL_CHECK):
            logger.info('Already in forgotten hall')
        else:
            self.ui_ensure(page_guide)
            from tools.forgotten_hall_navigator import TreasuresLightwardNavigator
            navigator = TreasuresLightwardNavigator()
            if not navigator.goto_forgotten_hall_from_guide(self.device):
                logger.error('Failed to navigate to Forgotten Hall')
                return False

        self.stage_choose(dungeon)
        return True

    def _wait_for_stage_list_loaded(self, timeout: float = 20.0, skip_first_screenshot=True) -> bool:
        """
        等待关卡列表加载完成（逐光捡金：虚构叙事 / 末日幻影也会复用同一套关卡列表OCR）

        Returns:
            bool: 是否在超时内加载成功
        """
        timeout_timer = Timer(timeout).start()
        while not timeout_timer.reached():
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.handle_forgotten_hall_buff():
                continue

            # 仍在外部界面时可能会看到传送按钮，补点击一次
            if self.appear_then_click(TELEPORT, interval=2):
                continue

            if self.appear(FORGOTTEN_HALL_CHECK):
                STAGE_LIST.load_rows(main=self)
                if STAGE_LIST.cur_buttons:
                    return True

            self.device.sleep(0.3)

        logger.warning('Wait stage list loaded timeout')
        return False

    def _wait_for_apocalyptic_shadow_loaded(self, timeout: float = 20.0, skip_first_screenshot=True) -> bool:
        """
        等待末日幻影选关界面加载完成（通过“前往挑战”按钮判断）。

        Returns:
            bool: 是否在超时内加载成功
        """
        from tasks.forgotten_hall.assets.assets_apocalyptic_shadow_ui import APOCALYPTIC_SHADOW_GOTO_CHALLENGE

        timeout_timer = Timer(timeout).start()
        while not timeout_timer.reached():
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.handle_forgotten_hall_buff():
                continue

            if self.appear_then_click(TELEPORT, interval=2):
                continue

            if self.match_template_color(APOCALYPTIC_SHADOW_GOTO_CHALLENGE, interval=0.5):
                return True

            self.device.sleep(0.3)

        logger.warning('Wait apocalyptic shadow loaded timeout')
        return False

    def goto_stage_selection_by_dungeon_type(self, dungeon_type: str) -> bool:
        """
        根据配置中的 DungeonType/DungeonTypes 导航到对应模式的关卡选择界面

        Args:
            dungeon_type: Memory_of_Chaos / The_Last_Vestiges_of_Towering_Citadel / Pure_Fiction / Apocalyptic_Shadow
        """
        if dungeon_type == 'Memory_of_Chaos':
            return self.goto_stage_selection(KEYWORDS_DUNGEON_LIST.Memory_of_Chaos)
        if dungeon_type == 'The_Last_Vestiges_of_Towering_Citadel':
            return self.goto_stage_selection(KEYWORDS_DUNGEON_LIST.The_Last_Vestiges_of_Towering_Citadel)

        if dungeon_type in ('Pure_Fiction', 'Apocalyptic_Shadow'):
            self.ui_ensure(page_guide)
            from tools.forgotten_hall_navigator import TreasuresLightwardNavigator

            navigator = TreasuresLightwardNavigator()
            if dungeon_type == 'Pure_Fiction':
                if not navigator.goto_pure_fiction_from_guide(self.device):
                    logger.error('Failed to navigate to Pure Fiction via Treasures Lightward')
                    return False
            else:
                if not navigator.goto_apocalyptic_shadow_from_guide(self.device):
                    logger.error('Failed to navigate to Apocalyptic Shadow via Treasures Lightward')
                    return False

            if dungeon_type == 'Pure_Fiction':
                # 虚构叙事为固定页面，不依赖 STAGE_LIST OCR
                self.device.sleep(1.0)
                return True

            if dungeon_type == 'Apocalyptic_Shadow':
                if not self._wait_for_apocalyptic_shadow_loaded(timeout=20.0, skip_first_screenshot=True):
                    logger.error('Failed to load apocalyptic shadow stage selection after navigation')
                    return False
                return True

            if not self._wait_for_stage_list_loaded(timeout=20.0, skip_first_screenshot=True):
                logger.error('Failed to load stage list after navigation')
                return False
            return True

        logger.error(f'Unknown dungeon type: {dungeon_type}')
        return False

    def stage_goto_by_dungeon_type(
        self,
        dungeon_type: str,
        stage_keyword: ForgottenHallStage,
        team1_preset: int = None,
        team2_preset: int = None,
        team1_buff: int = None,
        team2_buff: int = None,
    ) -> bool:
        """
        根据 dungeon_type 导航到指定关卡并配置预设编队
        """
        if dungeon_type == 'Memory_of_Chaos':
            return self.stage_goto(
                KEYWORDS_DUNGEON_LIST.Memory_of_Chaos,
                stage_keyword,
                team1_preset=team1_preset,
                team2_preset=team2_preset,
            )
        if dungeon_type == 'The_Last_Vestiges_of_Towering_Citadel':
            return self.stage_goto(
                KEYWORDS_DUNGEON_LIST.The_Last_Vestiges_of_Towering_Citadel,
                stage_keyword,
                team1_preset=team1_preset,
                team2_preset=team2_preset,
            )

        if dungeon_type in ('Pure_Fiction', 'Apocalyptic_Shadow'):
            if not self.goto_stage_selection_by_dungeon_type(dungeon_type):
                return False

            if dungeon_type == 'Pure_Fiction':
                stage_num = self.pure_fiction_resolve_stage_num(stage_keyword.id)
                logger.info(f'[PureFiction] Select stage: {stage_num}')
                if not self.pure_fiction_select_stage(stage_num):
                    return False
            elif dungeon_type == 'Apocalyptic_Shadow':
                stage_num = stage_keyword.id
                logger.info(f'[ApocalypticShadow] Select stage: {stage_num}')
                if not self.apocalyptic_shadow_select_stage(stage_num):
                    return False
            else:
                logger.info(f'Stage list select: {stage_keyword}')
                STAGE_LIST.select_row(stage_keyword, main=self)

            if team1_preset or team2_preset:
                logger.hr('Configure preset teams', level=1)
                if dungeon_type == 'Pure_Fiction':
                    if not self._enter_pure_fiction_team_selection(timeout=12):
                        logger.warning('[PureFiction] Team selection entry may have failed, continuing...')
                self._click_preset_team(timeout=15)
                self._configure_preset_teams(team1_preset, team2_preset)
                logger.info('Preset teams configuration completed')

            if dungeon_type == 'Pure_Fiction' and (team1_buff or team2_buff):
                logger.hr('Configure buffs', level=1)
                if not self._configure_pure_fiction_buffs(team1_buff=team1_buff, team2_buff=team2_buff):
                    logger.warning('[PureFiction] Buff configuration may have failed, continuing...')

            return True

        logger.error(f'Unknown dungeon type: {dungeon_type}')
        return False

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
        if dungeon == KEYWORDS_DUNGEON_LIST.Memory_of_Chaos and stage_keyword.id > 12:
            logger.error(f'This dungeon "{dungeon}" does not have stage that greater than 12. '
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
        from tasks.forgotten_hall.assets.assets_forgotten_hall_ui import (
            QUICK_COMPLETE_TITLE, QUICK_COMPLETE_CONFIRM
        )

        logger.hr('Handle battle success', level=2)
        timeout = Timer(15).start()

        while not timeout.reached():
            self.device.screenshot()

            if self.appear(FORGOTTEN_HALL_CHECK):
                logger.info('Battle success handled, returned to forgotten hall')
                return True

            # 处理快速通关弹窗（3星通关时前置关卡奖励解锁提示）
            if self.appear(QUICK_COMPLETE_TITLE, interval=2):
                logger.info('Quick complete popup detected, clicking confirm')
                self.device.click(QUICK_COMPLETE_CONFIRM)
                continue

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

    def _click_enter_dungeon(self, skip_first_screenshot=True):
        """
        Click enter button to enter forgotten hall dungeon (without combat execution)

        This method only handles entering the dungeon itself, not the combat.
        For full dungeon entry with combat, use enter_forgotten_hall_dungeon() instead.

        Args:
            skip_first_screenshot: Whether to skip first screenshot

        Pages:
            in: ENTRANCE_CHECKED, ENTER_FORGOTTEN_HALL_DUNGEON
            out: In dungeon (BUFF_Forgotten_Hall appears)
        """
        from tasks.base.assets.assets_base_popup import BUFF_Forgotten_Hall
        from tasks.forgotten_hall.assets.assets_forgotten_hall_ui import (
            DUNGEON_ENTER_CHECKED,
            ENTER_FORGOTTEN_HALL_DUNGEON
        )

        logger.info('Entering forgotten hall dungeon')
        interval = Timer(3)
        timeout = Timer(3)

        while True:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # Success: entered dungeon (BUFF appears)
            if self.appear(BUFF_Forgotten_Hall):
                logger.info('Successfully entered dungeon')
                break

            # Check enter button status
            if self.match_template_color(DUNGEON_ENTER_CHECKED):
                if timeout.reached():
                    logger.info('Wait dungeon BUFF_Forgotten_Hall timeout')
                    break
            else:
                timeout.reset()

            # Click enter button when ready
            if interval.reached() and self.team_prepared():
                self.device.click(ENTER_FORGOTTEN_HALL_DUNGEON)
                interval.reset()

    def enter_forgotten_hall_dungeon(self, skip_first_screenshot=True):
        """
        Enter forgotten hall dungeon and execute combat (standard SRC pattern)

        This is a convenience method that combines entering the dungeon
        and executing combat. For more control, use _click_enter_dungeon()
        and combat_execute() separately.

        Pages:
            in: ENTRANCE_CHECKED, ENTER_FORGOTTEN_HALL_DUNGEON
            out: page_main, in forgotten hall map
        """
        # Step 1: Enter dungeon
        self._click_enter_dungeon(skip_first_screenshot=skip_first_screenshot)

        # Step 2: Auto engage enemy
        logger.info('Dungeon entered, starting auto engage enemy')
        success = self.auto_engage_enemy(move_duration=8, timeout=15)

        if not success:
            logger.warning('Failed to auto-engage enemy')
            return

        # Step 3: Execute combat with standard battle end detection
        logger.info('Successfully engaged enemy, executing combat')

        from tasks.combat.assets.assets_combat_finish import COMBAT_AGAIN
        from tasks.forgotten_hall.assets.assets_forgotten_hall_ui import (
            BATTLE_FAILED,
            RETURN_TO_FORGOTTEN_HALL
        )
        from tasks.base.assets.assets_base_page import FORGOTTEN_HALL_CHECK

        def is_battle_end():
            """Check if battle has ended (success or failure)"""
            # Clear stuck record periodically (SRC standard pattern)
            if not hasattr(self, '_battle_end_stuck_timer'):
                self._battle_end_stuck_timer = Timer(10).start()

            if self._battle_end_stuck_timer.reached():
                logger.info('[is_battle_end] Clear stuck record (10s interval)')
                self.device.stuck_record_clear()
                self._battle_end_stuck_timer.reset()

            # Check all end conditions
            if self.appear(BATTLE_FAILED, interval=0.5):
                logger.info('[is_battle_end] BATTLE_FAILED detected')
                return True

            if self.appear(RETURN_TO_FORGOTTEN_HALL, interval=0.5):
                logger.info('[is_battle_end] RETURN_TO_FORGOTTEN_HALL detected')
                return True

            if self.appear(COMBAT_AGAIN, interval=0.5):
                logger.info('[is_battle_end] COMBAT_AGAIN detected')
                return True

            if self.appear(FORGOTTEN_HALL_CHECK, interval=0.5):
                logger.info('[is_battle_end] FORGOTTEN_HALL_CHECK detected')
                return True

            return False

        self.combat_execute(expected_end=is_battle_end)

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
                        # 跳过未解锁的关卡
                        if getattr(button, 'is_locked', False):
                            logger.info(f'Stage {stage_num}: locked (skipped)')
                            scanned_stages.add(stage_num)
                            stage_stars[stage_num] = -1  # 标记为未解锁
                            new_stages_found = True
                            continue

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

    def detect_current_highest_stage(
        self,
        max_stage: int = 12,
        target_stars: int = 3,
        dungeon_type: str | None = None,
    ) -> tuple:
        """
        从当前可见区域检测最高可挑战关卡（不滑动）

        游戏进入选关页面时自动定格在最高解锁关卡，直接识别即可

        Args:
            max_stage: 最大关卡数（混沌回忆=12, 忘却之庭=15）
            target_stars: 目标星数（默认3）

        Returns:
            tuple[int, dict]: (起始关卡, {关卡号: 星数})
            起始关卡为-1表示全部完成
        """
        logger.hr('Detect current highest stage', level=2)
        stage_stars = {}

        if dungeon_type == 'Pure_Fiction':
            self.device.screenshot()
            image = self.device.image

            stage_stars = self.pure_fiction_scan_stage_stars(image=image)
            locked = self.pure_fiction_detect_locked_stages(image=image)
            for stage_num in locked:
                stage_stars[stage_num] = -1

            highest_unlocked = max(
                (stage_num for stage_num in range(1, max_stage + 1) if stage_stars.get(stage_num, 0) != -1),
                default=0,
            )

            logger.info(f'[PureFiction] Visible stages: {stage_stars}, Highest: {highest_unlocked}')

            if highest_unlocked <= 0:
                logger.warning('[PureFiction] No stages detected in current view')
                return (1, stage_stars)

            # 若所有可挑战的关卡都已达标，则认为完成
            for stage_num in range(highest_unlocked, 0, -1):
                stars = stage_stars.get(stage_num, 0)
                if stars >= 0 and stars < target_stars:
                    logger.info(f'[PureFiction] Starting stage: {stage_num} ({stars} stars, target: {target_stars})')
                    return (stage_num, stage_stars)

            return (-1, stage_stars)

        self.device.screenshot()
        STAGE_LIST.load_rows(main=self)

        highest_unlocked = 0
        for button in STAGE_LIST.cur_buttons:
            if not button.matched_keyword:
                continue

            stage_num = button.matched_keyword.id
            if stage_num > max_stage:
                continue

            if getattr(button, 'is_locked', False):
                stage_stars[stage_num] = -1
                continue

            star_count = button.star_count if button.star_count is not None else 0
            stage_stars[stage_num] = star_count
            logger.info(f'Stage {stage_num}: {star_count} stars')

            if stage_num > highest_unlocked:
                highest_unlocked = stage_num

        logger.info(f'Visible stages: {stage_stars}, Highest: {highest_unlocked}')

        # 判断起始关卡
        if not stage_stars:
            logger.warning('No stages detected in current view')
            return (1, {})

        if highest_unlocked == max_stage and stage_stars.get(max_stage, 0) >= target_stars:
            logger.info(f'Stage {max_stage} already has {target_stars}+ stars, task complete')
            return (-1, stage_stars)

        # 找最高的未达标关卡
        for stage_num in sorted(stage_stars.keys(), reverse=True):
            stars = stage_stars[stage_num]
            if stars >= 0 and stars < target_stars:
                logger.info(f'Starting stage: {stage_num} ({stars} stars, target: {target_stars})')
                return (stage_num, stage_stars)

        # 所有可见关卡已完成，往右滑动找更高关卡
        if highest_unlocked < max_stage:
            logger.info(f'All visible stages completed, scrolling right to find higher stages...')
            next_stage = highest_unlocked + 1
            if next_stage <= max_stage:
                next_stage_keyword = getattr(KEYWORDS_FORGOTTEN_HALL_STAGE, f'Stage_{next_stage}')
                STAGE_LIST.insight_row(next_stage_keyword, main=self)
                # 递归检测
                return self.detect_current_highest_stage(max_stage, target_stars, dungeon_type=dungeon_type)

        return (-1, stage_stars)

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

            # 跳过未解锁关卡（星数为-1）
            if stars == -1:
                logger.debug(f'Stage {stage} is locked, skipping')
                continue

            if stars < target_stars:
                # 检查是否解锁（前一关有星数>=0 或是第1关）
                prev_stars = stage_stars.get(stage - 1, 0)
                if stage == 1 or (prev_stars >= 0 and prev_stars > 0):
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

    def check_and_claim_rewards(self, skip_first_screenshot=True) -> bool:
        """
        检测并领取深渊奖励

        在关卡选择界面检测右下角的奖励提示，存在则点击进入并领取

        Returns:
            bool: 是否成功领取了奖励

        Pages:
            in: FORGOTTEN_HALL_CHECK (关卡选择界面)
            out: FORGOTTEN_HALL_CHECK (关卡选择界面)
        """
        from tasks.forgotten_hall.assets.assets_forgotten_hall_ui import (
            REWARD_INDICATOR, REWARD_CLAIM_BUTTON, REWARD_EXIT
        )

        logger.hr('Check rewards', level=2)

        if not skip_first_screenshot:
            self.device.screenshot()

        # 检测奖励提示按钮
        if not self.appear(REWARD_INDICATOR):
            logger.info('No reward indicator found')
            return False

        logger.info('Reward indicator detected, claiming rewards...')

        # 点击奖励提示进入奖励界面
        self.device.click(REWARD_INDICATOR)
        self.device.sleep(1.0)

        # 等待奖励界面加载并领取
        timeout = Timer(15).start()
        claimed = False

        while not timeout.reached():
            self.device.screenshot()

            # 检测领取按钮
            if self.appear(REWARD_CLAIM_BUTTON, interval=1):
                logger.info('Claiming reward...')
                self.device.click(REWARD_CLAIM_BUTTON)
                claimed = True
                self.device.sleep(0.5)
                continue

            # 处理领取后的弹窗
            if self.handle_reward(interval=2):
                continue

            if self.handle_popup_confirm():
                continue

            if self.handle_popup_single():
                continue

            # 如果回到了关卡选择界面，说明领取完成
            if self.appear(FORGOTTEN_HALL_CHECK):
                if claimed:
                    logger.info('Rewards claimed successfully')
                break

            # 点击退出按钮返回深渊界面
            if self.appear(REWARD_EXIT, interval=2):
                logger.info('Clicking exit button to return to forgotten hall')
                self.device.click(REWARD_EXIT)
                self.device.sleep(0.5)
                continue

        return claimed
