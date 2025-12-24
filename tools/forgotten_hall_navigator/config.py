"""
Configuration constants for Forgotten Hall navigator.
"""

import cv2

# =========================================================================
# 模板匹配参数
# =========================================================================

# 模板匹配方法（OpenCV TM_CCOEFF_NORMED）
TEMPLATE_MATCH_METHOD = cv2.TM_CCOEFF_NORMED

# 默认匹配阈值（适用于大部分场景）
TEMPLATE_MATCH_THRESHOLD = 0.75

# Tab 切换匹配阈值（click 模板）
TEMPLATE_MATCH_THRESHOLD_CLICK = 0.70

# Nav 内容检测阈值（check 模板，用于验证Tab切换成功）
TEMPLATE_MATCH_THRESHOLD_NAV = 0.70

# =========================================================================
# 重试机制参数
# =========================================================================

# Tab 切换最大重试次数
MAX_TAB_RETRY = 3

# Nav 选择最大重试次数
MAX_NAV_RETRY = 3

# 重试等待间隔（秒）
RETRY_WAIT_INTERVAL = 1.0

# =========================================================================
# 调试参数
# =========================================================================

# 是否保存调试截图（仅首次匹配失败/成功时保存）
SAVE_DEBUG_SCREENSHOTS = True

# 调试截图保存目录（相对于当前文件）
DEBUG_SCREENSHOT_DIR = "debug"

# 是否输出详细匹配信息到日志
VERBOSE_MATCHING = False
