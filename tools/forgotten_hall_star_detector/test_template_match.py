#!/usr/bin/env python3
"""
测试小黄星模板匹配效果
"""
import cv2
import numpy as np
from pathlib import Path

# 文件路径
template_path = "screenshots/crops/crop_20260106_213501.png"
screenshot_path = "screenshots/templates/template_20260101_163612.png"
output_path = "screenshots/star_match_result.png"

# 读取模板和截图
template = cv2.imread(template_path)
screenshot = cv2.imread(screenshot_path)

if template is None:
    print(f"无法读取模板图片: {template_path}")
    exit(1)
if screenshot is None:
    print(f"无法读取截图: {screenshot_path}")
    exit(1)

print(f"模板尺寸: {template.shape}")
print(f"截图尺寸: {screenshot.shape}")

# 进行模板匹配
result = cv2.matchTemplate(screenshot, template, cv2.TM_CCOEFF_NORMED)

# 设置不同的阈值进行测试
thresholds = [0.7, 0.75, 0.8, 0.85, 0.9, 0.95]

print("\n" + "="*60)
for threshold in thresholds:
    # 找到所有匹配位置
    locations = np.where(result >= threshold)
    matches = list(zip(*locations[::-1]))  # (x, y) 坐标

    # 去除重叠的匹配（非极大值抑制）
    if len(matches) > 0:
        matches_filtered = []
        h, w = template.shape[:2]

        # 按匹配度排序
        match_scores = [(x, y, result[y, x]) for x, y in matches]
        match_scores.sort(key=lambda m: m[2], reverse=True)

        for x, y, score in match_scores:
            # 检查是否与已有匹配重叠
            overlap = False
            for fx, fy in matches_filtered:
                if abs(x - fx) < w and abs(y - fy) < h:
                    overlap = True
                    break
            if not overlap:
                matches_filtered.append((x, y))

        print(f"阈值 {threshold:.2f}: 找到 {len(matches_filtered)} 个匹配")
        for i, (x, y) in enumerate(matches_filtered, 1):
            score = result[y, x]
            print(f"  #{i}: 位置=({x}, {y}), 匹配度={score:.4f}")
    else:
        print(f"阈值 {threshold:.2f}: 找到 0 个匹配")

print("="*60)

# 使用 0.8 阈值进行可视化
threshold = 0.8
locations = np.where(result >= threshold)
matches = list(zip(*locations[::-1]))

# 去除重叠
matches_filtered = []
h, w = template.shape[:2]
match_scores = [(x, y, result[y, x]) for x, y in matches]
match_scores.sort(key=lambda m: m[2], reverse=True)

for x, y, score in match_scores:
    overlap = False
    for fx, fy in matches_filtered:
        if abs(x - fx) < w and abs(y - fy) < h:
            overlap = True
            break
    if not overlap:
        matches_filtered.append((x, y))

# 在截图上标记匹配位置
result_img = screenshot.copy()
for i, (x, y) in enumerate(matches_filtered, 1):
    # 画绿色矩形框
    cv2.rectangle(result_img, (x, y), (x + w, y + h), (0, 255, 0), 2)
    # 画红色中心点
    center_x = x + w // 2
    center_y = y + h // 2
    cv2.circle(result_img, (center_x, center_y), 3, (0, 0, 255), -1)
    # 标注序号
    cv2.putText(result_img, str(i), (x, y - 5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

# 保存结果
cv2.imwrite(output_path, result_img)
print(f"\n结果图片已保存到: {output_path}")
print(f"使用阈值 0.8，共识别出 {len(matches_filtered)} 个小黄星")
