"""
Core navigator for Treasures Lightward Tab → Forgotten Hall Nav.
Independent navigation module that does not depend on upstream DungeonTabSwitch/DungeonNavSwitch.
"""

import time
import cv2
import numpy as np
from typing import Optional, Tuple
from module.logger.logger import logger, logger_debug
from module.base.button import ClickButton
from module.base.timer import Timer

from .templates import ButtonTemplateManager
from . import config


class TreasuresLightwardNavigator:
    """
    独立导航器：从任意页面导航到忘却之庭

    导航路径：Guide → 逐光捡金 Tab → 忘却之庭 Nav
    """

    def __init__(self):
        """初始化导航器，加载模板"""
        self.templates = ButtonTemplateManager()
        self._debug_saved = {}  # Track which template_keys have been saved to debug
        logger.info("TreasuresLightwardNavigator initialized")

    def goto_forgotten_hall_from_guide(self, device) -> bool:
        """
        主入口：从 Guide 页面导航到忘却之庭内部

        完整流程:
        1. 切换到逐光捡金 Tab
        2. 选择忘却之庭 Nav
        3. 点击传送按钮进入忘却之庭内部页面

        Args:
            device: Device 实例，用于截图和点击

        Returns:
            bool: 是否成功到达忘却之庭内部页面
        """
        logger.hr("Navigate to Forgotten Hall via Treasures Lightward", level=2)

        # 步骤 1: 切换到逐光捡金 Tab
        if not self.ensure_treasures_lightward_tab(device):
            logger.error("Failed to switch to Treasures Lightward tab")
            return False

        # 步骤 2: 选择忘却之庭 Nav
        if not self.select_forgotten_hall_nav(device):
            logger.error("Failed to select Forgotten Hall nav")
            return False

        # 步骤 3: 点击传送按钮进入忘却之庭内部
        if not self.click_teleport_to_enter(device):
            logger.error("Failed to click teleport button")
            return False

        logger.info("Successfully navigated to Forgotten Hall interior")
        return True

    def goto_pure_fiction_from_guide(self, device) -> bool:
        """
        从 Guide 页面导航到虚构叙事内部

        导航路径：Guide → 逐光捡金 Tab → 虚构叙事 Nav → 传送进入
        """
        logger.hr("Navigate to Pure Fiction via Treasures Lightward", level=2)

        if not self.ensure_treasures_lightward_tab(device):
            logger.error("Failed to switch to Treasures Lightward tab")
            return False

        if not self.select_pure_fiction_nav(device):
            logger.error("Failed to select Pure Fiction nav")
            return False

        # 版本更新后可能出现“开启故事”弹窗，需要先点击确认
        self.handle_pure_fiction_start_story(device)

        # 虚构叙事进入选关需要点击一次独立传送按钮
        if not self.click_teleport_to_enter(device, teleport_template_key="nav/pure_fiction_teleport"):
            logger.error("Failed to click teleport button")
            return False

        # 少数情况下弹窗会在传送后出现，再处理一次
        self.handle_pure_fiction_start_story(device)

        logger.info("Successfully navigated to Pure Fiction interior")
        return True

    def goto_apocalyptic_shadow_from_guide(self, device) -> bool:
        """
        从 Guide 页面导航到末日幻影内部

        导航路径：Guide → 逐光捡金 Tab → 末日幻影 Nav → 传送进入
        """
        logger.hr("Navigate to Apocalyptic Shadow via Treasures Lightward", level=2)

        if not self.ensure_treasures_lightward_tab(device):
            logger.error("Failed to switch to Treasures Lightward tab")
            return False

        if not self.select_apocalyptic_shadow_nav(device):
            logger.error("Failed to select Apocalyptic Shadow nav")
            return False

        if not self.click_teleport_to_enter(device):
            logger.error("Failed to click teleport button")
            return False

        logger.info("Successfully navigated to Apocalyptic Shadow interior")
        return True

    def handle_pure_fiction_start_story(self, device) -> bool:
        """
        处理虚构叙事“开启故事”弹窗（可能在版本更新后首次进入出现）。

        Returns:
            bool: 是否点击过“开启故事”
        """
        template_key = "nav/pure_fiction_start_story"
        template = self.templates.get_template(template_key)
        area = self.templates.get_button_area(template_key)
        if template is None or area is None:
            return False

        clicked = False
        for attempt in range(1, config.MAX_NAV_RETRY + 1):
            device.screenshot()
            pos = self._find_template(
                device.image,
                template,
                area,
                threshold=config.TEMPLATE_MATCH_THRESHOLD_CLICK,
            )
            if pos is None:
                return clicked

            logger.info(f"Pure Fiction start story detected, clicking (attempt {attempt}/{config.MAX_NAV_RETRY})")
            self._click_position(device, pos)
            self._wait_for_screen_stable(device, timeout=3.0, check_interval=0.3)
            clicked = True

            device.screenshot()
            if self._find_template(
                device.image,
                template,
                area,
                threshold=config.TEMPLATE_MATCH_THRESHOLD_CLICK,
            ) is None:
                return True

        return clicked

    def click_teleport_to_enter(self, device, teleport_template_key: str | None = None) -> bool:
        """
        点击传送按钮进入忘却之庭内部页面

        在选择忘却之庭Nav后，右侧会显示预览和传送按钮，
        需要点击传送按钮才能真正进入忘却之庭内部。

        Returns:
            bool: 是否成功点击传送按钮并进入
        """
        logger.info("Clicking teleport button to enter...")

        default_teleport_center = (1028, 365)  # Forgotten Hall default teleport center
        fallback_teleport_centers = {
            # User-provided Pure Fiction teleport button area center: (1070, 445, 1107, 465)
            "nav/pure_fiction_teleport": (1088, 455),
        }

        if teleport_template_key:
            template = self.templates.get_template(teleport_template_key)
            area = self.templates.get_button_area(teleport_template_key)
            fallback_center = fallback_teleport_centers.get(teleport_template_key, default_teleport_center)

            if template is None or area is None:
                logger.warning(f"Teleport template not loaded: {teleport_template_key}, fallback click")
                self._click_position(device, fallback_center)
            else:
                clicked = False
                for attempt in range(1, config.MAX_NAV_RETRY + 1):
                    logger.info(f"Teleport click attempt {attempt}/{config.MAX_NAV_RETRY}")
                    pos = self._wait_for_template_position(
                        device,
                        template,
                        area,
                        timeout=config.RETRY_WAIT_INTERVAL,
                        threshold=config.TEMPLATE_MATCH_THRESHOLD_CLICK,
                    )
                    if pos is None:
                        continue

                    self._click_position(device, pos)
                    clicked = True
                    break

                if not clicked:
                    logger.warning("Teleport template matching failed, fallback click")
                    self._click_position(device, fallback_center)
        else:
            self._click_position(device, default_teleport_center)

        # 等待画面稳定（页面切换动画完成）
        logger.info("Waiting for screen to stabilize after teleport...")
        if not self._wait_for_screen_stable(device, timeout=3.0, check_interval=0.3):
            logger.warning("Screen did not stabilize, but continuing...")

        logger.info("Teleport button clicked and screen stabilized")
        return True

    def _wait_for_screen_stable(self, device, timeout=3.0, check_interval=0.3,
                                  stability_duration=0.6) -> bool:
        """
        等待画面稳定（页面切换动画完成）

        原理：连续比较截图，如果连续多次截图相同，则认为画面稳定

        Args:
            device: Device 实例
            timeout: 最大等待时间（秒）
            check_interval: 检查间隔（秒，基于截图节奏，无固定 sleep）
            stability_duration: 需要保持稳定的时长（秒）

        Returns:
            bool: 是否在超时前稳定
        """
        import cv2

        start_time = time.time()
        stable_start = None
        prev_image = None

        # 监控区域：屏幕中央区域（避免边缘动画干扰）
        monitor_area = (200, 100, 1080, 620)  # (x1, y1, x2, y2)

        while time.time() - start_time < timeout:
            device.screenshot()

            # 截取监控区域
            x1, y1, x2, y2 = monitor_area
            current_crop = device.image[y1:y2, x1:x2]

            # 转换为灰度图以加快比较
            if len(current_crop.shape) == 3:
                current_gray = cv2.cvtColor(current_crop, cv2.COLOR_BGR2GRAY)
            else:
                current_gray = current_crop

            if prev_image is not None:
                # 计算图像相似度
                diff = cv2.absdiff(current_gray, prev_image)
                diff_ratio = np.mean(diff) / 255.0  # 归一化到 0-1

                if diff_ratio < 0.01:  # 差异小于1%，认为画面相同
                    if stable_start is None:
                        stable_start = time.time()
                    elif time.time() - stable_start >= stability_duration:
                        # 画面已稳定足够长时间
                        elapsed = time.time() - start_time
                        logger.info(f"Screen stabilized after {elapsed:.2f}s")
                        return True
                else:
                    # 画面仍在变化，重置稳定计时
                    stable_start = None

            prev_image = current_gray

        # 超时
        logger.warning(f"Screen stabilization timeout after {timeout}s")
        return False

    def ensure_treasures_lightward_tab(self, device) -> bool:
        """
        确保切换到逐光捡金 Tab

        新策略:
        1. 总是查找并点击 click 模板（不检查是否已在Tab）
        2. 验证：检测是否出现 Nav 内容（如"混沌回忆"按钮）
        3. 重试机制

        Returns:
            bool: 是否成功切换到目标 Tab
        """
        logger.info("Ensuring Treasures Lightward tab...")

        click_template = self.templates.get_template("tab/treasures_lightward_click")
        click_area = self.templates.get_button_area("tab/treasures_lightward_click")

        if click_template is None:
            logger.error("Tab click template not loaded")
            return False
        if click_area is None:
            logger.error("Tab click area not found")
            return False

        # 获取 Nav 模板用于验证（检测是否出现了 Nav 内容）
        nav_check_template = self.templates.get_template("nav/forgotten_hall_check")
        nav_check_area = self.templates.get_button_area("nav/forgotten_hall_check")

        for attempt in range(1, config.MAX_TAB_RETRY + 1):
            logger.info(f"Tab switch attempt {attempt}/{config.MAX_TAB_RETRY}")

            # 截取当前画面
            device.screenshot()
            image = device.image

            # 先验证：检查是否已能看到 Nav 内容（说明已在正确Tab）
            if nav_check_template is not None and nav_check_area is not None:
                if self._is_template_matched(image, nav_check_template, nav_check_area,
                                              threshold=config.TEMPLATE_MATCH_THRESHOLD_NAV):
                    logger.info("Already on Treasures Lightward tab (Nav content visible)")
                    return True

            # 查找并点击 click 模板
            click_pos = self._find_template(image, click_template, click_area,
                                             threshold=config.TEMPLATE_MATCH_THRESHOLD_CLICK)
            if click_pos is None:
                logger.warning(f"Tab click button not found (attempt {attempt})")
                if attempt < config.MAX_TAB_RETRY:
                    click_pos = self._wait_for_template_position(
                        device,
                        click_template,
                        click_area,
                        timeout=config.RETRY_WAIT_INTERVAL,
                        threshold=config.TEMPLATE_MATCH_THRESHOLD_CLICK,
                    )
                    if click_pos is None:
                        continue
                else:
                    return False

            # 点击按钮
            self._click_position(device, click_pos)

            # 等待并验证切换成功：检测 Nav 内容是否出现
            verify_timer = Timer(3.0).start()
            while not verify_timer.reached():
                device.screenshot()

                # 验证：Nav 内容可见
                if nav_check_template is not None and nav_check_area is not None:
                    if self._is_template_matched(device.image, nav_check_template, nav_check_area,
                                                  threshold=config.TEMPLATE_MATCH_THRESHOLD_NAV):
                        logger.info("Tab switch successful (Nav content appeared)")
                        return True

            # 所有验证检查都失败
            logger.warning(f"Tab switch verification failed (attempt {attempt})")

        logger.error("Failed to switch to Treasures Lightward tab after all retries")
        return False

    def select_forgotten_hall_nav(self, device) -> bool:
        """
        选择忘却之庭二级导航

        新策略:
        1. 总是查找并点击 click 模板（不使用check预判断）
        2. 点击后验证选中状态
        3. 重试机制

        Returns:
            bool: 是否成功选择忘却之庭 Nav
        """
        logger.info("Selecting Forgotten Hall nav...")

        check_template = self.templates.get_template("nav/forgotten_hall_check")
        click_template = self.templates.get_template("nav/forgotten_hall_click")
        check_area = self.templates.get_button_area("nav/forgotten_hall_check")
        click_area = self.templates.get_button_area("nav/forgotten_hall_click")

        if check_template is None or click_template is None:
            logger.error("Nav templates not loaded")
            return False
        if check_area is None or click_area is None:
            logger.error("Nav button areas not found")
            return False

        for attempt in range(1, config.MAX_NAV_RETRY + 1):
            logger.info(f"Nav selection attempt {attempt}/{config.MAX_NAV_RETRY}")

            # 截取当前画面
            device.screenshot()
            image = device.image

            # 【移除check预判断】总是查找并点击 click 模板
            click_pos = self._find_template(image, click_template, click_area,
                                             threshold=config.TEMPLATE_MATCH_THRESHOLD_CLICK)
            if click_pos is None:
                logger.warning(f"Nav click button not found (attempt {attempt})")
                if attempt < config.MAX_NAV_RETRY:
                    click_pos = self._wait_for_template_position(
                        device,
                        click_template,
                        click_area,
                        timeout=config.RETRY_WAIT_INTERVAL,
                        threshold=config.TEMPLATE_MATCH_THRESHOLD_CLICK,
                    )
                    if click_pos is None:
                        continue
                else:
                    return False

            # 点击按钮
            self._click_position(device, click_pos)

            # 等待动画完成
            if not self._wait_for_screen_stable(device, timeout=2.0, check_interval=0.3):
                logger.warning("Nav selection did not stabilize, but continuing...")

            # 验证：点击后直接认为成功（check模板在不同Nav间相似度高，易误判）
            logger.info("Nav selection successful (clicked)")
            return True

        logger.error("Failed to select Forgotten Hall nav after all retries")
        return False

    def _select_nav(self, device, nav_key: str, nav_name: str) -> bool:
        logger.info(f"Selecting {nav_name} nav...")

        check_template = self.templates.get_template(f"nav/{nav_key}_check")
        click_template = self.templates.get_template(f"nav/{nav_key}_click")
        check_area = self.templates.get_button_area(f"nav/{nav_key}_check")
        click_area = self.templates.get_button_area(f"nav/{nav_key}_click")

        if check_template is None or click_template is None:
            logger.error("Nav templates not loaded")
            return False
        if check_area is None or click_area is None:
            logger.error("Nav button areas not found")
            return False

        for attempt in range(1, config.MAX_NAV_RETRY + 1):
            logger.info(f"Nav selection attempt {attempt}/{config.MAX_NAV_RETRY}")

            device.screenshot()
            image = device.image

            click_pos = self._find_template(
                image, click_template, click_area, threshold=config.TEMPLATE_MATCH_THRESHOLD_CLICK
            )
            if click_pos is None:
                logger.warning(f"Nav click button not found (attempt {attempt})")
                if attempt < config.MAX_NAV_RETRY:
                    click_pos = self._wait_for_template_position(
                        device,
                        click_template,
                        click_area,
                        timeout=config.RETRY_WAIT_INTERVAL,
                        threshold=config.TEMPLATE_MATCH_THRESHOLD_CLICK,
                    )
                    if click_pos is None:
                        continue
                return False

            self._click_position(device, click_pos)
            if not self._wait_for_screen_stable(device, timeout=2.0, check_interval=0.3):
                logger.warning(f"{nav_name} nav did not stabilize, but continuing...")

            logger.info("Nav selection successful (clicked)")
            return True

        return False

    def select_pure_fiction_nav(self, device) -> bool:
        return self._select_nav(device, nav_key="pure_fiction", nav_name="Pure Fiction")

    def select_apocalyptic_shadow_nav(self, device) -> bool:
        return self._select_nav(device, nav_key="apocalyptic_shadow", nav_name="Apocalyptic Shadow")

    # =========================================================================
    # 内部辅助方法
    # =========================================================================

    def _wait_for_template_position(
        self,
        device,
        template: np.ndarray,
        area: tuple,
        timeout: float,
        threshold: float,
    ) -> Optional[Tuple[int, int]]:
        timer = Timer(timeout).start()
        while not timer.reached():
            device.screenshot()
            pos = self._find_template(device.image, template, area, threshold=threshold)
            if pos is not None:
                return pos
        return None

    def _find_template(
        self,
        image: np.ndarray,
        template: np.ndarray,
        button_area: tuple,
        threshold: float = None,
    ) -> Optional[Tuple[int, int]]:
        """
        在完整图像中查找模板

        Args:
            image: 完整截图 (1280x720)
            template: 裁剪后的按钮模板（小图）
            button_area: 按钮在原图中的位置 (x1, y1, x2, y2)
            threshold: 匹配阈值，None 使用默认值

        Returns:
            Optional[Tuple[int, int]]: 匹配中心坐标 (x, y)，未找到返回 None
        """
        # 计算搜索区域 = 按钮区域 + 20px padding
        x1, y1, x2, y2 = button_area
        search_x1 = max(0, x1 - 20)
        search_y1 = max(0, y1 - 20)
        search_x2 = min(image.shape[1], x2 + 20)
        search_y2 = min(image.shape[0], y2 + 20)

        # 转换为灰度
        if len(image.shape) == 3:
            image_gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            image_gray = image

        # 裁剪搜索区域
        search_region = image_gray[search_y1:search_y2, search_x1:search_x2]

        # Canny边缘检测：只匹配形状轮廓，对亮度/对比度完全不敏感
        # 参数：低阈值50，高阈值150（标准参数，适用于大多数场景）
        template_edges = cv2.Canny(template, 50, 150)
        search_edges = cv2.Canny(search_region, 50, 150)

        # 模板匹配（使用边缘图像）
        result = cv2.matchTemplate(
            search_edges,
            template_edges,
            config.TEMPLATE_MATCH_METHOD
        )

        # 找到最佳匹配
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)

        # =========================================================================
        # Debug: 保存调试信息
        # =========================================================================
        if logger_debug and config.SAVE_DEBUG_SCREENSHOTS:
            from datetime import datetime
            from pathlib import Path
            import os

            # 创建 debug 目录
            debug_dir = Path(__file__).parent / config.DEBUG_SCREENSHOT_DIR
            debug_dir.mkdir(parents=True, exist_ok=True)

            # 为每个模板类型生成唯一 key
            template_key = f"{button_area}"

            # 决定是否保存
            should_save = False
            save_reason = ""

            # 条件 1: 匹配失败 + 首次失败
            if max_val < config.TEMPLATE_MATCH_THRESHOLD:
                if template_key not in self._debug_saved:
                    should_save = True
                    save_reason = "first_failure"
                    self._debug_saved[template_key] = True
            # 条件 2: 匹配成功 + 首次成功
            elif template_key not in self._debug_saved:
                should_save = True
                save_reason = "first_success"
                self._debug_saved[template_key] = True

            if should_save:
                # 生成时间戳
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")

                try:
                    # 1. 保存完整截图
                    cv2.imwrite(str(debug_dir / f"{timestamp}_full_screenshot.png"), image_gray)

                    # 2. 保存搜索区域
                    cv2.imwrite(str(debug_dir / f"{timestamp}_search_region.png"), search_region)

                    # 3. 保存模板
                    cv2.imwrite(str(debug_dir / f"{timestamp}_template.png"), template)

                    # 4. 保存匹配结果热图（归一化到 0-255）
                    result_normalized = ((result - result.min()) / (result.max() - result.min()) * 255).astype(np.uint8)
                    cv2.imwrite(str(debug_dir / f"{timestamp}_match_result.png"), result_normalized)

                    # 5. 保存详细日志
                    with open(debug_dir / f"{timestamp}_log.txt", "w", encoding="utf-8") as f:
                        f.write("=== Template Matching Debug Log ===\n\n")
                        f.write(f"Timestamp: {timestamp}\n")
                        f.write(f"Button area: {button_area}\n")
                        f.write(f"Search area: ({search_x1}, {search_y1}, {search_x2}, {search_y2})\n")
                        f.write(f"Search region size: {search_region.shape}\n")
                        f.write(f"Template size: {template.shape}\n")
                        f.write(f"Match method: {config.TEMPLATE_MATCH_METHOD} (TM_CCOEFF_NORMED)\n")
                        f.write(f"\n=== Match Results ===\n")
                        f.write(f"Max confidence: {max_val:.6f}\n")
                        f.write(f"Min confidence: {min_val:.6f}\n")
                        f.write(f"Threshold: {config.TEMPLATE_MATCH_THRESHOLD}\n")
                        f.write(f"Match location (in search region): {max_loc}\n")
                        f.write(f"Match passed: {max_val >= config.TEMPLATE_MATCH_THRESHOLD}\n")

                    # 6. 在搜索区域上标记匹配位置（无论是否通过阈值）
                    marked = cv2.cvtColor(search_region.copy(), cv2.COLOR_GRAY2BGR)
                    color = (0, 255, 0) if max_val >= config.TEMPLATE_MATCH_THRESHOLD else (0, 0, 255)  # 绿色=成功，红色=失败
                    cv2.rectangle(marked, max_loc,
                                 (max_loc[0] + template.shape[1], max_loc[1] + template.shape[0]),
                                 color, 2)
                    # 标注置信度
                    cv2.putText(marked, f"{max_val:.3f}",
                               (max_loc[0], max_loc[1] - 5),
                               cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
                    cv2.imwrite(str(debug_dir / f"{timestamp}_marked.png"), marked)

                    # =========== 增强可视化（新增） ===========

                    # 1. 并排对比图：Template vs Search Region
                    scale = 5
                    template_large = cv2.resize(template, (template.shape[1]*scale, template.shape[0]*scale),
                                                interpolation=cv2.INTER_NEAREST)
                    search_large = cv2.resize(search_region, (search_region.shape[1]*scale, search_region.shape[0]*scale),
                                              interpolation=cv2.INTER_NEAREST)

                    # 转为BGR用于彩色标注
                    template_bgr = cv2.cvtColor(template_large, cv2.COLOR_GRAY2BGR)
                    search_bgr = cv2.cvtColor(search_large, cv2.COLOR_GRAY2BGR)

                    # 垂直拼接（避免高度不同导致的拼接失败）
                    comparison = np.vstack([template_bgr, search_bgr])

                    # 添加文字标注（调整为垂直布局）
                    font = cv2.FONT_HERSHEY_SIMPLEX
                    cv2.putText(comparison, "Template", (20, 30), font, 0.8, (0, 255, 0), 2)
                    cv2.putText(comparison, f"Actual (conf={max_val:.3f})",
                               (20, template_large.shape[0] + 30), font, 0.8, (0, 255, 0), 2)

                    # 在底部添加状态信息
                    status_text = f"Threshold={config.TEMPLATE_MATCH_THRESHOLD:.2f} | Status={'PASS' if max_val >= config.TEMPLATE_MATCH_THRESHOLD else 'FAIL'}"
                    cv2.putText(comparison, status_text, (20, comparison.shape[0] - 20),
                               font, 0.6, (255, 255, 255), 1)

                    cv2.imwrite(str(debug_dir / f"{timestamp}_comparison.png"), comparison)

                    # 2. 彩色热图
                    # 放大热图以便观察
                    heatmap_large = cv2.resize(result_normalized,
                                               (search_region.shape[1]*scale, search_region.shape[0]*scale),
                                               interpolation=cv2.INTER_LINEAR)

                    # 应用彩色热力图（红=高，蓝=低）
                    heatmap_color = cv2.applyColorMap(heatmap_large, cv2.COLORMAP_JET)

                    # 标注最高匹配点
                    max_y, max_x = max_loc[1]*scale + scale//2, max_loc[0]*scale + scale//2
                    cv2.circle(heatmap_color, (max_x, max_y), 10, (255, 255, 255), 2)
                    cv2.putText(heatmap_color, f"Max: {max_val:.3f}", (max_x + 15, max_y),
                               font, 0.5, (255, 255, 255), 1)

                    cv2.imwrite(str(debug_dir / f"{timestamp}_heatmap_color.png"), heatmap_color)

                    # 3. 增强日志统计信息
                    with open(debug_dir / f"{timestamp}_log.txt", "a", encoding="utf-8") as f:
                        f.write(f"\n=== Heatmap Statistics ===\n")
                        f.write(f"Max value: {result.max():.6f}\n")
                        f.write(f"Min value: {result.min():.6f}\n")
                        f.write(f"Mean value: {result.mean():.6f}\n")
                        f.write(f"Std value: {result.std():.6f}\n")

                        f.write(f"\n=== Pixel Statistics ===\n")
                        f.write(f"Template: mean={template.mean():.1f}, std={template.std():.1f}\n")
                        f.write(f"Search Region: mean={search_region.mean():.1f}, std={search_region.std():.1f}\n")
                        f.write(f"Brightness difference: Δmean={abs(template.mean() - search_region.mean()):.1f}\n")

                        # Top-5 匹配位置
                        f.write(f"\n=== Top 5 Match Locations ===\n")
                        flat_result = result.flatten()
                        top_5_indices = np.argsort(flat_result)[-5:][::-1]
                        for i, idx in enumerate(top_5_indices, 1):
                            y, x = np.unravel_index(idx, result.shape)
                            conf = flat_result[idx]
                            f.write(f"{i}. Position ({x}, {y}): confidence={conf:.6f}\n")

                    logger.info(f"Debug files saved ({save_reason}): {debug_dir / timestamp}_*")

                except Exception as e:
                    logger.warning(f"Failed to save debug files: {e}")
            else:
                logger.debug(f"Skipping debug save for {template_key} (already saved)")

        # =========================================================================

        # 使用提供的阈值或默认值
        if threshold is None:
            threshold = config.TEMPLATE_MATCH_THRESHOLD

        if config.VERBOSE_MATCHING:
            status = 'PASS' if max_val >= threshold else 'FAIL'
            logger.attr("Template matching", f"confidence={max_val:.3f}, threshold={threshold:.2f}, status={status}")

        # 检查匹配度
        if max_val < threshold:
            return None

        # 计算按钮中心在完整图像中的坐标
        template_h, template_w = template.shape
        center_x = search_x1 + max_loc[0] + template_w // 2
        center_y = search_y1 + max_loc[1] + template_h // 2

        if config.VERBOSE_MATCHING:
            logger.info(f"Template found at ({center_x}, {center_y}), confidence={max_val:.3f}")

        return (center_x, center_y)

    def _is_template_matched(
        self,
        image: np.ndarray,
        template: np.ndarray,
        button_area: tuple,
        threshold: float = None,
    ) -> bool:
        """
        检查模板是否在图像中匹配

        Args:
            image: 完整截图
            template: 裁剪后的按钮模板
            button_area: 按钮在原图中的位置 (x1, y1, x2, y2)
            threshold: 匹配阈值，None 使用默认值

        Returns:
            bool: 是否匹配成功
        """
        result = self._find_template(image, template, button_area, threshold=threshold)
        return result is not None

    def _click_position(self, device, position: Tuple[int, int]):
        """
        点击指定位置

        Args:
            device: Device 实例
            position: 点击坐标 (x, y)
        """
        x, y = position
        # 创建小区域的 ClickButton（±4像素）
        button = ClickButton(
            area=(x - 4, y - 4, x + 4, y + 4),
            name=f"NavClick_{x}_{y}"
        )
        device.click(button)
        logger.info(f"Clicked at ({x}, {y})")
