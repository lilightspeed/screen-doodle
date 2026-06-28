# Screen Doodle — 屏幕涂鸦工具

一款轻量级的 Windows 屏幕涂鸦工具，通过全局快捷键随时唤出画笔，在屏幕任意位置自由手绘 / 标注 / 打草稿。类似 ZoomIt 的批注功能或 Epic Pen，但更轻量、开源、可自定。

![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue) ![PySide6](https://img.shields.io/badge/GUI-PySide6-41cd52) ![License](https://img.shields.io/badge/license-MIT-green)

---

## 功能一览

| 功能 | 说明 |
|------|------|
| **全局热键唤出** | 默认 `Ctrl+Shift+D`，可配置 |
| **透明画布** | 全屏透明覆盖层，多显示器支持 |
| **鼠标穿透** | 空闲时鼠标事件完全穿透窗口，不干扰操作 |
| **自由手绘** | 鼠标拖拽绘制，支持速度感应粗细变化 |
| **荧光笔** | 半透明粗笔触，适合标注高亮 |
| **橡皮擦** | 擦除部分或全部笔迹，带实时预览圆环 |
| **撤销 / 重做** | `Ctrl+Z` / `Ctrl+Y` 管理笔迹历史及选区移动 |
| **套索选择 / 移动** | 自由绘制套索选区，选中笔迹可拖拽移动，跨越边界的笔迹自动切分 |
| **16 色调色板** | 预设色板 + 自定义拾色器 |
| **笔刷 / 橡皮擦大小** | 独立滑块分别调节 |
| **设置持久化** | 自动保存工具状态与工具栏位置 |
| **系统托盘** | 后台常驻，托盘菜单切换 / 退出 |

---

## 快速开始

### 环境要求

- Windows 10 / 11
- Python 3.12+

### 安装与运行

```bash
# 克隆仓库
git clone https://github.com/lilightspeed/screen-doodle.git
cd screen-doodle

# 安装依赖
pip install -r requirements.txt

# 启动
python main.py
```

### 启动脚本

Windows 下也可直接双击 `run.bat` 启动。

---

## 使用指南

### 基本操作

| 操作 | 说明 |
|------|------|
| `Ctrl+Shift+D` | 切换绘制 / 隐藏模式 |
| `Esc` | 退出绘制模式（回到隐藏） |
| `Ctrl+Z` | 撤销上一笔 |
| `Ctrl+Y` | 重做上一笔 |
| **左键拖拽** | 绘画 / 擦除 |
| **右键点击** 工具栏 | 切换工具 |

### 工具栏

悬浮半透明工具栏提供以下控制：

- **工具切换**：笔 / 荧光笔 / 橡皮擦
- **颜色选择**：16 色预设面板 + 自定义拾色器
- **笔刷大小**：滑块调节（1–50）
- **橡皮擦大小**：滑块调节（5–100）
- **隐藏**：最小化工具栏

### 状态切换

双击系统托盘图标或按 `Ctrl+Shift+D` 可在绘制与隐藏模式间切换。隐藏模式下鼠标事件完全穿透窗口，不干扰任何操作。

---

## 笔迹调优

项目根目录的 `setting.json` 可用于调节笔迹渲染参数，包括速度感应宽度变化和渲染品质。

**详细参数说明请参考 → [`docs/stroke_config_guide.md`](docs/stroke_config_guide.md)**

```json
{
  "_comment": "笔迹调优参数。修改后重启应用生效；删除此文件可重建默认值。",
  "velocity": {
    "sample_interval": 4,
    "smoothing_alpha": 0.35,
    "thin_mult": 0.4,
    "thick_mult": 2.5,
    "ref_dist": 15.0,
    "power_exponent": 1.5
  },
  "rendering": {
    "min_segment_width": 0.1,
    "aa_quality": 2,
    "preview_antialias": true,
    "preview_opacity": 1,
    "highlighter_opacity_scale": 0.23,
    "highlighter_width_scale": 4.0,
    "interpolation_segments": 2,
    "subdivision_pixel_gap": 4.0,
    "max_point_gap": 3.0,
    "max_densify_insert": 16
  }
}
```

---

## 技术架构

### 窗口层级

```
ToolBarWindow（悬浮工具栏，置顶）
  └─ OverlayWindow × N（每屏一个全屏透明覆盖层）
       └─ DrawingCanvas（QPainter 绘图区域）
            ├─ 背景层：alpha=3 填充 / 截屏底图
            └─ 笔迹层：临时 QPixmap 合成后叠放
```

### 鼠标命中测试

放弃 Qt 的 `WA_TransparentForMouseEvents`（在分层窗口上不可靠），使用 Win32 原生事件过滤：

1. **WM_NCHITTEST 拦截** — 绘制模式返回 `HTCLIENT`，隐藏模式返回 `HTTRANSPARENT`
2. **WS_EX_TRANSPARENT 直接操作** — `SetWindowLongW` 设置 / 清除扩展窗口样式
3. **Alpha 层保障** — 画布每个像素填 alpha=3，确保命中测试正确交付
4. **WM_SETCURSOR 拦截** — 强制十字光标，防止显示底层窗口 I-beam

### 热键方案

常驻热键（始终生效）：`Ctrl+Shift+D` 切换模式

绘制模式热键（进入时注册，退出时注销，`suppress=True`）：
- `Esc` — 退出绘制
- `Ctrl+Z` — 撤销
- `Ctrl+Y` — 重做

使用 `keyboard` 库监听全局热键，通过 `Signal()` 桥接到 Qt 主线程。

---

## 项目结构

```
ScreenDoodle/
├── main.py                      # 入口：启动应用 + 事件循环
├── requirements.txt             # 依赖清单
├── pyproject.toml               # 项目元数据
├── run.bat                      # Windows 启动脚本
├── setting.json                 # 笔迹调优参数（删除后自动重建）
├── screen_doodle/
│   ├── __init__.py
│   ├── app.py                   # QApplication 单例 + 全局热键 + 窗口协调 + 托盘
│   ├── overlay.py               # 透明全屏覆盖窗口（Win32 原生事件过滤）
│   ├── canvas.py                # QPainter 绘图画布（双层合成）
│   ├── toolbar.py               # 悬浮半透明工具栏（含色板弹出窗口）
│   ├── models.py                # Stroke 数据模型 + ToolType 枚举
│   ├── stroke_manager.py        # 笔迹管理（撤销/重做/清除）
│   └── renderer.py              # 笔迹渲染函数（与画布解耦）
├── resources/
│   └── icons/                   # （预留）工具栏图标
└── docs/
    └── stroke_config_guide.md   # 笔迹参数配置说明
```

### 模块职责

| 模块 | 职责 |
|------|------|
| `main.py` | 启用高 DPI 支持，启动 QApplication，创建 ScreenDoodleApp 实例 |
| `app.py` | `ScreenDoodleApp` 类：管理全局热键、多窗口生命周期、系统托盘、JSON 设置读写 |
| `overlay.py` | `OverlayWindow`：全屏透明窗口，Win32 原生事件过滤实现鼠标穿透 / 捕获切换 |
| `canvas.py` | `DrawingCanvas`：QWidget 子类，双层合成，鼠标事件处理，实时笔迹预览 |
| `toolbar.py` | `ToolBarWindow` + `ColorPalettePopup`：悬浮半透明工具栏 |
| `models.py` | `Stroke`(dataclass)、`ToolType`(Enum) 数据模型 |
| `stroke_manager.py` | `StrokeManager`：笔迹列表 + 撤销栈 / 重做栈 + 清除 |
| `renderer.py` | `render_stroke()`：QPainter 渲染单个笔迹，支持预览与擦除模式 |

---

## 依赖

```
PySide6>=6.6        # Qt 绑定
Pillow>=10.0        # 屏幕截图（预留）
keyboard>=0.13      # 全局热键
```

---

## 开发计划

### ✅ 已实现

- 全屏透明覆盖层（每显示器独立窗口）
- 全局热键 `Ctrl+Shift+D` 切换绘制 / 隐藏模式
- Win32 原生鼠标穿透 / 捕获
- 自由手绘（速度感应粗细、Catmull-Rom 平滑）
- 荧光笔模式
- 橡皮擦（CompositionMode_Clear 擦笔迹层）
- 撤销 / 重做 / 清除全部（含选区移动撤销）
- 套索选择 + 选区拖动移动（含边界笔画自动切分）
- 悬浮工具栏（拖拽、隐藏、设置持久化）
- 16 色预设面板 + 自定义拾色器
- 笔刷 / 橡皮擦大小独立滑块
- 系统托盘
- 多显示器支持（热插拔）
- 设置自动持久化（JSON）

### 🚧 规划中

- [ ] 截图底图（屏幕快照作背景）
- [ ] 辅助图形（直线、箭头、矩形、椭圆）
- [ ] 取色器
- [ ] 保存 / 导出为 PNG
- [ ] 快捷键提示覆盖层
- [ ] 设置 UI（热键重绑定等）
- [ ] Nuitka / PyInstaller 打包为单 exe

---

## 开发原则

- **轻量优先**：启动 < 1s，空闲内存 < 60MB
- **最少依赖**：核心仅 PySide6 + Pillow + keyboard
- **模块解耦**：画布、模型、管理、渲染各司其职，通过信号 / 接口通信
- **增量构建**：每阶段产出可运行的程序
- **纯 Python**：无需 C++ 扩展，降低构建复杂度

---

## 关键技术参考

- [PySide6 透明窗口示例](https://doc.qt.io/qtforpython-6/examples/example_widgets_widgets_windowflags.html)
- [Qt.WA_TransparentForMouseEvents](https://doc.qt.io/qt-6/qt.html#WidgetAttribute-enum)
- [QPainter 路径绘制](https://doc.qt.io/qtforpython-6/PySide6/QtGui/QPainterPath.html)
- [QPainter CompositionMode 擦除](https://doc.qt.io/qt-6/qpainter.html#CompositionMode-enum)
- [keyboard 全局热键](https://github.com/boppreh/keyboard)
- [PIL.ImageGrab 屏幕截图](https://pillow.readthedocs.io/en/stable/reference/ImageGrab.html)
- [SetWindowLong / WS_EX_TRANSPARENT](https://learn.microsoft.com/en-us/windows/win32/winmsg/window-styles)
- [WM_NCHITTEST 消息](https://learn.microsoft.com/en-us/windows/win32/inputdev/wm-nchittest)

---

## License

MIT
