"""
测试系统集成：验证星级检测功能是否正确集成到 ForgottenHallStageOcr
"""

import cv2
import sys
sys.path.insert(0, '/Users/yexili/Desktop/Projects/StarRailCopilot-new')

from tasks.forgotten_hall.ui import ForgottenHallStageOcr
from tasks.forgotten_hall.assets.assets_forgotten_hall_ui import OCR_STAGE
from tasks.forgotten_hall.keywords.stage import ForgottenHallStage

# 加载测试图像
image = cv2.imread("screenshots/templates/template_20251229_233656.png")

print("[系统集成测试]\n")
print("测试 ForgottenHallStageOcr.matched_ocr() 是否包含星级信息\n")
print("=" * 70)

# 使用集成后的OCR进行识别
ocr = ForgottenHallStageOcr(OCR_STAGE)
results = ocr.matched_ocr(image, ForgottenHallStage)

print(f"\n识别结果：共 {len(results)} 个关卡\n")

for result in results:
    stage_name = result.matched_keyword
    star_count = result.star_count
    is_completed = result.is_completed

    status_text = "已完成 ✓" if is_completed else "未完成"

    print(f"关卡: {stage_name}")
    print(f"  OCR文本: {result.text}")
    print(f"  星级: {star_count} 星")
    print(f"  状态: {status_text}")
    print(f"  位置: {result.area}")
    print()

print("=" * 70)
print("\n[验证结果]")

# 验证：应该有至少一个关卡
if len(results) > 0:
    print(f"✓ 检测到 {len(results)} 个关卡")
else:
    print(f"❌ 未检测到任何关卡")

# 验证：所有结果都应该有 star_count 属性
all_have_star_count = all(hasattr(r, 'star_count') for r in results)
if all_have_star_count:
    print(f"✓ 所有结果都包含 star_count 属性")
else:
    print(f"❌ 部分结果缺少 star_count 属性")

# 验证：应该有至少一个3星关卡（根据测试截图）
three_star_stages = [r for r in results if r.star_count == 3]
if len(three_star_stages) > 0:
    print(f"✓ 检测到 {len(three_star_stages)} 个3星关卡")
    for stage in three_star_stages:
        print(f"  - {stage.matched_keyword}")
else:
    print(f"⚠ 未检测到3星关卡（预期至少1个）")

# 验证：is_completed 属性
has_completed_property = all(hasattr(r, 'is_completed') for r in results)
if has_completed_property:
    print(f"✓ 所有结果都包含 is_completed 属性")
else:
    print(f"❌ 部分结果缺少 is_completed 属性")

print("\n测试完成！")
