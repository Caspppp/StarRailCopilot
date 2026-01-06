"""
精确采样关卡01下方星星的颜色
"""

import cv2
import numpy as np

# 加载图像
image = cv2.imread("screenshots/templates/template_20251229_233656.png")

print("图像尺寸:", image.shape)
print("\n精确采样关卡01下方星星的颜色:\n")

# 根据截图，关卡01的数字在大约(175, 200)位置
# 星星应该在数字正下方，大约(175-210, 227-235)

# 采样多个精确的像素点
sample_points = [
    # 关卡01的星星（目测位置）
    (181, 231), (183, 232), (185, 233),  # 第一个星星
    (195, 231), (197, 232), (199, 233),  # 第二个星星
    (209, 231), (211, 232), (213, 233),  # 第三个星星

    # 关卡02的星星（目测位置，02在中间偏下）
    (293, 259), (295, 260), (297, 261),
    (307, 259), (309, 260), (311, 261),
    (321, 259), (323, 260), (325, 261),
]

print("采样点的颜色值:")
for x, y in sample_points:
    b, g, r = image[y, x]
    print(f"  ({x:3d}, {y:3d}): BGR=({b:3d}, {g:3d}, {r:3d}), RGB=({r:3d}, {g:3d}, {b:3d})")

# 绘制采样点
vis = image.copy()
for x, y in sample_points:
    cv2.circle(vis, (x, y), 2, (0, 255, 0), -1)

cv2.imwrite("tools/forgotten_hall_star_detector/debug/sample_points.png", vis)
print(f"\n采样点可视化已保存: debug/sample_points.png")

# 采样关卡01下方的一个小区域
x1, y1, x2, y2 = 180, 230, 215, 235
region = image[y1:y2, x1:x2]

print(f"\n关卡01星星区域 ({x1},{y1})-({x2},{y2}) 的统计:")
print(f"  区域形状: {region.shape}")

# 查找所有唯一颜色及其出现次数
region_flat = region.reshape(-1, 3)
unique_colors, counts = np.unique(region_flat, axis=0, return_counts=True)

# 按出现次数排序
sorted_indices = np.argsort(counts)[::-1]

print(f"\n最常见的10种颜色:")
for i in sorted_indices[:10]:
    b, g, r = unique_colors[i]
    count = counts[i]
    print(f"  BGR=({b:3d}, {g:3d}, {r:3d}), RGB=({r:3d}, {g:3d}, {b:3d}), 像素数={count:3d}")
