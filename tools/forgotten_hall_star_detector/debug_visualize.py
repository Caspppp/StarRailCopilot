"""
可视化检测到的黄色区域
"""

import cv2
import numpy as np

# 加载图像
image = cv2.imread("screenshots/templates/template_20251229_233656.png")
h, w = image.shape[:2]

# 使用相同的颜色范围
lower_yellow = np.array([97, 184, 239], dtype=np.uint8)
upper_yellow = np.array([127, 214, 255], dtype=np.uint8)
mask = cv2.inRange(image, lower_yellow, upper_yellow)

# 形态学降噪
kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
mask_clean = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

# 连通组件分析
num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(mask_clean, connectivity=8)

# 可视化
vis_image = image.copy()

print(f"总共检测到 {num_labels-1} 个连通区域")
print(f"\n面积>40的区域:")

for i in range(1, num_labels):
    area = stats[i, cv2.CC_STAT_AREA]
    x = stats[i, cv2.CC_STAT_LEFT]
    y = stats[i, cv2.CC_STAT_TOP]
    w = stats[i, cv2.CC_STAT_WIDTH]
    h = stats[i, cv2.CC_STAT_HEIGHT]

    if area > 40:
        print(f"  区域{i}: 面积={area}, 位置=({x},{y}), 大小=({w}x{h})")

        # 绘制边界框
        cv2.rectangle(vis_image, (x, y), (x+w, y+h), (0, 255, 0), 2)

        # 标注面积
        cv2.putText(vis_image, f"{area}", (x, y-5),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

# 保存可视化结果
cv2.imwrite("tools/forgotten_hall_star_detector/debug/debug_yellow_regions.png", vis_image)
cv2.imwrite("tools/forgotten_hall_star_detector/debug/debug_yellow_mask.png", mask)
cv2.imwrite("tools/forgotten_hall_star_detector/debug/debug_yellow_mask_clean.png", mask_clean)

print(f"\n可视化结果已保存:")
print(f"  - debug_yellow_regions.png (标注的原图)")
print(f"  - debug_yellow_mask.png (原始mask)")
print(f"  - debug_yellow_mask_clean.png (清洁后的mask)")
