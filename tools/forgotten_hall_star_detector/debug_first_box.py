"""
调试第一个检测到的数字框
"""

import cv2
import sys
sys.path.insert(0, '/Users/yexili/Desktop/Projects/StarRailCopilot-new')

from tasks.forgotten_hall.ui import ForgottenHallStageOcr
from tasks.forgotten_hall.assets.assets_forgotten_hall_ui import OCR_STAGE

# 加载测试图像
image = cv2.imread("screenshots/templates/template_20251229_233656.png")

# 使用OCR检测数字框
ocr = ForgottenHallStageOcr(OCR_STAGE)
boxes = ocr._find_number(image)

print(f"检测到 {len(boxes)} 个数字框:\n")

for idx, box in enumerate(boxes):
    x1, y1, x2, y2 = box
    print(f"框 {idx}: ({x1},{y1})-({x2},{y2}), 宽度={x2-x1}, 高度={y2-y1}")

    # 裁剪并保存
    crop_img = image[y1:y2, x1:x2]
    cv2.imwrite(f"tools/forgotten_hall_star_detector/debug/box_{idx}.png", crop_img)

print("\n已保存所有数字框的裁剪图像")
