# vend_email 独立测试入口接入真实 probe 设计

## 背景

当前仓库里已经存在两条相关能力线：

1. **vend.email alias service 方向**
   - 已有 `vend_email` source 设计与实现计划
   - 已在独立 worktree 中落下 vend runtime、state store、mailbox verification adapter、capture summary 契约等能力

2. **独立 alias generation test 入口方向**
   - 当前分支已新增：
     - `core/alias_pool/probe.py`
     - `POST /api/config/alias-test`
     - `Settings.tsx` 中的“别名邮件生成测试”卡片
   - `static_list` / `simple_generator` 已可通过独立测试入口真实测试
   - 但 `vend_email` 当前仍只是 probe 层的结构化 placeholder：

```python
error = "vend_email probe is not yet wired"
```

也就是说，前端入口已经具备：

- source 选择
- saved / draft 配置模式
- alias / mailbox / capture / steps / logs 展示

但它还不能真正执行 `vend_email` 这条复杂链路。

用户明确要求：

- 将 `vend_email` 真正接入独立 alias-test 入口
- 不是做半真半假的 placeholder，而是**完整复用 vend runtime**
- mailbox 相关配置必须来自前端配置或请求，而不是写死参考域名
- `cxwsss.online` 之类域名只作为参考验证环境，不能出现在运行时代码语义中

## 目标

本次设计要让独立 alias generation test 入口中的 `vend_email` 分支真正可执行，使系统能够：

1. 在 `/api/config/alias-test` 中对 `vend_email` source 执行真实 probe，而不是返回 placeholder
2. 复用 vend runtime 子树的真实能力，而不是重新在 probe 层实现一套 vend 流程
3. 根据当前配置读取 mailbox 验证站点参数与 vend source 参数
4. 在前端 `Settings` 测试卡片中看到真实 vend probe 结果，包括：
   - alias email
   - real mailbox
   - service email
   - capture summary
   - steps / logs
   - error
5. 保持正式 alias provider 和独立 alias-test 入口共享同一套 vend runtime 能力

## 非目标

本次设计不包含以下范围：

- 不把 vend runtime 扩展成完整通用浏览器编排平台
- 不在这一步接入多个新的 alias service 网站
- 不新增新的前端页面；继续复用 `Settings.tsx` 测试卡片
- 不改变 `/tasks/register` 的对外行为
- 不把某个参考 mailbox 域名写死进运行时代码命名或默认值

## 设计原则

### 1. probe 层调用 vend runtime，而不是平行实现 vend 流程

`AliasSourceProbeService` 的职责是：

- 选择 source
- 分发到合适的 probe/runtime 能力
- 聚合结果

它不应该在 `vend_email` 分支里自己理解注册/确认/登录/forwarder 创建的页面细节，否则会形成：

- 正式 alias provider 一套 vend 逻辑
- 独立 alias-test probe 另一套 vend 逻辑

这是本次设计明确避免的。

### 2. mailbox 验证能力必须配置驱动

当前参考环境使用：

- `mailbox_base_url`
- `mailbox_email`
- `mailbox_password`

但具体站点、邮箱账号、密码未来可能变化，因此 mailbox adapter 只能依赖这些配置字段，不能依赖某个固定域名名词。

### 3. 共享 vend runtime，出口不同

正式 alias provider 与独立 alias-test 入口的差异应该只体现在“出口语义”上：

- alias provider：供任务级 alias pool 消费
- alias-test probe：返回单次 probe 结果给前端

底层 vend runtime、state、capture、mailbox verification 应共享。

### 4. Settings 卡片继续做结果展示，不承担 vend 流程逻辑

前端卡片已经具备：

- 触发请求
- 切换 saved/draft 模式
- 选择 source
- 展示结果

这次它不需要理解 vend probe 细节，只需要继续展示后端返回的真实结构化结果。

## 总体设计

本次接入分为三层：

1. **vend runtime 子树完整接入当前分支**
2. **probe 层在 `vend_email` 分支里调用真实 vend runtime probe**
3. **alias-test API / Settings 卡片继续复用现有结构，只接收真实 vend 结果**

## 需要接入/迁移的后端能力

当前 `alias-generation-test-entry` 分支缺少 vend runtime 本体，因此需要把这些能力迁入或等价重建到当前分支：

- `core/alias_pool/vend_email_state.py`
- 通用 mailbox verification adapter（使用 generic 命名，不依赖参考域名）
- `core/alias_pool/vend_email_service.py` 中与 runtime / orchestrator 相关的部分

### 注意

这不是把另一个分支的文件无脑拷贝进来，而是：

1. 保留已经修好的通用 mailbox adapter 命名与配置驱动方向
2. 把 vend runtime 能力接回当前分支
3. 让 probe 层与正式 provider 共用它们

## vend runtime 复用边界

这次接入后，建议 vend runtime 明确暴露一个单次 probe 能力，例如：

- `probe_once(...)`
- 或 `run_probe(...)`

返回统一结构化结果，其中至少包括：

- `alias_email`
- `real_mailbox_email`
- `service_email`
- `capture_summary`
- `steps`
- `logs`
- `error`

### probe 与正式 provider 的差异

- **正式 provider**：以 producer 语义为中心，负责把 alias 放入 pool
- **独立 probe**：以“拿到一个 alias 并返回结果”为中心

但二者共享：

- vend runtime
- mailbox verification adapter
- state store
- capture 记录结构

## probe 层接线方式

当前 `AliasSourceProbeService` 在 `vend_email` 分支里只是返回 placeholder。接入后应改为：

1. 根据 `source` 配置构建 vend runtime 及其依赖
2. 调用 vend runtime 的单次 probe 方法
3. 将结果映射成 `AliasProbeResult`

因此 `vend_email` 分支不再是：

```python
error = "vend_email probe is not yet wired"
```

而是返回真实 probe 结果。

## alias-test API 的变化

`POST /api/config/alias-test` 的请求/响应模型原则上不需要大改。

### 请求保持不变

```json
{
  "sourceId": "vend-email-primary",
  "useDraftConfig": true,
  "config": { ... }
}
```

### 响应保持结构化

```json
{
  "ok": true,
  "sourceId": "vend-email-primary",
  "sourceType": "vend_email",
  "aliasEmail": "vendcapdemo20260417@serf.me",
  "realMailboxEmail": "admin@example.com",
  "serviceEmail": "vendcap202604170108@example.com",
  "captureSummary": [ ... ],
  "steps": [ ... ],
  "logs": [ ... ],
  "error": ""
}
```

区别只是：

- 之前 vend 分支返回 placeholder 错误
- 现在 vend 分支返回真实 probe 结果

## 前端设计

### Settings 卡片结构不需要重做

`AliasGenerationTestCard` 当前已具备：

- source 选择
- saved / draft 切换
- 测试按钮
- alias / mailbox / source / service email 展示
- steps / logs / captureSummary 展示

因此前端这次不是重构 UI，而是：

- 继续使用当前卡片
- 让它吃到真实 vend probe 结果

### 仍需保持的前端语义

1. saved 模式下使用 saved source options
2. draft 模式下使用 draft source options
3. 在模式切换时避免保留无效 source 选择

## 配置驱动边界

必须继续保证以下配置来自请求草稿或已保存配置：

- `register_url`
- `mailbox_base_url`
- `mailbox_email`
- `mailbox_password`
- `alias_domain`
- 其他 vend source 所需字段

运行时代码中：

- 不出现固定参考域名命名
- 不把参考环境 URL 当作默认行为依赖

## 测试设计

### 1. 后端单元/契约测试

覆盖：

1. vend runtime probe 的返回结构
2. mailbox adapter 的配置驱动行为
3. probe 层 `vend_email` 分支接入真实 vend runtime
4. state store / capture summary 的协同行为

### 2. API 测试

覆盖：

1. `sourceType=vend_email` 时返回真实字段
2. saved / draft 配置都能驱动 vend probe
3. 错误返回仍是结构化响应

### 3. 前端验证

继续以 build/typecheck 为主，验证：

- `Settings` 卡片继续能渲染 vend probe 返回的真实字段

### 4. 真实手动验证

至少验证一轮：

1. mailbox 登录成功
2. 确认链接提取成功
3. vend 登录 / forwarder 创建成功
4. 前端卡片显示真实 alias 与 capture summary

## 影响范围

### 需要新增/迁入或修改的典型文件

- `core/alias_pool/vend_email_state.py`
- `core/alias_pool/mailbox_verification_adapter.py`（或等价 generic 命名文件）
- `core/alias_pool/vend_email_service.py`
- `core/alias_pool/probe.py`
- `tests/test_alias_pool.py`
- `tests/test_alias_generation_api.py`
- 可能补一份 vend runtime / mailbox adapter 专项测试文件

### 前端

大概率只需：

- `frontend/src/components/settings/AliasGenerationTestCard.tsx`
- `frontend/src/lib/aliasGenerationTest.ts`
- 如有必要，`frontend/src/pages/Settings.tsx`

## 风险与取舍

### 1. 跨分支迁移会带来契约漂移风险

如果简单复制旧文件，很容易把旧命名或参考域名语义一起带回来。所以这次必须以当前“generic mailbox verification + config-driven”约束为准，重新审视 vend 子树。

### 2. 独立 probe 与正式 provider 的出口不同

即使共享 vend runtime，也仍然需要小心不要让 probe 逻辑污染正式 pool 行为。因此共享底层能力，但保留各自出口语义。

### 3. 手动验证仍然重要

即使单元测试和 API 测试都通过，真实 vend 站点和 mailbox 站点的行为仍可能漂移，所以这次接入后的真实手动验证是必要验收项。

## 验收标准

满足以下条件即可视为本次设计对应实现完成：

1. `vend_email` 在独立 alias-test API 中不再返回 placeholder
2. `AliasSourceProbeService` 在 `vend_email` 分支调用的是真实 vend runtime probe，而不是平行逻辑
3. vend runtime 与独立 alias-test 入口共享同一套 state / mailbox verification / capture 能力
4. mailbox 站点参数来自配置，而不是硬编码参考域名
5. `Settings` 卡片能展示真实 vend probe 结果
6. 正式 alias provider 与独立 alias-test 入口共享同一套 vend runtime 能力
