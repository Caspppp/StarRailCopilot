# Template Processor - 模板处理工具

用于处理游戏 UI 按钮模板，自动识别和提取黑色背景中的按钮区域（符合 SRC 官方标准）。

## 快速开始

### 环境要求

**重要**: 本项目使用 conda 环境，所有 Python 脚本必须使用项目专用的 Python 解释器。

**Python 环境路径**: `/opt/anaconda3/envs/src/bin/python`

### 方法 1: 使用便捷脚本（推荐）

项目提供了便捷的 shell 脚本，自动使用正确的 Python 环境：

```bash
# 分析 screenshots/templates/ 下的所有模板
./tools/process_templates.sh

# 分析指定文件
./tools/process_templates.sh --file screenshots/templates/template_123.png

# 分析指定目录
./tools/process_templates.sh --dir path/to/templates

# 提取按钮并保存为单独文件
./tools/process_templates.sh --extract
```

### 方法 2: 使用 Claude Code 技能

直接在对话中调用技能：

```
/template-processor
```

或者：

```
帮我处理 screenshots/templates 下的新模板
```

Claude 会自动：
- 使用正确的 Python 环境 (`/opt/anaconda3/envs/src/bin/python`)
- 扫描模板目录
- 分析每个模板的属性（大小、背景类型）
- 提取按钮区域（如果是黑色背景）
- 建议命名规范
- 提供集成代码

### 方法 3: 直接使用 Python 脚本

如果需要手动调用，必须使用完整的 Python 路径：

```bash
# 正确 ✅
/opt/anaconda3/envs/src/bin/python tools/template_processor.py

# 错误 ❌ - 缺少依赖 (cv2, numpy)
python tools/template_processor.py
python3 tools/template_processor.py
```

## 输出示例

```
📂 Found 2 template(s) in screenshots/templates

📄 Template: template_20251221_004645.png
   Size: 1280x720
   Black ratio: 99.9%
   Background: ⬛ Black (SRC official format)
   Button area: (440, 95, 478, 135)
   Button size: 38x40
   ✅ Recommend: Use button extraction pattern
      (see tools/forgotten_hall_navigator/templates.py)

💡 Naming suggestions (replace [category] and [name]):
   Example: tab_treasures_lightward_check.png
   Example: nav_forgotten_hall_click.png
```

## 模板标准

### SRC 官方格式（黑色背景）

- **尺寸**: 1280x720 完整截图
- **背景**: 99%+ 黑色 (RGB 0,0,0)
- **按钮**: 占据小区域（例如 50x48 像素）
- **处理方式**: 自动提取按钮区域

**适用场景**:
- Tab 切换按钮（例如：逐光捡金、生存索引）
- Nav 二级导航按钮（例如：忘却之庭、虚构叙事）

**命名规范**:
```
{category}_{name}_{state}.png

例如：
- tab_treasures_lightward_check.png  (选中状态)
- tab_treasures_lightward_click.png  (未选中状态)
- nav_forgotten_hall_check.png       (选中状态)
- nav_forgotten_hall_click.png       (未选中状态)
```

### 普通格式（无黑色背景）

- **尺寸**: 任意
- **背景**: 游戏实际背景
- **处理方式**: 标准 cv2.matchTemplate

**适用场景**:
- 通用 UI 按钮
- 图标识别
- 状态标记

**命名规范**:
```
{category}_{name}.png

例如：
- button_confirm.png
- icon_star.png
- status_locked.png
```

## 集成示例

### 黑色背景模板（按钮提取模式）

```python
from pathlib import Path
import cv2
import numpy as np

class TemplateManager:
    def __init__(self):
        self.templates = {}
        self.button_areas = {}

    def _load_template(self, path: Path):
        """加载模板并自动提取按钮区域"""
        image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)

        # 找到非黑色像素
        non_zero_coords = np.argwhere(image > 10)
        y_min, x_min = non_zero_coords.min(axis=0)
        y_max, x_max = non_zero_coords.max(axis=0)

        # 添加 padding
        padding = 5
        y_min = max(0, y_min - padding)
        x_min = max(0, x_min - padding)
        y_max = min(image.shape[0], y_max + padding)
        x_max = min(image.shape[1], x_max + padding)

        # 裁剪按钮
        button_image = image[y_min:y_max, x_min:x_max]
        button_area = (x_min, y_min, x_max, y_max)

        return button_image, button_area

    def match_template(self, screenshot, template, button_area):
        """在搜索区域内匹配小按钮"""
        x1, y1, x2, y2 = button_area

        # 搜索区域 = button_area + 20px padding
        search_x1 = max(0, x1 - 20)
        search_y1 = max(0, y1 - 20)
        search_x2 = min(screenshot.shape[1], x2 + 20)
        search_y2 = min(screenshot.shape[0], y2 + 20)

        # 裁剪搜索区域
        search_region = screenshot[search_y1:search_y2, search_x1:search_x2]

        # 模板匹配
        result = cv2.matchTemplate(search_region, template, cv2.TM_CCOEFF_NORMED)
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)

        if max_val >= 0.75:  # 阈值
            # 计算按钮中心坐标
            center_x = search_x1 + max_loc[0] + template.shape[1] // 2
            center_y = search_y1 + max_loc[1] + template.shape[0] // 2
            return (center_x, center_y)

        return None
```

完整实现参考: `tools/forgotten_hall_navigator/templates.py`

### 普通模板（标准匹配模式）

```python
import cv2

def match_normal_template(screenshot, template, threshold=0.8):
    """标准模板匹配"""
    result = cv2.matchTemplate(screenshot, template, cv2.TM_CCOEFF_NORMED)
    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)

    if max_val >= threshold:
        # 返回匹配位置
        return max_loc

    return None
```

## 技术细节

### 为什么需要按钮提取？

SRC 官方模板是 1280x720 完整截图，其中 99.9% 是黑色背景：
- 直接匹配完整截图 → 黑色背景差异导致负匹配值 ❌
- 提取按钮区域后匹配 → 高置信度 (0.85-0.95) ✅

### 关键参数

| 参数 | 值 | 说明 |
|------|---|------|
| 黑色阈值 | 10 | 像素值 ≤ 10 视为黑色 |
| 黑色占比 | 90% | 黑色像素 ≥ 90% 视为黑色背景 |
| 边界 padding | 5px | 按钮边界扩展 5 像素 |
| 搜索 padding | 20px | 搜索区域扩展 20 像素 |
| 匹配阈值 | 0.75 | 提取按钮的推荐阈值 |
| 匹配方法 | TM_CCOEFF_NORMED | OpenCV 标准化相关系数匹配 |

## 常见问题

### Q: 如何判断是否需要按钮提取？

A: 运行 `python tools/template_processor.py --file <path>`，如果显示"Black (SRC official format)"则需要提取。

### Q: 提取后的按钮太小/太大？

A: 调整 `padding` 参数（默认 5px），或检查原始截图的按钮亮度（需要 > 10）。

### Q: 匹配失败（置信度低）？

A:
1. 检查游戏分辨率是否为 1280x720
2. 检查模板是否使用相同分辨率截图
3. 尝试调整阈值（0.70-0.85）
4. 检查 button_area 是否正确提取

## 参考

- 完整实现: `tools/forgotten_hall_navigator/`
- 上游标准: `module/base/button.py`, `dev_tools/button_extract.py`
- 项目文档: `.claude/CLAUDE.md`
