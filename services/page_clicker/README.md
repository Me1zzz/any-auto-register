# Page Clicker

最小可运行的页面自动点击框架，默认使用 **Playwright** 执行真实页面导航与点击，`selectolax` 只用于静态 HTML 预分析。

## 目录

- `config.py`：CLI 与环境变量配置解析
- `runner.py`：Playwright 导航与点击流程
- `dom.py`：静态 HTML 可点击元素提取辅助工具
- `demo/local_click.html`：本地可重复运行的示例页

## 为什么默认选 Playwright

- 可以处理 JS 渲染后的真实页面
- 点击前能等待元素出现并执行真实浏览器点击
- 比纯 HTML DOM 解析更适合自动化交互场景

## 运行前准备

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

## 运行本地示例

```bash
python -m services.page_clicker --demo local-click
```

## 运行指定页面

```bash
python -m services.page_clicker --url "https://example.com" --click-selector "button.submit"
```

## 常用参数

- `--wait-for-selector`：点击前先等待某个元素出现
- `--timeout-ms`：等待/点击超时时间
- `--headless true|false`：显式覆盖浏览器是否无头
- `--screenshot-path`：点击后保存页面截图

也支持环境变量：

- `AUTOCLICK_HEADLESS`
- `PLAYWRIGHT_HEADLESS`

## 限制

- 当前版本只实现单次页面导航 + 单次点击
- 定位方式当前以 CSS selector 为主
- `dom.py` 不负责真实点击，只做静态 HTML 分析
