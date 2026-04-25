# ChatGPT 官网注册 Runtime Edge Profile 隔离方案

## 背景

ChatGPT 官网注册流程会在 Edge 浏览器中产生登录态。若多个账号连续使用同一个 Edge Profile，前一个账号注册/登录后留下的 Cookie、LocalStorage、IndexedDB、Service Worker Cache 等状态会影响下一个账号。

典型问题：

```text
账号 A 注册完成
  -> Edge Profile 中保留 A 的 ChatGPT/OpenAI 登录态
  -> 下次打开 chatgpt.com 已是登录状态
  -> 账号 B 的注册入口和页面分支变复杂
```

本方案的目标是解决**本地浏览器状态串号**，让每次注册开始时都是干净、未登录的浏览器状态。

## 核心结论

官网注册流程应使用**每账号一次性的 runtime Edge Profile**：

```text
每个账号注册开始
        │
        ▼
创建/复制一个 runtime Edge User Data Dir
        │
        ▼
用该 runtime profile 打开 chatgpt.com / 官网注册页
        │
        ▼
完成注册、Team 加入、OAuth 登录、Team 移除
        │
        ▼
关闭 Edge
        │
        ▼
删除 runtime profile
        │
        ▼
下一个账号重新创建新的 runtime profile
```

这不是“服务端不可检测”的方案，而是**流程可靠性与状态隔离机制**。

## 与正常点击 Edge 图标的区别

正常点击 Edge 图标通常使用真实长期 Profile：

```text
真实 Edge Profile
├─ cookies
├─ localStorage
├─ IndexedDB
├─ service worker cache
├─ 登录态
├─ 浏览器偏好设置
├─ 扩展
└─ 历史积累的站点状态
```

一次性 runtime profile 使用临时资料目录：

```text
临时 Edge Profile
├─ 空 cookies
├─ 空 localStorage
├─ 空 IndexedDB
├─ 空 cache
├─ 没有 ChatGPT 登录态
└─ 关闭后删除
```

如果使用的是同一个 `msedge.exe`，服务端看到的浏览器内核仍然是 Microsoft Edge / Chromium。变化主要在于浏览器的本地状态容器不同。

## 服务端能看到什么

服务端通常能直接或间接看到：

| 类型 | 正常 Edge | 一次性 runtime profile |
|---|---|---|
| User-Agent / Edge 版本 | 能看到 | 能看到，基本相同 |
| IP / 代理 | 能看到 | 能看到 |
| 时区 / 语言 | 可通过 JS/请求推断 | 基本相同，取决于启动配置 |
| 屏幕尺寸 / DPR | 可通过 JS 看到 | 基本相同 |
| 字体 / Canvas / WebGL | 可通过 JS 指纹推断 | 多数仍相同，因为还是同一台机器 |
| Cookie | 有历史 Cookie | 没有历史 Cookie |
| LocalStorage / IndexedDB | 有历史状态 | 空 |
| 是否老访客 | 可能能识别 | 会像新 Profile / 新访客 |
| 本地 `--user-data-dir` 路径 | 通常看不到 | 通常看不到 |

服务端通常看不到本地路径：

```text
--user-data-dir=C:\Temp\codex-gui-edge-xxxx
```

但服务端可以间接感知“这是一个没有历史 Cookie / Storage 的新浏览器身份”。

因此，如果短时间内出现：

```text
同 IP / 同设备指纹
+ 多个新 Cookie 身份
+ 重复注册
+ 行为路径高度一致
+ 每次都是全新浏览器状态
```

服务端仍然可能通过这些组合特征进行风控判断。本方案不承诺规避服务端风控。

## 当前项目已有能力

相关代码：

- `platforms/chatgpt/browser_session.py`
- `platforms/chatgpt/codex_gui_driver.py`
- `tests/test_codex_gui_registration_engine.py`

当前逻辑：

```text
不配置 codex_gui_edge_user_data_dir
  -> tempfile.mkdtemp(prefix="codex-gui-edge-")
  -> 使用全新临时 Edge User Data Dir
  -> close() 后删除

配置 codex_gui_edge_user_data_dir + codex_gui_edge_snapshot_profile=True
  -> 复制配置的 Edge profile 到临时快照目录
  -> 使用快照目录运行自动化
  -> close() 后删除快照

配置 codex_gui_edge_user_data_dir + codex_gui_edge_snapshot_profile=False
  -> 直接复用真实 Edge Profile
  -> 登录态会保留
  -> 不适合官网注册批量流程
```

## 推荐配置模式

### 模式 A：默认临时空 Profile（最干净）

不传 `codex_gui_edge_user_data_dir`。

当前代码会自动创建临时目录：

```text
tempfile.mkdtemp(prefix="codex-gui-edge-")
```

适合官网注册默认流程。

### 模式 B：干净模板 Profile + Snapshot（推荐用于保留浏览器设置）

准备一个专用模板 Profile：

```text
D:\Profiles\EdgeTemplate\User Data
└─ Default
```

模板要求：

- 不登录 ChatGPT；
- 不登录 OpenAI；
- 不保存目标站点 Cookie；
- 只保留必要浏览器设置，例如语言、窗口、证书等。

配置示例：

```json
{
  "codex_gui_edge_user_data_dir": "D:\\Profiles\\EdgeTemplate\\User Data",
  "codex_gui_edge_profile_directory": "Default",
  "codex_gui_edge_snapshot_profile": true
}
```

运行时会复制模板到临时目录，注册结束后删除临时快照。

## 不推荐方案：注册后退出登录或清 Cookie

不建议只依赖：

```text
访问 logout 页面
点击退出登录
清理部分 Cookie
```

原因是 ChatGPT/OpenAI 登录态可能分散在：

- `chatgpt.com`
- `auth.openai.com`
- `openai.com`
- `platform.openai.com`
- Cookie
- LocalStorage
- SessionStorage
- IndexedDB
- Cache Storage
- Service Worker
- 浏览器 Session Restore

这种清理方式容易残留状态，下一轮注册仍可能进入复杂页面分支。

## 建议实现保护

官网注册变体应避免直接复用真实 Edge Profile。

建议在启动前加入保护：

```python
if codex_gui_variant == "official_signup":
    if configured_user_data_dir and codex_gui_edge_snapshot_profile is False:
        raise RuntimeError(
            "官网注册变体不允许直接复用真实 Edge Profile，请启用 codex_gui_edge_snapshot_profile"
        )
```

也可以选择更温和的策略：

```python
if codex_gui_variant == "official_signup":
    extra_config["codex_gui_edge_snapshot_profile"] = True
```

但更推荐显式报错，因为静默改配置可能让操作者误以为正在复用原始 Profile。

## 建议测试

应补充以下测试：

1. 官网注册变体不允许直接使用真实 Profile：

```text
Given codex_gui_variant=official_signup
And codex_gui_edge_user_data_dir is configured
And codex_gui_edge_snapshot_profile=False
Then startup should fail with a clear error
```

2. 官网注册变体无 `user_data_dir` 时使用临时 Profile：

```text
Given no codex_gui_edge_user_data_dir
When launching official_signup
Then runtime user data dir is a tempfile path
And close deletes it
```

3. 官网注册变体配置模板 Profile 时必须使用 Snapshot：

```text
Given codex_gui_edge_user_data_dir configured
And codex_gui_edge_snapshot_profile=True
Then snapshot_source_profile is called
And runtime dir is deleted on close
```

## 最终定位

一次性 runtime Edge Profile 的定位是：

> 同一个 Edge 浏览器程序，换一个全新的用户数据容器。

它解决的是：

```text
账号 A 的登录态污染账号 B 的注册流程
```

它不解决也不承诺解决：

```text
服务端是否能判断环境相似
服务端是否能做风控关联
服务端是否认为多个新 Cookie 身份来自同一设备/IP
```

因此，官网注册流程应把它作为**状态隔离与流程稳定性机制**使用，而不是作为反检测机制。
