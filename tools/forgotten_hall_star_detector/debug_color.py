"""
调试脚本：检查星星的实际颜色值
"""

import cv2
import numpy as np

# 加载图像
image = cv2.imread("screenshots/templates/template_20251229_233656.png")

if image is None:
    print("无法加载图像")
    exit(1)

print("图像尺寸:", image.shape)

# 手动指定几个星星的大致位置来采样颜色
# 从截图中目测，关卡01的星星大约在 (175-205, 225-235) 区域
star_sample_regions = [
    (175, 225, 185, 235),  # 关卡01的第一个星星
    (190, 225, 200, 235),  # 关卡01的第二个星星
    (205, 225, 215, 235),  # 关卡01的第三个星星
]

print("\n采样星星区域的颜色:")
for idx, (x1, y1, x2, y2) in enumerate(star_sample_regions):
    region = image[y1:y2, x1:x2]

    # 计算平均BGR值
    mean_color = region.mean(axis=0).mean(axis=0)
    b, g, r = mean_color

    print(f"\n星星 {idx+1} 区域 ({x1},{y1})-({x2},{y2}):")
    print(f"  平均BGR: ({b:.0f}, {g:.0f}, {r:.0f})")
    print(f"  平均RGB: ({r:.0f}, {g:.0f}, {b:.0f})")

    # 查找区域内最亮的像素
    region_flat = region.reshape(-1, 3)
    max_brightness_idx = (region_flat.sum(axis=1)).argmax()
    brightest_pixel = region_flat[max_brightness_idx]
    b, g, r = brightest_pixel
    print(f"  最亮像素BGR: ({b}, {g}, {r})")
    print(f"  最亮像素RGB: ({r}, {g}, {b})")

# 扫描整个黄色范围
print("\n\n测试不同的颜色范围:")

test_ranges = [
    ("用户指定 RGB(254,199,112)", (97, 184, 239), (127, 214, 255)),
    ("放宽容差 ±30", (82, 169, 224), (142, 229, 255)),
    ("HSV 黄色范围", None, None),  # 特殊处理
]

for name, lower, upper in test_ranges:
    if lower is None:  # HSV
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        # 黄色在HSV空间: H=20-40, S>100, V>100
        lower_hsv = np.array([15, 80, 80], dtype=np.uint8)
        upper_hsv = np.array([35, 255, 255], dtype=np.uint8)
        mask = cv2.inRange(hsv, lower_hsv, upper_hsv)
        print(f"\n{name}:")
        print(f"  H: 15-35, S: 80-255, V: 80-255")
    else:
        lower = np.array(lower, dtype=np.uint8)
        upper = np.array(upper, dtype=np.uint8)
        mask = cv2.inRange(image, lower, upper)
        print(f"\n{name}:")
        print(f"  BGR: {lower} - {upper}")

    pixel_count = np.sum(mask > 0)
    print(f"  检测到的黄色像素总数: {pixel_count}")

    if pixel_count > 0:
        # 连通组件分析
        num_labels, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        regions_over_40 = sum(1 for i in range(1, num_labels) if stats[i, cv2.CC_STAT_AREA] > 40)
        print(f"  面积>40的区域数量: {regions_over_40}")

print("\n\n扩大搜索区域测试（整图）:")
# 测试在整图中的黄色范围
full_image_test = [
    ("严格黄色", (97, 184, 239), (127, 214, 255)),
    ("放宽黄色", (70, 150, 200), (150, 255, 255)),
]

for name, lower, upper in full_image_test:
    lower = np.array(lower, dtype=np.uint8)
    upper = np.array(upper, dtype=np.uint8)
    mask = cv2.inRange(image, lower, upper)
    pixel_count = np.sum(mask > 0)

    if pixel_count > 0:
        num_labels, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        regions = [stats[i, cv2.CC_STAT_AREA] for i in range(1, num_labels)]
        regions_over_40 = [area for area in regions if area > 40]

        print(f"\n{name} BGR: {lower} - {upper}")
        print(f"  总像素数: {pixel_count}")
        print(f"  连通区域数: {len(regions)}")
        print(f"  面积>40的区域: {len(regions_over_40)}")
        if regions_over_40:
            print(f"  最大区域面积: {max(regions_over_40)}")
            print(f"  平均区域面积: {sum(regions_over_40)/len(regions_over_40):.1f}")
