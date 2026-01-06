"""
调试脚本：测试不同搜索区域
"""

import cv2
from star_detector import detect_yellow_stars

# 加载图像
image = cv2.imread("screenshots/templates/template_20251229_233656.png")

print("测试不同的搜索区域:\n")

test_areas = [
    ("全图搜索", None),
    ("默认区域 (100,200,1180,300)", (100, 200, 1180, 300)),
    ("扩大Y范围 (100,150,1180,350)", (100, 150, 1180, 350)),
    ("全宽度 (0,200,1280,300)", (0, 200, 1280, 300)),
    ("全图 (0,0,1280,720)", (0, 0, 1280, 720)),
]

for name, area in test_areas:
    stars = detect_yellow_stars(image, area)
    print(f"{name}:")
    print(f"  检测到 {len(stars)} 个星星")
    if stars:
        y_coords = [s['center'][1] for s in stars]
        print(f"  Y坐标范围: {min(y_coords)} - {max(y_coords)}")
        for idx, star in enumerate(stars[:5]):  # 只显示前5个
            print(f"    星星{idx+1}: 中心{star['center']}, 像素数{star['pixel_count']}")
    print()
