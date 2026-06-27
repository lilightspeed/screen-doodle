# Screen Doodle — 屏幕涂鸦工具

## 项目概述

一款轻量级的 Windows 屏幕涂鸦工具，通过全局快捷键随时唤出画笔，在屏幕任意位置自由手绘/标注/打草稿。类似 ZoomIt 的批注功能或 Epic Pen，但更轻量、开源、可自定。

**语言：** Python 3.12+
**GUI 框架：** PySide6 (Qt6)
**打包规划：** Nuitka / PyInstaller（单 exe 发布）

---

## 核心功能

| 功能 | 说明 |
|------|------|
| **全局热键唤出** | 默认 `Ctrl+Shift+D`，可配置 |
| **透明画布** | 全屏透明覆盖层，多显示器支持 |
| **鼠标穿透** | 空闲时鼠标事件穿透窗口，完全不干扰操作 |
| **自由手绘** | 鼠标拖拽绘制 |
| **荧光笔** | 半透明粗笔触，适合标注 |
| **橡皮擦** | 擦除部分或全部笔迹，带实时预览圆环 |
| **撤销/重做** | Ctrl+Z / Ctrl+Y，笔迹历史管理 |
| **调色板 + 笔刷大小** | 16 色预设面板 + 自定义拾色器 + 粗细滑块 |
| **橡皮擦大小** | 独立于笔刷的粗细滑块 |
| **设置持久化** | 自动保存/恢复工具状态与工具栏位置 |
| **系统托盘** | 后台常驻，托盘菜单切换/退出 |
| **多显示器支持** | 遍历 QScreen，每个屏幕建一个 OverlayWindow |

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
└── docs/                        # 文档
```

### 各模块职责

| 模块 | 职责 |
|------|------|
| `main.py` | 启用高 DPI 支持，启动 QApplication，创建 ScreenDoodleApp 实例 |
| `app.py` | `ScreenDoodleApp` 类：管理全局热键（`keyboard` 库）、多窗口生命周期、系统托盘、JSON 设置读写 |
| `overlay.py` | `OverlayWindow`：全屏透明窗口，通过 Win32 原生事件过滤（WM_NCHITTEST）实现鼠标穿透/捕获切换 |
| `canvas.py` | `DrawingCanvas`：QWidget 子类，双层合成（背景层 + 笔迹层），鼠标事件处理，实时笔迹预览 |
| `toolbar.py` | `ToolBarWindow` + `ColorPalettePopup`：悬浮半透明工具栏，含工具切换/颜色/粗细滑块等；色板含 16 预设色 + 自定义拾色器 |
| `models.py` | `Stroke`(dataclass)：路径点列表 + 颜色 + 粗细 + 透明度 + 工具类型；`ToolType`(Enum)：PEN / HIGHLIGHTER / ERASER |
| `stroke_manager.py` | `StrokeManager`：笔迹列表 + 撤销栈/重做栈 + 清除，发射 data_changed 信号 |
| `renderer.py` | `render_stroke()` 函数：QPainter 渲染单个笔迹，支持预览透明度，支持 CompositionMode_Clear 擦除 |

---

## 架构设计

### 窗口层级

```
┌─────────────────────────────────────────────────┐
│  ToolBarWindow（悬浮工具栏，独立 QWidget，置顶）    │
│  ┌─────────────────────────────────────────────┐ │
│  │  OverlayWindow × N（每屏一个全屏透明覆盖层）   │ │
│  │  ┌─────────────────────────────────────────┐ │ │
│  │  │  DrawingCanvas（QPainter 绘图区域）       │ │ │
│  │  │  ┌─────────────────────────────────────┐ │ │ │
│  │  │  │  背景层：alpha=3 填充 / 截屏底图     │ │ │ │
│  │  │  │  笔迹层：临时 QPixmap 合成后叠放     │ │ │ │
│  │  │  └─────────────────────────────────────┘ │ │ │
│  │  └─────────────────────────────────────────┘ │ │
│  └─────────────────────────────────────────────┘ │
│  Frameless | TranslucentBackground | Tool         │
│  ShowInTaskbar=False | WindowDoesNotAcceptFocus   │
└─────────────────────────────────────────────────┘
```

### 窗口状态机

```
                   按 Ctrl+Shift+D / 双击托盘图标
    [隐藏模式] ─────────────────────────────────────→ [绘制模式]
       │                                                  │
       │ WS_EX_TRANSPARENT 设置                          │ WS_EX_TRANSPARENT 清除
       │ 窗口隐藏 (hide)                                  │ 窗口显示 (show + raise)
       │ 工具栏隐藏                                       │ 工具栏显示
       │ 模式热键注销                                     │ 模式热键注册（Esc / Ctrl+Z / Ctrl+Y）
       │                                                  │
       └──────────────────────────────────────────────────┘
             按 Ctrl+Shift+D / Esc / 工具栏"─"按钮
```

### 鼠标命中测试机制

放弃 Qt 的 `WA_TransparentForMouseEvents`（在分层窗口上不可靠），改为：

1. **Win32 原生事件过滤**：`_Win32HitTestFilter` 拦截 `WM_NCHITTEST` — 绘制模式返回 `HTCLIENT`（接收事件），隐藏模式返回 `HTTRANSPARENT`（穿透）
2. **WS_EX_TRANSPARENT 直接操作**：`SetWindowLongW` 直接设置/清除扩展窗口样式，绕过 Qt 的不可靠行为
3. **Alpha 层保障**：画布每个像素填 `alpha=3`，确保 Windows 分层窗口逐像素命中测试正确交付鼠标事件
4. **WM_SETCURSOR 拦截**：强制设置十字光标（IDC_CROSS），防止显示底层窗口的 I-beam 光标

### 笔迹数据模型

```python
class ToolType(Enum):
    PEN = auto()
    HIGHLIGHTER = auto()
    ERASER = auto()


@dataclass
class Stroke:
    points: list[QPointF]       # 路径控制点
    color: QColor               # 笔迹颜色
    width: float                # 笔刷大小
    opacity: float              # 透明度 (0.0 ~ 1.0)
    tool: ToolType              # PEN / HIGHLIGHTER / ERASER
```

### 绘图管道

```
用户鼠标事件 → DrawingCanvas 收集 QPointF 路径点
       ↓
StrokeManager.start_stroke() / add_point() / end_stroke()
       ↓
update() 触发 paintEvent → QPainter 双层合成 (Layer 1 + Layer 2)
       ↓
Layer 1: 画布底色填充 (alpha=3) + 截屏背景（可选）直接绘制
Layer 2: 新临时 QPixmap（透明填充）
         ├─ 遍历已完成的 Stroke → render_stroke()
         ├─ 当前预览笔迹 → render_stroke(is_preview=True, opacity=0.7)
         └─ drawPixmap 叠放到 Layer 1
额外: 橡皮擦模式时在 Layer 1 上方绘制虚线圆环预览
```

### 擦除实现

橡皮擦使用 `QPainter.CompositionMode_Clear` 在独立的**笔迹层**（临时 QPixmap）上操作，而非直接画在画布上。这样擦除只会清除笔迹像素，不会触及背景层（alpha=3 填充或截屏底图），保证命中测试始终有效。

### 热键方案

```python
# 常驻热键（任何时候生效）
keyboard.add_hotkey("ctrl+shift+d", toggle_requested)

# 绘制模式热键（进入时注册，退出时注销，suppress=True）
keyboard.add_hotkey("esc",    exit_requested,    suppress=True)
keyboard.add_hotkey("ctrl+z", undo_requested,    suppress=True)
keyboard.add_hotkey("ctrl+y", redo_requested,    suppress=True)
```

使用 `keyboard` 库监听全局热键，而非 Qt 内置的 QShortcut（Qt 的快捷键只在窗口聚焦时生效）。跨线程信号通过 `Signal()` 桥接到主线程。模式热键使用 `suppress=True` 阻止事件传递到底层窗口。

---

## 设置持久化

设置存储为 JSON，路径由 `QStandardPaths.AppDataLocation` 决定（`%APPDATA%/ScreenDoodle/settings.json`）：

```json
{
  "hotkey": "ctrl+shift+d",
  "default_color": "#FF0000",
  "default_width": 3.0,
  "default_tool": "PEN",
  "eraser_width": 20.0,
  "opacity": 1.0,
  "toolbar_x": null,
  "toolbar_y": null
}
```

每次用户变更工具/颜色/粗细/橡皮擦大小时自动持久化，工具栏位置在应用退出时保存。

---

## 依赖

```
PySide6>=6.6        # Qt 绑定
Pillow>=10.0        # 屏幕截图（预留）
keyboard>=0.13      # 全局热键
```

---

## 已实现功能（Phase 1 & 2 已完成）

- [x] 全屏透明覆盖层（每显示器独立窗口）
- [x] 全局热键 `Ctrl+Shift+D` 切换绘制/隐藏模式
- [x] Win32 原生鼠标穿透/捕获（WM_NCHITTEST + WS_EX_TRANSPARENT + alpha=3 保障）
- [x] 十字光标强制设置（WM_SETCURSOR 拦截）
- [x] 自由手绘（QPainter Path + lineTo + RoundCap/RoundJoin）
- [x] 荧光笔模式（alpha=0.3 × opacity + 4× 加粗）
- [x] 橡皮擦（CompositionMode_Clear 擦笔迹层 + 虚线圆环预览）
- [x] 撤销/重做（Ctrl+Z / Ctrl+Y）
- [x] 清除全部
- [x] 悬浮半透明工具栏（Emoji 图标，可拖拽，含隐藏按钮）
- [x] 16 色预设面板 + 自定义 QColorDialog 拾色器
- [x] 笔刷大小滑块（1-50）+ 橡皮擦大小滑块（5-100）
- [x] 设置持久化（JSON，颜色/粗细/工具/橡皮擦/工具栏位置）
- [x] 系统托盘图标（左键单击切换，右键菜单退出）
- [x] 多显示器支持（screenAdded/screenRemoved 热插拔）
- [x] Esc 退出绘制模式
- [x] 鼠标拖拽期间 grabMouse，防止丢失事件
- [x] 设置自动保存（每次变更即时写盘）
- [x] 工具栏位置持久化

## 笔迹调节配置 (`setting.json`)

项目根目录的 `setting.json` 用于调节笔迹渲染参数。修改后重启应用即可生效；删除此文件可重新生成默认值。

```json
{
  "_comment": "...",
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

### velocity 速度感应

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `sample_interval` | `4` | 每 N 个鼠标事件重新计算一次笔迹宽度（越大越平滑但响应越慢） |
| `smoothing_alpha` | `0.35` | 指数平滑因子（越小过渡越平滑，越大笔锋越灵敏） |
| `thin_mult` | `0.4` | 最快速度时的最小宽度倍率 |
| `thick_mult` | `2.5` | 最慢速度时的最大宽度倍率 |
| `ref_dist` | `15.0` | 速度曲线半程参考距离（像素） |
| `power_exponent` | `1.5` | 速度-宽度曲线形状（<1 低速段更敏感，>1 高速段更敏感） |

### rendering 渲染质量

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `min_segment_width` | `0.1` | 每小段最小绘制宽度（防止零宽度导致不可见） |
| `aa_quality` | `2` | SSAA 超采样倍数（1=Qt自带AA，2=2×SSAA 高质量） |
| `preview_antialias` | `true` | 笔迹预览是否启用抗锯齿 |
| `preview_opacity` | `1.0` | 笔迹预览透明度倍率 |
| `highlighter_opacity_scale` | `0.23` | 荧光笔额外透明度倍率 |
| `highlighter_width_scale` | `4.0` | 荧光笔宽度倍率（在基础宽度上放大） |
| `interpolation_segments` | `2` | Catmull-Rom 每对控制点之间的插值段数（越高曲线越平滑） |
| `subdivision_pixel_gap` | `4.0` | **回退细分密度**：渲染器在极端稀疏时的安全细分间距（正常情况下由 stroke_manager 插密接管） |
| `max_point_gap` | `3.0` | **自适应插密阈值**：相邻原始采样点超过此距离时，自动用 Catmull-Rom 插入带曲率的中间点（越小插密越密，曲线越平滑；调大则保留更多原始稀疏采样） |
| `max_densify_insert` | `16` | 单次插密最多插入的点数，防止极端稀疏数据导致点数爆炸 |

## 待实现功能（Phase 3 & 4）

- [ ] 截图底图（PIL.ImageGrab.grab() → set_background，toolbar 添加快照按钮）
- [ ] 辅助图形：直线、箭头、矩形、椭圆
- [ ] 取色器
- [ ] 保存/导出为 PNG（QImage 渲染 + 白底可选）
- [ ] 快捷键提示覆盖层（长按热键时显示帮助）
- [ ] 设置 UI（热键重绑定等）
- [ ] Nuitka / PyInstaller 打包为单 exe

---

## 开发原则

- **轻量优先**：启动 < 1s，空闲内存 < 60MB
- **最少依赖**：核心仅 PySide6 + Pillow + keyboard
- **模块解耦**：画布、模型、管理、渲染各司其职，通过信号/接口通信
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
- [Nuitka 打包指南](https://nuitka.net/doc/user-manual.html)
