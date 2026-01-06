"""
调试星星匹配过程
"""

import cv2
import sys
sys.path.insert(0, '/Users/yexili/Desktop/Projects/StarRailCopilot-new')

from tools.forgotten_hall_star_detector.star_detector import (
    detect_yellow_stars,
    cluster_stars_by_proximity
)
from tasks.forgotten_hall.ui import ForgottenHallStageOcr
from tasks.forgotten_hall.assets.assets_forgotten_hall_ui import OCR_STAGE

# 加载测试图像
image = cv2.imread("screenshots/templates/template_20251229_233656.png")

# 检测关卡数字
ocr = ForgottenHallStageOcr(OCR_STAGE)
stage_boxes = ocr._find_number(image)

# 检测星星
star_regions = detect_yellow_stars(image)
star_clusters = cluster_stars_by_proximity(star_regions)

print(f"星星聚类信息:")
for idx, cluster in enumerate(star_clusters):
    print(f"  聚类{idx}: 中心=({cluster['center_x']}, {cluster['y_center']}), 星数={cluster['count']}")

print(f"\n关卡框信息:")
for idx, box in enumerate(stage_boxes):
    x1, y1, x2, y2 = box
    center_x = (x1 + x2) // 2
    print(f"  框{idx}: 中心X={center_x}, Y范围=({y1},{y2})")

print(f"\n匹配过程分析:")
for cluster_idx, cluster in enumerate(star_clusters):
    cluster_x = cluster['center_x']
    cluster_y = cluster['y_center']

    print(f"\n聚类{cluster_idx} (X={cluster_x}, Y={cluster_y}):")

    for stage_idx, box in enumerate(stage_boxes):
        x1, y1, x2, y2 = box
        center_x = (x1 + x2) // 2

        x_distance = abs(cluster_x - center_x)
        y_relation = "下方" if cluster_y > y2 else ("上方" if cluster_y < y1 else "范围内")

        # 检查Y坐标条件
        y_check = "跳过" if cluster_y < y1 - 50 else "通过"

        print(f"  框{stage_idx}: X距离={x_distance}px, 星星在框{y_relation}, Y检查={y_check}")
