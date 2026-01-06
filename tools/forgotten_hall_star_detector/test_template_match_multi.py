#!/usr/bin/env python3
"""
测试小黄星模板匹配效果 - 多阈值对比版本
"""
import cv2
import numpy as np
from pathlib import Path

# 文件路径
template_path = "screenshots/crops/crop_20260106_213501.png"
screenshot_path = "screenshots/templates/template_20260101_163612.png"
output_dir = "screenshots/star_match_results"

# 创建输出目录
Path(output_dir).mkdir(exist_ok=True)

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
h, w = template.shape[:2]

# 测试不同阈值
thresholds = [0.65, 0.70, 0.75, 0.80, 0.85]

print("\n" + "="*60)

for threshold in thresholds:
    # 找到所有匹配位置
    locations = np.where(result >= threshold)
    matches = list(zip(*locations[::-1]))  # (x, y) 坐标

    # 去除重叠的匹配（非极大值抑制）
    matches_filtered = []
    if len(matches) > 0:
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

    print(f"\n阈值 {threshold:.2f}: 找到 {len(matches_filtered)} 个匹配")

    # 在截图上标记匹配位置
    result_img = screenshot.copy()
    for i, (x, y) in enumerate(matches_filtered, 1):
        score = result[y, x]
        print(f"  #{i}: 位置=({x:4d}, {y:4d}), 匹配度={score:.4f}")

        # 画绿色矩形框（加粗以便看清）
        cv2.rectangle(result_img, (x-2, y-2), (x + w + 2, y + h + 2), (0, 255, 0), 3)
        # 画红色中心点
        center_x = x + w // 2
        center_y = y + h // 2
        cv2.circle(result_img, (center_x, center_y), 5, (0, 0, 255), -1)
        # 标注序号（大字体）
        cv2.putText(result_img, str(i), (x - 10, y - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)

    # 添加阈值信息到图片上
    info_text = f"Threshold: {threshold:.2f} | Matches: {len(matches_filtered)}"
    cv2.putText(result_img, info_text, (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 2)

    # 保存结果
    output_path = f"{output_dir}/threshold_{threshold:.2f}.png"
    cv2.imwrite(output_path, result_img)
    print(f"  -> 已保存: {output_path}")

print("="*60)
print(f"\n所有结果图片已保存到: {output_dir}/")
print("\n建议:")
print("- 查看不同阈值的结果图片，选择识别准确且误报较少的阈值")
print("- 阈值太低会有误匹配，阈值太高会漏检")
print("- 根据实际游戏场景调整阈值")
