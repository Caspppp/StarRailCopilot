"""
验证用户提供的星星位置
"""

import cv2
import numpy as np

image = cv2.imread("screenshots/templates/template_20251229_233656.png")

# 用户提供的星星位置
star_area = (340, 455, 368, 484)
x1, y1, x2, y2 = star_area

print(f"验证星星位置: ({x1}, {y1}) - ({x2}, {y2})")
print(f"区域大小: {x2-x1}x{y2-y1}\n")

# 提取这个区域
star_region = image[y1:y2, x1:x2]

# 采样颜色
mean_color = star_region.mean(axis=0).mean(axis=0)
b, g, r = mean_color
print(f"平均颜色: BGR=({b:.0f}, {g:.0f}, {r:.0f}), RGB=({r:.0f}, {g:.0f}, {b:.0f})")

# 查找最亮的像素
region_flat = star_region.reshape(-1, 3)
max_brightness_idx = (region_flat.sum(axis=1)).argmax()
brightest = region_flat[max_brightness_idx]
b, g, r = brightest
print(f"最亮像素: BGR=({b}, {g}, {r}), RGB=({r}, {g}, {b})")

# 测试用户提供的颜色范围
lower_yellow = np.array([97, 184, 239], dtype=np.uint8)
upper_yellow = np.array([127, 214, 255], dtype=np.uint8)

mask = cv2.inRange(star_region, lower_yellow, upper_yellow)
yellow_pixels = np.sum(mask > 0)

print(f"\n使用 RGB(254,199,112) 范围:")
print(f"  检测到的黄色像素: {yellow_pixels}/{star_region.shape[0]*star_region.shape[1]}")

# 检测整个图像中Y=450-490区域的星星
print(f"\n检测整个图像中 Y=450-490 区域的星星:")
search_region = image[450:490, 0:1280]

mask_full = cv2.inRange(search_region, lower_yellow, upper_yellow)

# 形态学降噪
kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
mask_clean = cv2.morphologyEx(mask_full, cv2.MORPH_OPEN, kernel)

# 连通组件分析
num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(mask_clean, connectivity=8)

print(f"检测到 {num_labels-1} 个连通区域")
print(f"\n面积>40的区域:")

stars_found = []
for i in range(1, num_labels):
    area = stats[i, cv2.CC_STAT_AREA]
    if area > 40:
        x = stats[i, cv2.CC_STAT_LEFT]
        y = stats[i, cv2.CC_STAT_TOP] + 450  # 加回偏移
        w = stats[i, cv2.CC_STAT_WIDTH]
        h = stats[i, cv2.CC_STAT_HEIGHT]
        print(f"  星星: 位置=({x}, {y}), 大小=({w}x{h}), 面积={area}")
        stars_found.append((x, y, w, h, area))

# 可视化
vis = image.copy()
cv2.rectangle(vis, (star_area[0], star_area[1]), (star_area[2], star_area[3]), (0, 255, 0), 2)
cv2.putText(vis, "User provided", (star_area[0], star_area[1]-5),
           cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

for x, y, w, h, area in stars_found:
    cv2.rectangle(vis, (x, y), (x+w, y+h), (255, 0, 0), 2)
    cv2.putText(vis, f"{area}", (x, y-5),
               cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 0, 0), 1)

cv2.imwrite("tools/forgotten_hall_star_detector/debug/verify_location.png", vis)
print(f"\n可视化已保存: debug/verify_location.png")
