"""
找到所有可能的黄色区域，尝试不同的颜色范围
"""

import cv2
import numpy as np

image = cv2.imread("screenshots/templates/template_20251229_233656.png")

# 测试不同的黄色/橙色范围
color_ranges = [
    ("亮黄色 RGB(254,199,112)", (97, 184, 239), (127, 214, 255)),
    ("橙黄色", (0, 100, 150), (100, 220, 255)),
    ("深橙色", (0, 50, 100), (80, 180, 220)),
    ("暗黄色 (基于采样)", (40, 15, 15), (80, 35, 40)),
]

print("扫描不同颜色范围，寻找可能的星星:\n")

for name, lower, upper in color_ranges:
    lower = np.array(lower, dtype=np.uint8)
    upper = np.array(upper, dtype=np.uint8)
    mask = cv2.inRange(image, lower, upper)

    # 连通组件分析
    num_labels, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)

    # 统计不同大小的区域
    areas = [stats[i, cv2.CC_STAT_AREA] for i in range(1, num_labels)]

    # 按Y坐标分组 - 找到在关卡数字下方的区域
    regions_in_stage_area = []
    for i in range(1, num_labels):
        y = stats[i, cv2.CC_STAT_TOP]
        area = stats[i, cv2.CC_STAT_AREA]
        # 关卡数字区域大约在 Y=180-280
        if 180 <= y <= 280 and area > 20:
            x = stats[i, cv2.CC_STAT_LEFT]
            w = stats[i, cv2.CC_STAT_WIDTH]
            h = stats[i, cv2.CC_STAT_HEIGHT]
            regions_in_stage_area.append((x, y, w, h, area))

    print(f"{name}:")
    print(f"  BGR范围: {lower} - {upper}")
    print(f"  总像素数: {np.sum(mask > 0)}")
    print(f"  连通区域数: {len(areas)}")

    if areas:
        print(f"  区域面积范围: {min(areas)} - {max(areas)}")
        areas_over_20 = [a for a in areas if a > 20]
        if areas_over_20:
            print(f"  面积>20的区域: {len(areas_over_20)}")

    if regions_in_stage_area:
        print(f"  在关卡区域(Y=180-280)的区域: {len(regions_in_stage_area)}")
        for x, y, w, h, area in regions_in_stage_area[:10]:
            print(f"    位置=({x},{y}), 大小=({w}x{h}), 面积={area}")

    print()

# 特别检查：关卡01下方的具体区域
print("\n特别检查：关卡01下方区域 (175-215, 225-240):")
region = image[225:240, 175:215]

# 统计这个区域内的所有颜色
region_flat = region.reshape(-1, 3)
unique_colors, counts = np.unique(region_flat, axis=0, return_counts=True)

# 找到最亮的颜色（总和最大）
color_sums = unique_colors.sum(axis=1)
brightest_idx = np.argmax(color_sums)
b, g, r = unique_colors[brightest_idx]

print(f"  最亮的颜色: BGR=({b},{g},{r}), RGB=({r},{g},{b}), 出现{counts[brightest_idx]}次")

# 找到最"黄"的颜色（G和R都较高，B较低）
yellow_scores = (unique_colors[:, 1].astype(float) + unique_colors[:, 2].astype(float)) - unique_colors[:, 0].astype(float)
yellowest_idx = np.argmax(yellow_scores)
b, g, r = unique_colors[yellowest_idx]

print(f"  最黄的颜色: BGR=({b},{g},{r}), RGB=({r},{g},{b}), 出现{counts[yellowest_idx]}次")
