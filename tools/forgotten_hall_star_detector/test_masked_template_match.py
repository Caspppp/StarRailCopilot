#!/usr/bin/env python3
"""
使用带遮罩的模板匹配来识别不规则形状的小黄星
"""
import cv2
import numpy as np
from pathlib import Path

# 文件路径
template_path = "screenshots/crops/crop_20260106_232720.png"
screenshot_path = "screenshots/templates/template_20260101_163612.png"
output_dir = "screenshots/masked_star_match_results"

# 创建输出目录
Path(output_dir).mkdir(exist_ok=True)

# 读取模板和截图
template = cv2.imread(template_path, cv2.IMREAD_UNCHANGED)  # 保留 alpha 通道
screenshot = cv2.imread(screenshot_path)

if template is None:
    print(f"无法读取模板图片: {template_path}")
    exit(1)
if screenshot is None:
    print(f"无法读取截图: {screenshot_path}")
    exit(1)

print(f"模板尺寸: {template.shape}")
print(f"截图尺寸: {screenshot.shape}")

# 方法1: 基于颜色创建 mask（提取黄色星星）
# 转换到 HSV 色彩空间更容易提取黄色
template_hsv = cv2.cvtColor(template[:, :, :3] if template.shape[2] == 4 else template,
                            cv2.COLOR_BGR2HSV)

# 定义黄色的 HSV 范围
# 黄色在 HSV 中 H 值大约在 20-30
lower_yellow = np.array([15, 100, 100])
upper_yellow = np.array([35, 255, 255])

# 创建黄色 mask
mask = cv2.inRange(template_hsv, lower_yellow, upper_yellow)

# 保存 mask 用于查看
cv2.imwrite(f"{output_dir}/mask_color.png", mask)
print(f"\n颜色 mask 已保存: {output_dir}/mask_color.png")

# 如果 mask 太稀疏，尝试膨胀一下
kernel = np.ones((3, 3), np.uint8)
mask_dilated = cv2.dilate(mask, kernel, iterations=1)
cv2.imwrite(f"{output_dir}/mask_dilated.png", mask_dilated)

# 可视化：显示 mask 覆盖的区域
template_rgb = template[:, :, :3] if template.shape[2] == 4 else template.copy()
masked_template = cv2.bitwise_and(template_rgb, template_rgb, mask=mask)
cv2.imwrite(f"{output_dir}/template_masked.png", masked_template)
print(f"遮罩后的模板: {output_dir}/template_masked.png")

# 进行带 mask 的模板匹配
# 注意：cv2.matchTemplate 在某些版本中支持 mask 参数
# 如果不支持，我们用另一种方法：只对模板的黄色部分加权

print("\n" + "="*60)
print("方法1: 使用颜色 mask 的模板匹配")
print("="*60)

# 标准模板匹配（不带 mask）- 作为对比
result_no_mask = cv2.matchTemplate(screenshot, template_rgb, cv2.TM_CCOEFF_NORMED)

# 带 mask 的方法：将非星星区域设为灰色（中性色）
template_for_match = template_rgb.copy()
# 将背景设为平均灰度，减少干扰
avg_gray = np.mean(screenshot)
template_for_match[mask == 0] = [avg_gray, avg_gray, avg_gray]
cv2.imwrite(f"{output_dir}/template_neutralized.png", template_for_match)

result_masked = cv2.matchTemplate(screenshot, template_for_match, cv2.TM_CCOEFF_NORMED)

# 测试不同阈值
thresholds = [0.65, 0.70, 0.75, 0.80]
h, w = template.shape[:2]

for method_name, result in [("无mask", result_no_mask), ("有mask", result_masked)]:
    print(f"\n{'='*60}")
    print(f"方法: {method_name}")
    print(f"{'='*60}")

    for threshold in thresholds:
        # 找到所有匹配位置
        locations = np.where(result >= threshold)
        matches = list(zip(*locations[::-1]))

        # 非极大值抑制
        matches_filtered = []
        if len(matches) > 0:
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

        print(f"\n阈值 {threshold:.2f}: 找到 {len(matches_filtered)} 个匹配")

        # 可视化
        result_img = screenshot.copy()
        for i, (x, y) in enumerate(matches_filtered[:20], 1):  # 只显示前20个
            score = result[y, x]
            if i <= 10:  # 只打印前10个
                print(f"  #{i}: ({x:4d}, {y:4d}), 匹配度={score:.4f}")

            # 绘制
            cv2.rectangle(result_img, (x-2, y-2), (x + w + 2, y + h + 2), (0, 255, 0), 2)
            cv2.circle(result_img, (x + w//2, y + h//2), 4, (0, 0, 255), -1)
            cv2.putText(result_img, str(i), (x - 10, y - 5),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

        # 添加信息
        info = f"{method_name} | Threshold: {threshold:.2f} | Matches: {len(matches_filtered)}"
        cv2.putText(result_img, info, (10, 30),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)

        # 保存
        safe_name = method_name.replace(" ", "_")
        output_path = f"{output_dir}/{safe_name}_threshold_{threshold:.2f}.png"
        cv2.imwrite(output_path, result_img)

print(f"\n{'='*60}")
print(f"所有结果已保存到: {output_dir}/")
print(f"{'='*60}")
