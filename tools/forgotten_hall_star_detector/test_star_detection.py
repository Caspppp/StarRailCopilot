"""
星级检测测试脚本

测试星级检测算法的准确性，并生成可视化结果
"""

import cv2
import os
from datetime import datetime
from star_detector import detect_yellow_stars, cluster_stars_by_proximity, match_stars_to_stages


def test_star_detection():
    """
    测试星级检测功能
    """
    # 测试图像路径
    test_image_path = "screenshots/templates/template_20251229_233656.png"

    if not os.path.exists(test_image_path):
        print(f"[错误] 测试图像不存在: {test_image_path}")
        return

    # 加载图像
    image = cv2.imread(test_image_path)
    if image is None:
        print(f"[错误] 无法加载图像: {test_image_path}")
        return

    h, w = image.shape[:2]
    print(f"\n[星级检测测试]")
    print(f"图像尺寸: {w}x{h}")
    print(f"图像路径: {test_image_path}")
    print("=" * 60)

    # 步骤1：检测黄色星星
    print("\n[步骤1] 检测黄色星星...")
    star_regions = detect_yellow_stars(image)
    print(f"找到 {len(star_regions)} 个黄色星星区域")

    if star_regions:
        print("\n星星详情:")
        for idx, star in enumerate(star_regions):
            center = star['center']
            bbox = star['bbox']
            pixels = star['pixel_count']
            print(f"  星星 {idx+1}: 中心=({center[0]}, {center[1]}), 像素数={pixels}")

    # 步骤2：聚类星星
    print(f"\n[步骤2] 聚类临近星星...")
    star_clusters = cluster_stars_by_proximity(star_regions)
    print(f"聚类为 {len(star_clusters)} 组")

    if star_clusters:
        print("\n聚类详情:")
        for idx, cluster in enumerate(star_clusters):
            count = cluster['count']
            x_range = (cluster['x_min'], cluster['x_max'])
            center_x = cluster['center_x']
            print(f"  组 {idx+1}: {count} 个星星, X范围={x_range}, 中心X={center_x}")

    # 步骤3：模拟关卡框进行匹配测试
    print(f"\n[步骤3] 匹配星星到关卡...")
    # 从测试图像中，我们假设有5个关卡，它们的大致位置
    # 这里使用估计的关卡位置进行测试
    simulated_stage_boxes = [
        (140, 180, 200, 220),  # 关卡01
        (280, 230, 340, 270),  # 关卡02
        (420, 180, 480, 220),  # 关卡03
        (680, 230, 740, 270),  # 关卡04
        (920, 180, 980, 220),  # 关卡05
    ]

    stage_star_map = match_stars_to_stages(star_clusters, simulated_stage_boxes)
    print(f"\n关卡星级映射: {stage_star_map}")

    print("\n关卡星级详情:")
    for stage_idx, star_count in sorted(stage_star_map.items()):
        stage_num = stage_idx + 1
        status = "已完成" if star_count == 3 else "未完成"
        print(f"  关卡 {stage_num:02d}: {star_count} 星 ({status})")

    # 步骤4：可视化结果
    print(f"\n[步骤4] 生成可视化结果...")
    vis_image = image.copy()

    # 绘制星星区域（绿色）
    for star in star_regions:
        x1, y1, x2, y2 = star['bbox']
        cv2.rectangle(vis_image, (x1, y1), (x2, y2), (0, 255, 0), 1)
        center = star['center']
        cv2.circle(vis_image, center, 3, (0, 255, 0), -1)

    # 绘制聚类边界（蓝色）
    for cluster in star_clusters:
        x_min, x_max = cluster['x_min'], cluster['x_max']
        y_center = cluster['y_center']
        cv2.line(vis_image, (x_min, y_center - 20), (x_max, y_center - 20), (255, 0, 0), 2)

        # 标注星星数量
        center_x = cluster['center_x']
        count = cluster['count']
        text = f"{count} stars"
        cv2.putText(vis_image, text, (center_x - 30, y_center - 30),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 1)

    # 绘制模拟的关卡框（红色）
    for stage_idx, box in enumerate(simulated_stage_boxes):
        x1, y1, x2, y2 = box
        star_count = stage_star_map.get(stage_idx, 0)
        color = (0, 0, 255) if star_count == 3 else (128, 128, 128)
        cv2.rectangle(vis_image, (x1, y1), (x2, y2), color, 2)

        # 标注关卡编号和星数
        stage_num = stage_idx + 1
        text = f"{stage_num:02d} ({star_count}*)"
        cv2.putText(vis_image, text, (x1, y1 - 5),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)

    # 保存结果
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = f"tools/forgotten_hall_star_detector/debug/star_detection_result_{timestamp}.png"
    cv2.imwrite(output_path, vis_image)
    print(f"\n可视化结果已保存: {output_path}")

    print("\n" + "=" * 60)
    print("[测试完成]")

    # 验证预期结果
    print("\n[验证] 检查预期结果...")
    success = True

    # 预期至少检测到9个星星
    if len(star_regions) < 9:
        print(f"  ❌ 检测到的星星太少: {len(star_regions)} < 9")
        success = False
    else:
        print(f"  ✓ 检测到足够的星星: {len(star_regions)}")

    # 预期至少3个聚类
    if len(star_clusters) < 3:
        print(f"  ❌ 聚类数量太少: {len(star_clusters)} < 3")
        success = False
    else:
        print(f"  ✓ 聚类数量正常: {len(star_clusters)}")

    # 预期至少3组有3个星星
    three_star_clusters = [c for c in star_clusters if c['count'] == 3]
    if len(three_star_clusters) < 3:
        print(f"  ❌ 3星聚类太少: {len(three_star_clusters)} < 3")
        success = False
    else:
        print(f"  ✓ 3星聚类正常: {len(three_star_clusters)}")

    if success:
        print("\n✓ 所有验证通过！")
    else:
        print("\n❌ 部分验证失败，请检查算法参数")

    return success


if __name__ == "__main__":
    test_star_detection()
