"""
Star Rating Detector for Forgotten Hall

检测深渊挑战关卡界面的星级（完成状态）
"""

import cv2
import numpy as np
from typing import List, Dict, Tuple, Optional


def detect_yellow_stars(image: np.ndarray, search_area: Optional[Tuple[int, int, int, int]] = None) -> List[Dict]:
    """
    检测图像中的黄色星星

    Args:
        image: BGR格式的图像
        search_area: 搜索区域 (x1, y1, x2, y2)，默认为 (100, 200, 1180, 300)

    Returns:
        星星区域列表，每个元素包含:
            - center: (x, y) 中心坐标
            - bbox: (x1, y1, x2, y2) 边界框
            - pixel_count: 像素数量
            - area: 连通区域面积
    """
    if search_area is None:
        # 默认搜索区域：复用 OCR_STAGE.area，覆盖所有关卡数字和星星
        # OCR_STAGE.area = (0, 281, 1280, 581)
        search_area = (0, 281, 1280, 581)

    x1, y1, x2, y2 = search_area

    # 边界检查
    h, w = image.shape[:2]
    x1 = max(0, x1)
    y1 = max(0, y1)
    x2 = min(w, x2)
    y2 = min(h, y2)

    # 裁剪搜索区域
    crop_img = image[y1:y2, x1:x2]

    # 颜色提取：目标颜色 RGB(254, 199, 112)
    # 注意：self.device.image 是 RGB 格式（不是 BGR）！
    # 参考：.claude/COLOR_FORMAT_STANDARD.md
    # 容差 ±15 适应光照变化
    lower_yellow = np.array([239, 184, 97], dtype=np.uint8)   # RGB(254-15, 199-15, 112-15)
    upper_yellow = np.array([255, 214, 127], dtype=np.uint8)  # RGB(254+15, 199+15, 112+15)
    mask = cv2.inRange(crop_img, lower_yellow, upper_yellow)

    # 形态学降噪：开运算（先腐蚀后膨胀）
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

    # 连通组件分析
    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)

    star_regions = []

    for i in range(1, num_labels):  # 跳过背景 (0)
        area = stats[i, cv2.CC_STAT_AREA]

        # 过滤：像素数 > 40（用户指定的阈值）
        if area > 40:
            x = stats[i, cv2.CC_STAT_LEFT]
            y = stats[i, cv2.CC_STAT_TOP]
            w = stats[i, cv2.CC_STAT_WIDTH]
            h = stats[i, cv2.CC_STAT_HEIGHT]

            # 转换为绝对坐标
            abs_x = x + x1
            abs_y = y + y1

            star_regions.append({
                'center': (abs_x + w // 2, abs_y + h // 2),
                'bbox': (abs_x, abs_y, abs_x + w, abs_y + h),
                'pixel_count': area,
                'area': area
            })

    return star_regions


def cluster_stars_by_proximity(star_regions: List[Dict], max_horizontal_gap: int = 100) -> List[Dict]:
    """
    将临近的星星聚类（属于同一关卡）

    Args:
        star_regions: detect_yellow_stars() 返回的星星区域列表
        max_horizontal_gap: 同组星星最大X间距（像素），默认100

    Returns:
        聚类列表，每个元素包含:
            - stars: 星星列表
            - count: 星星数量
            - x_min, x_max: 水平范围
            - y_center: 平均Y坐标
            - center_x: 聚类中心X坐标
    """
    if not star_regions:
        return []

    # 按 X 坐标排序
    sorted_stars = sorted(star_regions, key=lambda s: s['center'][0])

    clusters = []
    current_cluster = [sorted_stars[0]]

    for star in sorted_stars[1:]:
        # 计算与当前聚类最后一个星星的X间距
        last_star_x = current_cluster[-1]['center'][0]
        current_star_x = star['center'][0]
        gap = current_star_x - last_star_x

        if gap < max_horizontal_gap:
            # 加入当前聚类
            current_cluster.append(star)
        else:
            # 开始新聚类
            if 1 <= len(current_cluster) <= 3:
                clusters.append(current_cluster)
            current_cluster = [star]

    # 添加最后一个聚类
    if 1 <= len(current_cluster) <= 3:
        clusters.append(current_cluster)

    # 计算聚类统计信息
    cluster_info = []
    for cluster in clusters:
        x_coords = [s['center'][0] for s in cluster]
        y_coords = [s['center'][1] for s in cluster]

        cluster_info.append({
            'stars': cluster,
            'count': len(cluster),
            'x_min': min(x_coords),
            'x_max': max(x_coords),
            'y_center': int(np.mean(y_coords)),
            'center_x': int(np.mean(x_coords))
        })

    return cluster_info


def match_stars_to_stages(star_clusters: List[Dict], stage_boxes: List[Tuple[int, int, int, int]]) -> Dict[int, int]:
    """
    将星星聚类匹配到关卡数字

    Args:
        star_clusters: cluster_stars_by_proximity() 返回的聚类列表
        stage_boxes: 关卡数字的边界框列表 (x1, y1, x2, y2)

    Returns:
        关卡索引 → 星星数量的映射字典
        例如: {0: 3, 1: 3, 2: 3, 3: 0, 4: 0}
    """
    stage_star_map = {}

    # 计算每个关卡框的中心X坐标和Y范围
    stage_centers = []
    for idx, box in enumerate(stage_boxes):
        x1, y1, x2, y2 = box
        center_x = (x1 + x2) // 2
        stage_centers.append((idx, center_x, y1, y2))

    # 初始化所有关卡为0星
    for idx, _, _, _ in stage_centers:
        stage_star_map[idx] = 0

    # 为每个聚类找到最近的关卡
    matched_stages = {}  # stage_idx -> star_count

    for cluster in star_clusters:
        cluster_x = cluster['center_x']
        cluster_y = cluster['y_center']

        # 找到X坐标最接近且星星在数字下方的关卡
        min_distance = float('inf')
        best_stage_idx = None

        for stage_idx, stage_x, stage_y1, stage_y2 in stage_centers:
            # 星星应该在数字下方（Y坐标更大）
            # 允许一定的容差，因为有些情况星星可能略高于数字底部
            if cluster_y < stage_y1 - 50:  # 星星明显在数字上方，跳过
                continue

            distance = abs(cluster_x - stage_x)
            if distance < min_distance:
                min_distance = distance
                best_stage_idx = stage_idx

        # 如果距离在容差范围内（80px），匹配成功
        if min_distance < 80 and best_stage_idx is not None:
            # 如果同一个关卡已经匹配过，保留星数更多的
            if best_stage_idx in matched_stages:
                matched_stages[best_stage_idx] = max(matched_stages[best_stage_idx], cluster['count'])
            else:
                matched_stages[best_stage_idx] = cluster['count']

    # 更新映射表
    stage_star_map.update(matched_stages)

    return stage_star_map
