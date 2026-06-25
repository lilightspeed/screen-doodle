# Screen Doodle — 屏幕涂鸦工具

## 项目概述

一款轻量级的 Windows 屏幕涂鸦工具，通过全局快捷键随时唤出画笔，在屏幕任意位置自由手绘/标注/打草稿。类似 ZoomIt 的批注功能或 Epic Pen，但更轻量、开源、可自定。

**语言：** Python 3.12+
**GUI 框架：** PySide6 (Qt6)
**打包：** Nuitka / PyInstaller（单 exe 发布）

---

## 核心功能

| 功能 | 说明 |
|------|------|
| **全局热键唤出** | 默认 `Ctrl+Shift+D`，可配置 |
| **透明画布** | 全屏透明覆盖层，不遮挡桌面操作 |
| **鼠标穿透** | 空闲时鼠标事件穿透窗口，完全不干扰操作 |
| **自由手绘** | 鼠标拖拽绘制，支持压感 |
| **荧光笔** | 半透明粗笔触，适合标注 |
| **橡皮擦** | 擦除部分或全部笔迹 |
| **直线/箭头/矩形/椭圆** | 常用辅助图形 |
| **取色器** | 拾取屏幕任意位置颜色 |
| **截图底图** | 截取当前屏幕作为背景，在图上标注 |
| **撤销/重做** | 笔迹历史管理 |
| **调色板 + 笔刷大小** | 颜色选择器与粗细滑块 |
| **保存/导出** | 保存为 PNG（可含白色背景） |
| **多显示器支持** | 在所有显示器上绘制 |

---

## 项目结构

```
ScreenDoodle/
├── main.py                      # 入口：启动应用 + 注册热键
├── requirements.txt             # 依赖清单
├── pyproject.toml               # 项目元数据
├── screen_doodle/
│   ├── __init__.py
│   ├── app.py                   # QApplication 单例 + 全局热键管理
│   ├── overlay.py               # 透明全屏覆盖窗口（核心）
│   ├── toolbar.py               # 悬浮工具栏窗口
│   ├── canvas.py                # 自定义 QWidget 绘图画布
│   ├── models.py                # Stroke 数据模型 + ToolType 枚举
│   ├── stroke_manager.py        # 笔迹管理（撤销/重做/清除）
│   ├── capture_service.py       # 屏幕截图服务
│   └── export_service.py        # 保存/导出服务
├── resources/
│   ├── icons/                   # 工具栏图标 SVG
│   └── settings.json            # 用户配置持久化文件
└── docs/
    └── ARCHITECTURE.md
```

### 各模块职责

| 模块 | 职责 |
|------|------|
| `main.py` | 解析命令行参数，启动 QApplication，进入事件循环 |
| `app.py` | `ScreenDoodleApp` 类：管理全局热键（`keyboard` 库监听）、窗口生命周期、托盘图标 |
| `overlay.py` | `OverlayWindow`：全屏透明窗口，处理鼠标穿透/捕获切换，键盘事件转发 |
| `canvas.py` | `DrawingCanvas`：QWidget 子类，override `paintEvent`/`mouseEvent`，QPainter 渲染 |
| `toolbar.py` | `ToolBar`：悬浮半透明工具栏，画笔选择、颜色、粗细，发送信号给 canvas |
| `models.py` | `Stroke`(dataclass)：路径点列表 + 颜色 + 粗细 + 透明度 + 工具类型；`ToolType`(Enum) |
| `stroke_manager.py` | `StrokeManager`：笔迹列表 + 撤销栈/重做栈 + 清除 |
| `capture_service.py` | 调用 `PIL.ImageGrab.grab()` 截图，设为画布背景 |
| `export_service.py` | QPainter 将笔迹渲染到 QImage 并保存为 PNG |

---

## 架构设计

### 窗口层级

```
┌─────────────────────────────────────────────┐
│  ToolBarWindow（悬浮工具栏，独立 QWidget）    │
│  ┌─────────────────────────────────────────┐ │
│  │  OverlayWindow（全屏透明覆盖层）          │ │
│  │  ┌─────────────────────────────────────┐ │ │
│  │  │  DrawingCanvas（QPainter 绘图区域）   │ │ │
│  │  │  ┌─────────────────────────────────┐ │ │ │
│  │  │  │  截图背景（QPixmap，可选）       │ │ │ │
│  │  │  └─────────────────────────────────┘ │ │ │
│  │  └─────────────────────────────────────┘ │ │
│  └─────────────────────────────────────────┘ │
│  Frameless | TranslucentBackground | Topmost  │
│  ShowInTaskbar=False                           │
└─────────────────────────────────────────────┘
```

### 窗口状态机

```
                   按 Ctrl+Shift+D
    [隐藏模式] ──────────────────→ [绘制模式]
       │                              │
       │ 鼠标穿透（WS_EX_TRANSPARENT） │ 鼠标捕获
       │ 窗口透明（WA_TranslucentBg）  │ 显示工具栏
       │ 不显示工具栏                 │ 可绘制
       │                              │
       └──────────────────────────────────┘
        按 Ctrl+Shift+D / Esc 切回隐藏
```

### 笔迹数据模型

```python
@dataclass
class Stroke:
    points: list[QPointF]       # 路径控制点
    color: QColor               # 笔迹颜色
    width: float                # 笔刷大小
    opacity: float              # 透明度 (0.0 ~ 1.0)
    tool: ToolType              # Pen / Highlighter / Eraser / Shape

class ToolType(Enum):
    PEN = "pen"
    HIGHLIGHTER = "highlighter"
    ERASER = "eraser"
    LINE = "line"
    ARROW = "arrow"
    RECTANGLE = "rectangle"
    ELLIPSE = "ellipse"
```

### 绘图管道

```
用户鼠标事件 → DrawingCanvas 收集 QPointF 路径点
       ↓
Stroke 对象创建 → 加入 StrokeManager.list
       ↓
update() 触发 paintEvent → QPainter 遍历所有 Stroke
       ↓
       └─ 绘制路径 (drawPath)
       └─ 绘制形状 (drawRect / drawEllipse)
       └─ 实时预览当前笔迹（鼠标移动中）
```

### 热键方案

使用 `keyboard` 库监听全局热键，而非 Qt 内置的 QShortcut（Qt 的快捷键只在窗口聚焦时生效）：

```python
keyboard.add_hotkey("ctrl+shift+d", toggle_drawing_mode)
```

热键注册在 `app.py` 中统一管理。

---

## 依赖

```
PySide6>=6.6          # Qt 绑定
Pillow>=10.0          # 屏幕截图
keyboard>=0.13        # 全局热键
pynput>=1.7           # （备选）鼠标位置检测 / 取色器
nuitka                # 打包为单 exe
```

---

## 开发计划

### Phase 1 — 最小可用（MVP）
- [x] 项目骨架：目录结构 + requirements.txt + pyproject.toml
- [ ] `OverlayWindow`：全屏透明 + 置顶 + 无任务栏
- [ ] 全局热键 `Ctrl+Shift+D` 切换绘制/隐藏模式
- [ ] 鼠标穿透/捕获切换（`setAttribute(Qt.WA_TransparentForMouseEvents)`）
- [ ] `DrawingCanvas`：QPainter 基础手绘（固定颜色 + 粗细）
- [ ] `ToolBar`：悬浮半透明工具栏雏形（工具切换、颜色、粗细）

### Phase 2 — 核心功能
- [ ] 荧光笔模式（半透明 + 粗笔触）
- [ ] 橡皮擦
- [ ] `StrokeManager`：撤销 / 重做（Ctrl+Z / Ctrl+Y）
- [ ] 清除全部
- [ ] 调色板控件（预设色板 + 自定义 RGB）
- [ ] 笔刷大小滑块

### Phase 3 — 增强功能
- [ ] 屏幕截图底图（`PIL.ImageGrab.grab()`）
- [ ] 辅助图形：直线、箭头、矩形、椭圆
- [ ] 保存为 PNG（QImage 渲染 + 白底可选）
- [ ] 取色器（`pynput` 获取鼠标位置 → `PIL.ImageGrab` 取像素）

### Phase 4 — 打磨
- [ ] 多显示器支持（遍历 QScreen，每个屏幕建一个 OverlayWindow）
- [ ] 设置持久化（settings.json：热键、默认颜色、粗细等）
- [ ] 系统托盘图标（后台常驻，右键菜单退出）
- [ ] 快捷键提示覆盖层（长按热键显示帮助）
- [ ] Nuitka 打包为单 exe（`nuitka --onefile --windows-disable-console main.py`）

---

## 开发原则

- **轻量优先**：启动 < 1s，空闲内存 < 60MB
- **最少依赖**：核心仅 PySide6 + Pillow + keyboard，避免大而全的第三方库
- **模块解耦**：画布、模型、管理、服务各司其职，通过信号/接口通信
- **增量构建**：每阶段产出可运行的程序，不追求一步到位
- **纯 Python**：无需 C++ 扩展，降低构建复杂度

---

## 关键技术参考

- [PySide6 透明窗口示例](https://doc.qt.io/qtforpython-6/examples/example_widgets_widgets_windowflags.html)
- [Qt.WA_TransparentForMouseEvents](https://doc.qt.io/qt-6/qt.html#WidgetAttribute-enum)
- [QPainter 路径绘制](https://doc.qt.io/qtforpython-6/PySide6/QtGui/QPainterPath.html)
- [keyboard 全局热键](https://github.com/boppreh/keyboard)
- [PIL.ImageGrab 屏幕截图](https://pillow.readthedocs.io/en/stable/reference/ImageGrab.html)
- [Nuitka 打包指南](https://nuitka.net/doc/user-manual.html)
