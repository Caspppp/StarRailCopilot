"""
使用真实的OCR结果测试星级检测
"""

import cv2
import sys
sys.path.insert(0, '/Users/yexili/Desktop/Projects/StarRailCopilot-new')

from tasks.forgotten_hall.ui import ForgottenHallStageOcr
from tasks.forgotten_hall.assets.assets_forgotten_hall_ui import OCR_STAGE
from tasks.forgotten_hall.keywords.stage import ForgottenHallStage
from star_detector import detect_yellow_stars, cluster_stars_by_proximity, match_stars_to_stages

# 加载测试图像
image = cv2.imread("screenshots/templates/template_20251229_233656.png")

print("[使用真实OCR测试星级检测]\n")

# 步骤1：使用OCR识别关卡数字
print("[步骤1] OCR识别关卡数字...")
ocr = ForgottenHallStageOcr(OCR_STAGE)
stage_boxes = ocr._find_number(image)

print(f"检测到 {len(stage_boxes)} 个关卡数字框:")
for idx, box in enumerate(stage_boxes):
    x1, y1, x2, y2 = box
    center_x = (x1 + x2) // 2
    center_y = (y1 + y2) // 2
    print(f"  关卡 {idx+1}: 框=({x1},{y1})-({x2},{y2}), 中心=({center_x},{center_y})")

# 步骤2：检测黄色星星
print(f"\n[步骤2] 检测黄色星星...")
star_regions = detect_yellow_stars(image)
print(f"找到 {len(star_regions)} 个黄色星星")

# 步骤3：聚类星星
print(f"\n[步骤3] 聚类临近星星...")
star_clusters = cluster_stars_by_proximity(star_regions)
print(f"聚类为 {len(star_clusters)} 组")

for idx, cluster in enumerate(star_clusters):
    print(f"  组 {idx+1}: {cluster['count']} 个星星, 中心X={cluster['center_x']}")

# 步骤4：匹配星星到关卡
print(f"\n[步骤4] 匹配星星到关卡...")
stage_star_map = match_stars_to_stages(star_clusters, stage_boxes)

print(f"\n关卡星级映射: {stage_star_map}")
print(f"\n关卡星级详情:")
for stage_idx, star_count in sorted(stage_star_map.items()):
    if stage_idx < len(stage_boxes):
        box = stage_boxes[stage_idx]
        center_x = (box[0] + box[2]) // 2
        status = "已完成" if star_count == 3 else "未完成"
        print(f"  关卡索引{stage_idx}: {star_count} 星 ({status}), 关卡框中心X={center_x}")

# 可视化
vis = image.copy()

# 绘制关卡框
for idx, box in enumerate(stage_boxes):
    x1, y1, x2, y2 = box
    star_count = stage_star_map.get(idx, 0)
    color = (0, 255, 0) if star_count == 3 else (128, 128, 128)
    cv2.rectangle(vis, (x1, y1), (x2, y2), color, 2)
    cv2.putText(vis, f"{star_count}*", (x1, y1-5),
               cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)

# 绘制星星
for star in star_regions:
    x1, y1, x2, y2 = star['bbox']
    cv2.rectangle(vis, (x1, y1), (x2, y2), (0, 255, 255), 1)

# 绘制聚类
for cluster in star_clusters:
    center_x = cluster['center_x']
    y_center = cluster['y_center']
    cv2.circle(vis, (center_x, y_center), 5, (255, 0, 0), -1)
    cv2.putText(vis, f"{cluster['count']}", (center_x + 10, y_center),
               cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 0), 2)

cv2.imwrite("tools/forgotten_hall_star_detector/debug/test_with_real_ocr.png", vis)
print(f"\n可视化已保存: debug/test_with_real_ocr.png")

# 验证
print(f"\n[验证结果]")
if len(star_regions) == 3:
    print(f"✓ 检测到3个星星")
else:
    print(f"❌ 星星数量不对: {len(star_regions)} != 3")

if len(star_clusters) == 1 and star_clusters[0]['count'] == 3:
    print(f"✓ 正确聚类为1组3星")
else:
    print(f"❌ 聚类不对")

# 找到有3星的关卡
three_star_stages = [idx for idx, count in stage_star_map.items() if count == 3]
if len(three_star_stages) == 1:
    print(f"✓ 检测到1个已完成关卡（索引{three_star_stages[0]}）")
else:
    print(f"❌ 已完成关卡数量不对: {len(three_star_stages)}")
