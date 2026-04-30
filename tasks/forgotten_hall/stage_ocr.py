import cv2
import numpy as np
import os
import time
from pponnxcr.predict_system import BoxedResult

from module.base.base import ModuleBase
from module.base.timer import Timer
from module.base.utils import crop, save_image
from module.logger.logger import logger, logger_debug
from module.ocr.keyword import Keyword
from module.ocr.ocr import Ocr, OcrResultButton
from module.ui.draggable_list import DraggableList
from tasks.base.assets.assets_base_page import FORGOTTEN_HALL_CHECK
from tasks.forgotten_hall.assets.assets_forgotten_hall_nav import LAST_VASTIGES_CHECK, MEMORY_OF_CHAOS_CHECK
from tasks.forgotten_hall.assets.assets_forgotten_hall_ui import ENTRANCE_CHECKED, OCR_STAGE
from tasks.forgotten_hall.keywords import ForgottenHallStage, KEYWORDS_FORGOTTEN_HALL_STAGE

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


def mark_locked_stage_buttons(image, buttons, save_debug=False, ocr_model=None):
    """
    Mark locked stages directly on final OCR buttons.

    This intentionally uses each matched stage button's own area instead of raw
    OCR box indexes, because non-stage OCR noise can be filtered before buttons
    are consumed by auto-selection.
    """
    if not buttons:
        return []

    from module.ocr.models import TextSystem

    if ocr_model is None:
        ocr_model = TextSystem('zhs')

    locked_stage_ids = []
    for button in buttons:
        button.is_locked = False

        stage = getattr(button, 'matched_keyword', None)
        if stage is None:
            continue

        x1, y1, x2, y2 = button.area
        center_x = (x1 + x2) // 2
        search_area = (
            center_x - 40,
            y2,
            center_x + 40,
            y2 + 20,
        )

        stage_id = getattr(stage, 'id', None)
        debug_index = stage_id if stage_id is not None else len(locked_stage_ids)
        if detect_unlocked_text(
            image,
            search_area,
            ocr_model=ocr_model,
            save_debug=save_debug,
            debug_index=debug_index,
        ):
            button.is_locked = True
            locked_stage_ids.append(stage_id)
            logger.info(f"[ForgottenHallStageOcr] Stage {stage} is locked (marked, not filtered)")

    if locked_stage_ids:
        logger.info(f"[ForgottenHallStageOcr] Found {len(locked_stage_ids)} locked stages: {locked_stage_ids}")

    return locked_stage_ids


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

        ocr_text = getattr(boxed_result, 'ocr_text', getattr(boxed_result, 'text', ''))
        if not hasattr(boxed_result, 'ocr_text'):
            boxed_result.ocr_text = ocr_text

        matched_keyword = self._match_result(
            ocr_text,
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
        mark_locked_stage_buttons(image, results, save_debug=logger_debug)

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
    def select_row(
            self,
            row: Keyword,
            main: ModuleBase,
            insight=True,
            skip_first_screenshot=True,
            timeout: float = 20.0
    ):
        return super().select_row(
            row=row,
            main=main,
            insight=insight,
            skip_first_screenshot=skip_first_screenshot,
            timeout=timeout,
        )

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
