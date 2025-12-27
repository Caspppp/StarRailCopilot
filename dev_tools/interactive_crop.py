"""
交互式截图裁剪工具

功能：
1. 连接模拟器截图
2. 鼠标框选区域
3. 滚轮缩放、右键拖动
4. 自动保存裁剪图片
5. 显示坐标信息

用法：
    python -m dev_tools.interactive_crop
    python -m dev_tools.interactive_crop --serial 127.0.0.1:16384
    python -m dev_tools.interactive_crop --image path/to/screenshot.png

快捷键：
    鼠标左键拖动 - 框选区域
    拖动框的边缘 - 调整框大小
    拖动框内部   - 移动框位置
    鼠标右键拖动 - 平移视图
    滚轮         - 缩放视图
    F3/F5       - 刷新截图
    S           - 保存当前裁剪
    T           - 保存为黑色背景模板（适用于SRC项目）
    C           - 复制坐标到剪贴板
    R           - 重置选择
    0           - 重置缩放（适应窗口）
    Q/ESC       - 退出
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

# 添加项目根目录到路径
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


class InteractiveCropper:
    def __init__(self, serial=None, config_name=None, image_path=None):
        self.serial = serial
        self.config_name = config_name
        self.image_path = image_path
        self.device = None
        self.image = None  # 原始图像
        self.display_image = None  # 显示用图像

        # 框选状态
        self.drawing = False
        self.start_point = None  # 原始图像坐标
        self.end_point = None    # 原始图像坐标
        self.crop_area = None

        # 调整框的状态
        self.resize_mode = None  # None, 'move', 'left', 'right', 'top', 'bottom', 'tl', 'tr', 'bl', 'br'
        self.resize_start_point = None  # 开始调整时的鼠标位置（图像坐标）
        self.resize_original_area = None  # 开始调整时的框区域

        # 视图状态
        self.scale = 1.0
        self.offset_x = 0  # 平移偏移
        self.offset_y = 0
        self.panning = False
        self.pan_start = None

        self.save_dir = ROOT / "screenshots" / "crops"
        self.save_dir.mkdir(parents=True, exist_ok=True)

        self.window_name = "Interactive Crop - H for help"
        self.window_width = 1400
        self.window_height = 800

    def connect_device(self):
        """连接模拟器"""
        if self.image_path:
            print(f"[INFO] 从文件加载: {self.image_path}")
            self.image = cv2.imread(self.image_path)
            if self.image is None:
                raise FileNotFoundError(f"无法读取图片: {self.image_path}")
            return

        try:
            from module.device.device import Device
            from module.config.config import AzurLaneConfig

            if self.config_name:
                config = AzurLaneConfig(self.config_name)
            else:
                config_dir = ROOT / "config"
                configs = list(config_dir.glob("*.json"))
                if configs:
                    config_name = configs[0].stem
                    print(f"[INFO] 使用配置: {config_name}")
                    config = AzurLaneConfig(config_name)
                else:
                    raise RuntimeError("未找到配置文件")

            if self.serial:
                config.Emulator_Serial = self.serial

            self.device = Device(config)
            print(f"[INFO] 已连接设备: {config.Emulator_Serial}")
        except Exception as e:
            print(f"[ERROR] 连接设备失败: {e}")
            print("[INFO] 请使用 --image 参数指定截图文件")
            raise

    def take_screenshot(self):
        """截取屏幕"""
        if self.image_path:
            self.image = cv2.imread(self.image_path)
        elif self.device:
            self.device.screenshot()
            self.image = cv2.cvtColor(np.array(self.device.image), cv2.COLOR_RGB2BGR)

        # 重置视图
        self.reset_view()
        print(f"[INFO] 截图完成: {self.image.shape[1]}x{self.image.shape[0]}")

    def reset_view(self):
        """重置视图到适应窗口"""
        if self.image is None:
            return
        h, w = self.image.shape[:2]
        scale_w = self.window_width / w
        scale_h = self.window_height / h
        self.scale = min(scale_w, scale_h, 1.0)  # 不超过100%
        self.offset_x = 0
        self.offset_y = 0

    def screen_to_image(self, sx, sy):
        """屏幕坐标转图像坐标"""
        ix = int((sx - self.offset_x) / self.scale)
        iy = int((sy - self.offset_y) / self.scale)
        # 限制在图像范围内
        h, w = self.image.shape[:2]
        ix = max(0, min(ix, w - 1))
        iy = max(0, min(iy, h - 1))
        return ix, iy

    def image_to_screen(self, ix, iy):
        """图像坐标转屏幕坐标"""
        sx = int(ix * self.scale + self.offset_x)
        sy = int(iy * self.scale + self.offset_y)
        return sx, sy

    def detect_resize_mode(self, x, y):
        """检测鼠标位置，返回调整模式"""
        if not self.crop_area:
            return None

        ix, iy = self.screen_to_image(x, y)
        x1, y1, x2, y2 = self.crop_area

        # 边缘检测阈值（图像坐标）
        threshold = max(8, int(8 / self.scale))

        # 判断是否在角落
        near_left = abs(ix - x1) <= threshold
        near_right = abs(ix - x2) <= threshold
        near_top = abs(iy - y1) <= threshold
        near_bottom = abs(iy - y2) <= threshold

        if near_top and near_left:
            return 'tl'  # top-left
        if near_top and near_right:
            return 'tr'  # top-right
        if near_bottom and near_left:
            return 'bl'  # bottom-left
        if near_bottom and near_right:
            return 'br'  # bottom-right

        # 判断是否在边缘
        in_x_range = x1 <= ix <= x2
        in_y_range = y1 <= iy <= y2

        if near_left and in_y_range:
            return 'left'
        if near_right and in_y_range:
            return 'right'
        if near_top and in_x_range:
            return 'top'
        if near_bottom and in_x_range:
            return 'bottom'

        # 判断是否在框内部
        if in_x_range and in_y_range:
            return 'move'

        return None

    def mouse_callback(self, event, x, y, flags, param):
        """鼠标回调"""

        # 右键拖动 - 平移
        if event == cv2.EVENT_RBUTTONDOWN:
            self.panning = True
            self.pan_start = (x, y)
            return

        if event == cv2.EVENT_RBUTTONUP:
            self.panning = False
            self.pan_start = None
            return

        # 左键按下
        if event == cv2.EVENT_LBUTTONDOWN:
            # 先检测是否要调整现有框
            mode = self.detect_resize_mode(x, y)
            if mode:
                self.resize_mode = mode
                self.resize_start_point = self.screen_to_image(x, y)
                self.resize_original_area = self.crop_area
            else:
                # 开始新的框选
                self.drawing = True
                self.start_point = self.screen_to_image(x, y)
                self.end_point = self.start_point
                self.crop_area = None
            self.update_display()
            return

        # 左键释放
        if event == cv2.EVENT_LBUTTONUP:
            if self.drawing:
                self.drawing = False
                self.end_point = self.screen_to_image(x, y)
                self.update_crop_area()
                self.update_display()
            elif self.resize_mode:
                self.resize_mode = None
                self.resize_start_point = None
                self.resize_original_area = None
                self.update_display()
            return

        # 鼠标移动
        if event == cv2.EVENT_MOUSEMOVE:
            if self.panning and self.pan_start:
                # 平移视图
                dx = x - self.pan_start[0]
                dy = y - self.pan_start[1]
                self.offset_x += dx
                self.offset_y += dy
                self.pan_start = (x, y)
                self.update_display()
            elif self.drawing:
                # 绘制新框
                self.end_point = self.screen_to_image(x, y)
                self.update_display()
            elif self.resize_mode:
                # 调整现有框
                self._handle_resize(x, y)
                self.update_display()
            return

        # 滚轮缩放 - macOS 可能使用不同的事件
        if event == cv2.EVENT_MOUSEWHEEL:
            self._do_zoom(x, y, flags > 0)
            return

        # macOS 上的滚轮可能是这些事件
        if event == 10:  # 某些系统上的滚轮事件
            self._do_zoom(x, y, flags > 0)
            return

    def _handle_resize(self, x, y):
        """处理框的调整"""
        if not self.resize_mode or not self.resize_original_area:
            return

        ix, iy = self.screen_to_image(x, y)
        ox1, oy1, ox2, oy2 = self.resize_original_area
        start_ix, start_iy = self.resize_start_point

        # 计算移动距离
        dx = ix - start_ix
        dy = iy - start_iy

        # 根据模式调整框
        x1, y1, x2, y2 = ox1, oy1, ox2, oy2

        if self.resize_mode == 'move':
            # 移动整个框
            x1 += dx
            x2 += dx
            y1 += dy
            y2 += dy
        elif self.resize_mode == 'left':
            x1 = ox1 + dx
        elif self.resize_mode == 'right':
            x2 = ox2 + dx
        elif self.resize_mode == 'top':
            y1 = oy1 + dy
        elif self.resize_mode == 'bottom':
            y2 = oy2 + dy
        elif self.resize_mode == 'tl':
            x1 = ox1 + dx
            y1 = oy1 + dy
        elif self.resize_mode == 'tr':
            x2 = ox2 + dx
            y1 = oy1 + dy
        elif self.resize_mode == 'bl':
            x1 = ox1 + dx
            y2 = oy2 + dy
        elif self.resize_mode == 'br':
            x2 = ox2 + dx
            y2 = oy2 + dy

        # 限制在图像范围内
        h, w = self.image.shape[:2]
        x1 = max(0, min(x1, w - 1))
        x2 = max(0, min(x2, w - 1))
        y1 = max(0, min(y1, h - 1))
        y2 = max(0, min(y2, h - 1))

        # 确保顺序正确
        if x1 > x2:
            x1, x2 = x2, x1
        if y1 > y2:
            y1, y2 = y2, y1

        # 最小尺寸限制
        if x2 - x1 < 5:
            x2 = x1 + 5
        if y2 - y1 < 5:
            y2 = y1 + 5

        self.crop_area = (x1, y1, x2, y2)
        self.start_point = (x1, y1)
        self.end_point = (x2, y2)

    def _do_zoom(self, x, y, zoom_in):
        """执行缩放"""
        old_scale = self.scale

        if zoom_in:
            self.scale *= 1.2
        else:
            self.scale /= 1.2

        # 限制缩放范围：10% ~ 2000%
        self.scale = max(0.1, min(self.scale, 20.0))

        # 调整偏移以保持鼠标位置不变
        scale_ratio = self.scale / old_scale
        self.offset_x = x - (x - self.offset_x) * scale_ratio
        self.offset_y = y - (y - self.offset_y) * scale_ratio

        self.update_display()

    def update_crop_area(self):
        """更新裁剪区域"""
        if self.start_point and self.end_point:
            x1 = min(self.start_point[0], self.end_point[0])
            y1 = min(self.start_point[1], self.end_point[1])
            x2 = max(self.start_point[0], self.end_point[0])
            y2 = max(self.start_point[1], self.end_point[1])
            self.crop_area = (x1, y1, x2, y2)

    def update_display(self):
        """更新显示"""
        if self.image is None:
            return

        # 创建画布
        canvas = np.zeros((self.window_height, self.window_width, 3), dtype=np.uint8)
        canvas[:] = (40, 40, 40)  # 深灰色背景

        # 计算可见区域在原图中的位置
        h, w = self.image.shape[:2]

        # 原图中的可见区域
        img_x1 = max(0, int(-self.offset_x / self.scale))
        img_y1 = max(0, int(-self.offset_y / self.scale))
        img_x2 = min(w, int((self.window_width - self.offset_x) / self.scale))
        img_y2 = min(h, int((self.window_height - self.offset_y) / self.scale))

        if img_x2 <= img_x1 or img_y2 <= img_y1:
            # 没有可见区域
            cv2.imshow(self.window_name, canvas)
            return

        # 只裁剪并缩放可见部分
        visible_img = self.image[img_y1:img_y2, img_x1:img_x2]

        new_w = int((img_x2 - img_x1) * self.scale)
        new_h = int((img_y2 - img_y1) * self.scale)

        if new_w > 0 and new_h > 0:
            # 高倍缩放时使用最近邻插值（更快）
            interp = cv2.INTER_NEAREST if self.scale > 5.0 else cv2.INTER_LINEAR
            scaled = cv2.resize(visible_img, (new_w, new_h), interpolation=interp)
        else:
            cv2.imshow(self.window_name, canvas)
            return

        # 计算放置位置
        ox = int(self.offset_x + img_x1 * self.scale)
        oy = int(self.offset_y + img_y1 * self.scale)

        # 计算实际绘制区域
        dst_x1 = max(0, ox)
        dst_y1 = max(0, oy)
        dst_x2 = min(self.window_width, ox + new_w)
        dst_y2 = min(self.window_height, oy + new_h)

        src_x1 = max(0, -ox)
        src_y1 = max(0, -oy)
        src_x2 = src_x1 + (dst_x2 - dst_x1)
        src_y2 = src_y1 + (dst_y2 - dst_y1)

        if dst_x2 > dst_x1 and dst_y2 > dst_y1:
            canvas[dst_y1:dst_y2, dst_x1:dst_x2] = scaled[src_y1:src_y2, src_x1:src_x2]

        # 绘制选框
        if self.start_point and self.end_point:
            sp = self.image_to_screen(*self.start_point)
            ep = self.image_to_screen(*self.end_point)

            # 绘制框线
            cv2.rectangle(canvas, sp, ep, (0, 255, 0), 2)

            # 如果有完整的框，绘制调整点
            if self.crop_area:
                x1, y1, x2, y2 = self.crop_area

                # 四个角点
                corners = [
                    (x1, y1), (x2, y1),  # 左上、右上
                    (x1, y2), (x2, y2),  # 左下、右下
                ]

                # 四条边的中点
                midpoints = [
                    ((x1 + x2) // 2, y1),  # 上边中点
                    ((x1 + x2) // 2, y2),  # 下边中点
                    (x1, (y1 + y2) // 2),  # 左边中点
                    (x2, (y1 + y2) // 2),  # 右边中点
                ]

                # 绘制控制点
                handle_size = max(4, int(4 / self.scale))
                for px, py in corners + midpoints:
                    sx, sy = self.image_to_screen(px, py)
                    cv2.circle(canvas, (sx, sy), 5, (0, 255, 255), -1)  # 黄色实心圆
                    cv2.circle(canvas, (sx, sy), 5, (0, 200, 0), 2)     # 绿色边框

            # 显示坐标信息
            x1 = min(self.start_point[0], self.end_point[0])
            y1 = min(self.start_point[1], self.end_point[1])
            x2 = max(self.start_point[0], self.end_point[0])
            y2 = max(self.start_point[1], self.end_point[1])

            coord_text = f"area=({x1}, {y1}, {x2}, {y2})"
            # 修正尺寸显示：包含右下角像素，所以宽度是 x2-x1+1
            size_text = f"size: {x2-x1+1}x{y2-y1+1}"
        else:
            coord_text = "Left-click drag to select"
            size_text = ""

        # 信息面板
        cv2.rectangle(canvas, (10, 10), (450, 105), (0, 0, 0), -1)
        cv2.rectangle(canvas, (10, 10), (450, 105), (100, 100, 100), 1)
        cv2.putText(canvas, coord_text, (20, 35),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 0), 2)
        cv2.putText(canvas, size_text, (20, 60),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 0), 2)
        cv2.putText(canvas, f"Zoom: {self.scale*100:.0f}%  |  S=save  T=template  H=help", (20, 95),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180, 180, 180), 1)

        self.display_image = canvas
        cv2.imshow(self.window_name, canvas)

    def save_crop(self, filename=None):
        """保存裁剪图片"""
        if not self.crop_area:
            print("[WARN] 请先框选区域")
            return None

        x1, y1, x2, y2 = self.crop_area
        # 修复：Python切片是左闭右开，需要+1才能包含右下角像素
        cropped = self.image[y1:y2+1, x1:x2+1]

        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"crop_{timestamp}.png"

        save_path = self.save_dir / filename
        cv2.imwrite(str(save_path), cropped)
        print(f"[INFO] 已保存: {save_path}")
        print(f"[INFO] 坐标: area=({x1}, {y1}, {x2}, {y2})")
        print(f"[INFO] 尺寸: {x2-x1+1}x{y2-y1+1}")
        return save_path

    def save_template_crop(self, filename=None):
        """保存为黑色背景模板（SRC项目模板格式）"""
        if not self.crop_area:
            print("[WARN] 请先框选区域")
            return None

        x1, y1, x2, y2 = self.crop_area

        # 创建与原图相同大小的黑色背景
        h, w = self.image.shape[:2]
        template = np.zeros((h, w, 3), dtype=np.uint8)

        # 将裁剪区域复制到黑色背景上（修复像素问题）
        template[y1:y2+1, x1:x2+1] = self.image[y1:y2+1, x1:x2+1]

        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"template_{timestamp}.png"

        # 保存到 screenshots/templates 目录
        template_dir = ROOT / "screenshots" / "templates"
        template_dir.mkdir(parents=True, exist_ok=True)
        save_path = template_dir / filename

        cv2.imwrite(str(save_path), template)
        print(f"[INFO] 已保存模板: {save_path}")
        print(f"[INFO] 坐标: area=({x1}, {y1}, {x2}, {y2})")
        print(f"[INFO] 裁剪区域尺寸: {x2-x1+1}x{y2-y1+1}")
        print(f"[INFO] 模板总尺寸: {w}x{h} (黑色背景)")
        return save_path

    def copy_coords_to_clipboard(self):
        """复制坐标到剪贴板"""
        if not self.crop_area:
            print("[WARN] 请先框选区域")
            return

        x1, y1, x2, y2 = self.crop_area
        coord_str = f"area=({x1}, {y1}, {x2}, {y2})"

        try:
            import subprocess
            process = subprocess.Popen(['pbcopy'], stdin=subprocess.PIPE)
            process.communicate(coord_str.encode('utf-8'))
            print(f"[INFO] 已复制到剪贴板: {coord_str}")
        except Exception as e:
            print(f"[WARN] 复制失败: {e}")
            print(f"[INFO] 坐标: {coord_str}")

    def show_help(self):
        """显示帮助"""
        help_text = """
╔═══════════════════════════════════════════════════╗
║          Interactive Crop 帮助                    ║
╠═══════════════════════════════════════════════════╣
║  鼠标左键拖动  - 框选区域                         ║
║  拖动框的边缘  - 调整框大小                       ║
║  拖动框内部    - 移动框位置                       ║
║  鼠标右键拖动  - 平移视图                         ║
║  滚轮 / +/-   - 缩放视图                          ║
║  F5 / 5      - 刷新截图                           ║
║  S           - 保存裁剪图片                       ║
║  T           - 保存为黑色背景模板（SRC项目）      ║
║  C           - 复制坐标到剪贴板                   ║
║  P           - 打印当前坐标                       ║
║  R           - 重置选择                           ║
║  0           - 重置缩放（适应窗口）               ║
║  H           - 显示帮助                           ║
║  Q / ESC     - 退出                               ║
╚═══════════════════════════════════════════════════╝
"""
        print(help_text)

    def run(self):
        """主循环"""
        self.connect_device()
        self.take_screenshot()

        cv2.namedWindow(self.window_name, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(self.window_name, self.window_width, self.window_height)
        cv2.setMouseCallback(self.window_name, self.mouse_callback)

        self.update_display()

        print("\n[INFO] 工具已启动，按 H 查看帮助")
        self.show_help()

        while True:
            key = cv2.waitKey(50) & 0xFF

            if key == ord('q') or key == 27:  # Q or ESC
                break
            elif key == ord('h'):
                self.show_help()
            elif key == ord('s'):
                self.save_crop()
            elif key == ord('t'):
                self.save_template_crop()
            elif key == ord('c'):
                self.copy_coords_to_clipboard()
            elif key == ord('p'):
                if self.crop_area:
                    print(f"[INFO] 当前坐标: area={self.crop_area}")
                else:
                    print("[WARN] 请先框选区域")
            elif key == ord('r'):
                self.start_point = None
                self.end_point = None
                self.crop_area = None
                self.update_display()
                print("[INFO] 已重置选择")
            elif key == ord('0'):
                self.reset_view()
                self.update_display()
                print("[INFO] 已重置缩放")
            elif key == ord('=') or key == ord('+'):  # 放大
                center_x = self.window_width // 2
                center_y = self.window_height // 2
                self._do_zoom(center_x, center_y, True)
            elif key == ord('-'):  # 缩小
                center_x = self.window_width // 2
                center_y = self.window_height // 2
                self._do_zoom(center_x, center_y, False)
            elif key == 194 or key == ord('5'):  # F5
                print("[INFO] 刷新截图...")
                self.take_screenshot()
                self.start_point = None
                self.end_point = None
                self.crop_area = None
                self.update_display()

        cv2.destroyAllWindows()
        print("[INFO] 已退出")


def main():
    parser = argparse.ArgumentParser(description="交互式截图裁剪工具")
    parser.add_argument("--serial", "-s", help="模拟器地址，如 127.0.0.1:16384")
    parser.add_argument("--config", "-c", help="配置文件名")
    parser.add_argument("--image", "-i", help="直接加载图片文件")
    args = parser.parse_args()

    cropper = InteractiveCropper(
        serial=args.serial,
        config_name=args.config,
        image_path=args.image,
    )
    cropper.run()


if __name__ == "__main__":
    main()
