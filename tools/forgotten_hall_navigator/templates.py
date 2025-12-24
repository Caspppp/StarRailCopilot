"""
Template manager for Forgotten Hall navigation buttons.
Loads and caches button templates for Tab and Nav navigation.
"""

import cv2
import numpy as np
from pathlib import Path
from module.logger.logger import logger


# Manual button areas (overrides auto-extraction)
# Format: "tab/button_name": (x1, y1, x2, y2)
# These coordinates specify the button region in 1280x720 screenshots
# 禁用手动区域，使用全区域搜索
MANUAL_BUTTON_AREAS = {
    # "tab/treasures_lightward_check": (446, 96, 471, 132),  # 禁用：坐标不准确
    # "tab/treasures_lightward_click": (446, 96, 471, 132),   # 禁用：坐标不准确
}


class ButtonTemplateManager:
    """管理忘却之庭导航按钮模板"""

    def __init__(self):
        """初始化模板管理器，预加载所有模板到内存"""
        self.templates: dict[str, np.ndarray] = {}
        self.button_areas: dict[str, tuple] = {}  # 新增：存储按钮位置
        self.assets_dir = Path(__file__).parent / "assets"
        self._load_all_templates()

    def _load_all_templates(self):
        """预加载所有8个模板（Tab: 2个，Nav: 6个），自动提取按钮区域"""
        # Tab 按钮模板
        tab_templates = {
            "tab/treasures_lightward_check": "tab/treasures_lightward_check.png",
            "tab/treasures_lightward_click": "tab/treasures_lightward_click.png",
        }

        # Nav 按钮模板
        nav_templates = {
            "nav/forgotten_hall_check": "nav/forgotten_hall_check.png",
            "nav/forgotten_hall_click": "nav/forgotten_hall_click.png",
            "nav/pure_fiction_check": "nav/pure_fiction_check.png",
            "nav/pure_fiction_click": "nav/pure_fiction_click.png",
            "nav/apocalyptic_shadow_check": "nav/apocalyptic_shadow_check.png",
            "nav/apocalyptic_shadow_click": "nav/apocalyptic_shadow_click.png",
        }

        # 合并所有模板
        all_templates = {**tab_templates, **nav_templates}

        # 加载每个模板
        for key, filename in all_templates.items():
            path = self.assets_dir / filename
            result = self._load_template(path)
            if result is not None:
                button_image, button_area = result
                self.templates[key] = button_image
                self.button_areas[key] = button_area
                logger.info(f"Loaded template: {key} ({button_image.shape})")
            else:
                logger.warning(f"Failed to load template: {key}")

        logger.attr("ButtonTemplateManager", f"{len(self.templates)}/8 templates loaded")

    def _load_template(self, path: Path) -> tuple[np.ndarray, tuple] | None:
        """
        加载模板并提取按钮区域（优先使用手动区域，否则自动提取）

        SRC 官方模板格式：1280x720 完整截图，按钮周围是黑色背景
        本方法会：
        1. 优先检查 MANUAL_BUTTON_AREAS 配置
        2. 如无手动配置，则自动检测非黑色区域

        Args:
            path: 模板文件路径

        Returns:
            tuple: (裁剪后的按钮图像, 按钮在原图中的位置 (x1, y1, x2, y2))
            None: 加载失败
        """
        if not path.exists():
            logger.warning(f"Template file not found: {path}")
            return None

        # 使用灰度模式加载，与遗器模块保持一致
        image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)

        if image is None:
            logger.warning(f"Failed to load template: {path}")
            return None

        # 构造模板 key (例如 "tab/treasures_lightward_check")
        template_key = str(path.parent.name + "/" + path.stem)

        # 检查是否有手动指定区域
        if template_key in MANUAL_BUTTON_AREAS:
            # 使用手动区域（用于指定屏幕搜索位置）
            x1, y1, x2, y2 = MANUAL_BUTTON_AREAS[template_key]
            button_area = (x1, y1, x2, y2)
            # 对于小裁剪模板，直接使用完整图片，不再裁剪
            button_image = image
            logger.info(f"Using manual button area for {template_key}: "
                        f"area={button_area}, size={button_image.shape}")
            return button_image, button_area

        # 自动检测非黑色区域（按钮位置）
        # 找到像素值 > 10 的坐标（排除纯黑背景）
        non_zero_coords = np.argwhere(image > 10)
        if len(non_zero_coords) == 0:
            logger.warning(f"Template has no non-black content: {path}")
            return None

        # 计算边界框（非黑色内容的范围）
        y_min, x_min = non_zero_coords.min(axis=0)
        y_max, x_max = non_zero_coords.max(axis=0)

        # 检测内容尺寸
        content_width = x_max - x_min
        content_height = y_max - y_min

        # 检测图片尺寸
        image_height, image_width = image.shape[:2]
        is_large_template = image_width > 500 or image_height > 500  # 大于500px认为是全屏截图
        is_small_content = content_width < 150 and content_height < 150  # 内容小于150px

        if is_large_template and is_small_content:
            # 大模板但内容小：使用传统自动提取（裁剪出按钮）
            padding = 5
            y_min = max(0, y_min - padding)
            x_min = max(0, x_min - padding)
            y_max = min(image.shape[0], y_max + padding)
            x_max = min(image.shape[1], x_max + padding)

            button_image = image[y_min:y_max, x_min:x_max]
            button_area = (x_min, y_min, x_max, y_max)
            logger.info(f"Large template with small content, extracted button: "
                        f"area={button_area}, size={button_image.shape}")
        elif content_width < 100 and content_height < 100:
            # 小裁剪模板：使用全区域搜索
            if "tab" in str(path):
                button_area = (50, 20, 650, 120)
                logger.info(f"Small tab template detected, using full tab search area: {button_area}")
            elif "nav" in str(path):
                button_area = (150, 120, 850, 650)
                logger.info(f"Small nav template detected, using full nav search area: {button_area}")
            else:
                button_area = (0, 0, image.shape[1], image.shape[0])
            button_image = image
        else:
            # 其他情况：使用传统提取
            padding = 5
            y_min = max(0, y_min - padding)
            x_min = max(0, x_min - padding)
            y_max = min(image.shape[0], y_max + padding)
            x_max = min(image.shape[1], x_max + padding)

            button_image = image[y_min:y_max, x_min:x_max]
            button_area = (x_min, y_min, x_max, y_max)

        logger.info(f"Auto-extracted button from {path.name}: "
                    f"area={button_area}, size={button_image.shape}")

        return button_image, button_area

    def get_template(self, key: str) -> np.ndarray | None:
        """
        获取已缓存的模板图像

        Args:
            key: 模板键名，格式如 "tab/treasures_lightward_check" 或 "nav/forgotten_hall_click"

        Returns:
            numpy.ndarray: 模板图像，不存在时返回 None
        """
        template = self.templates.get(key)
        if template is None:
            logger.warning(f"Template not found in cache: {key}")
        return template

    def get_button_area(self, key: str) -> tuple | None:
        """
        获取按钮在原始截图中的位置

        Args:
            key: 模板键名，格式如 "tab/treasures_lightward_check" 或 "nav/forgotten_hall_click"

        Returns:
            tuple: 按钮位置 (x1, y1, x2, y2)，不存在时返回 None
        """
        area = self.button_areas.get(key)
        if area is None:
            logger.warning(f"Button area not found for: {key}")
        return area

    def is_loaded(self, key: str) -> bool:
        """检查模板是否已成功加载"""
        return key in self.templates

    def get_all_keys(self) -> list[str]:
        """获取所有已加载的模板键名"""
        return list(self.templates.keys())
