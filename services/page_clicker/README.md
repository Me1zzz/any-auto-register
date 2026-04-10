# Page Clicker

`page_clicker` 现在是一个 **双后端页面/桌面点击框架**，支持：

- **Playwright 后端**：适合真实网页、DOM 选择器、文本定位、页面元信息与截图
- **PyAutoGUI 后端**：适合前台桌面窗口、图像定位、屏幕坐标点击与桌面截图

它不再是一个最小示例脚手架，而是一个有明确后端边界、配置校验、失败保护和测试覆盖的独立工具。

## 目录

- `config.py`：统一 CLI 与双后端配置校验
- `models.py`：通用配置、目标模型、后端选项与返回结果
- `runner.py`：统一编排层，负责 backend 选择与错误归一化
- `backends/playwright_backend.py`：浏览器自动化执行后端
- `backends/pyautogui_backend.py`：桌面屏幕控制执行后端
- `dom.py`：静态 HTML 可点击元素分析辅助工具，不负责真实点击
- `demo/local_click.html`：Playwright 本地演示页

## 设计目标

- 保留浏览器后端的稳定 DOM/locator 能力
- 提供桌面 GUI 后端用于必须依赖前台屏幕操作的场景
- 通过统一 CLI 与结果结构切换后端
- 把“更像真人”控制在 **节奏、移动、停顿、保护机制** 上，而不是做绕过检测的对抗逻辑

## 依赖准备

### Playwright 后端

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

### PyAutoGUI 后端

```bash
pip install pyautogui
```

如果你要使用图像定位置信度参数 `--locate-confidence`，还需要安装图像匹配依赖，例如 OpenCV。

## 后端能力对比

| 能力 | Playwright | PyAutoGUI |
| --- | --- | --- |
| 网页导航 | 支持 | 不支持 |
| CSS / 文本定位 | 支持 | 不支持 |
| 图像定位 | 不支持 | 支持 |
| 屏幕坐标点击 | 不支持 | 支持 |
| 页面 title / final_url | 支持 | 不可靠/不提供 |
| 浏览器截图 | 支持 | 不支持 |
| 桌面截图 | 不支持 | 支持 |
| Headless | 支持 | 不支持 |

## Playwright 后端示例

### 运行本地 demo

```bash
python -m services.page_clicker --backend playwright --demo local-click --target-css "#start-button"
```

### 运行真实页面

```bash
python -m services.page_clicker --backend playwright --url "https://example.com" --target-css "button.submit"
```

### 文本目标

```bash
python -m services.page_clicker --backend playwright --url "https://example.com" --target-text "Continue"
```

### 拟人化点击

```bash
python -m services.page_clicker --backend playwright --demo local-click --target-css "#start-button" --click-mode human
```

Playwright 的 `human` 模式会执行 hover、短暂停顿、元素内部偏移点移动、再进行 mouse down / mouse up。
它会让点击在交互形态上更接近真人，但**不等于绕过平台风控或反自动化检测**。

## PyAutoGUI 后端示例

### 图像定位点击

```bash
python -m services.page_clicker --backend pyautogui --target-image "C:\\tmp\\button.png" --allow-gui-control true
```

### 坐标点击

```bash
python -m services.page_clicker --backend pyautogui --target-point "640,480" --allow-gui-control true
```

### 局部区域图像搜索

```bash
python -m services.page_clicker --backend pyautogui --target-image "C:\\tmp\\button.png" --region "100,100,800,600" --allow-gui-control true
```

### PyAutoGUI 拟人化点击

```bash
python -m services.page_clicker --backend pyautogui --target-image "C:\\tmp\\button.png" --click-mode human --allow-gui-control true
```

PyAutoGUI 的 `human` 模式会采用更平滑的移动、点击前后停顿以及 down/up 分离按压。它更像真实桌面输入，但稳定性会明显受屏幕分辨率、窗口位置、缩放比例和前台焦点影响。

## 关键参数

### 通用参数

- `--backend playwright|pyautogui`
- `--click-mode direct|human`
- `--timeout-ms`
- `--screenshot-path`

### Playwright 参数

- `--url`
- `--demo local-click`
- `--target-css`
- `--click-selector`：兼容旧参数，等价于 `--target-css`
- `--target-text`
- `--wait-css`
- `--wait-text`
- `--headless true|false`

也支持环境变量：

- `AUTOCLICK_HEADLESS`
- `PLAYWRIGHT_HEADLESS`

### PyAutoGUI 参数

- `--target-image`
- `--target-point X,Y`
- `--region X,Y,W,H`
- `--locate-confidence`
- `--move-duration-ms`
- `--pre-click-delay-ms`
- `--post-click-delay-ms`
- `--failsafe true|false`
- `--allow-gui-control true`

## PyAutoGUI 安全护栏

PyAutoGUI 后端默认不是“开箱即点”，而是要求显式授权：

- 必须传 `--allow-gui-control true`
- 默认启用 FailSafe
- 图像定位失败时不会盲点
- 可用 `--region` 缩小搜索范围，减少误命中
- 可以通过 `--screenshot-path` 保留失败现场截图

这部分设计是为了**降低误操作风险**，不是为了规避检测。

## 结果输出

CLI 会输出统一 JSON，包含例如：

- `success`
- `backend`
- `url`
- `target_kind`
- `target_value`
- `final_url`
- `title`
- `clicked_text`
- `clicked_position`
- `screenshot_path`
- `error`

不同后端的可用字段不同，例如 `PyAutoGUI` 通常不会返回 `final_url` 或 `title`。

## 限制与边界

- 当前仍然以“单目标、单次点击、单次结果”为主，不是工作流引擎
- Playwright 更适合网页交互；PyAutoGUI 更适合前台桌面控制
- PyAutoGUI 依赖活跃桌面会话，不能像 Playwright 一样 headless
- `dom.py` 只负责静态 HTML 分析，不参与后端执行
- 本工具不会实现指纹伪装、绕过检测或对抗平台风控的逻辑
