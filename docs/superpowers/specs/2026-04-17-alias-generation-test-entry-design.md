# 独立别名邮件生成测试入口设计

## 背景

当前仓库已经具备 alias pool 的基础抽象与多种 alias source：

- `core/alias_pool/static_list.py`：静态别名列表
- `core/alias_pool/simple_generator.py`：简单随机生成别名
- `core/alias_pool/vend_email_service.py`：vend.email 别名服务 provider 与 runtime 契约
- `api/tasks.py::_build_alias_pool()`：在正式注册任务前置构建 alias pool

但目前系统里还没有一个**单独的、可直接调试的 alias 生成入口**。如果想验证当前配置是否真的能生成别名，现状只能：

1. 通过注册任务主链路间接触发 alias pool
2. 观察日志与任务结果
3. 手动推断 alias source / mailbox / runtime 哪一步出了问题

这对 vend.email 这类带有外部邮箱验证、确认链接、forwarder 创建、抓包摘要的 alias source 尤其不友好，因为：

- 测试 alias 生成本身时，不需要启动完整账号注册主流程
- 调试 alias source 时，更需要结构化结果和步骤诊断，而不是只有“注册成功/失败”
- 前端已经有完整的邮箱服务配置页（`frontend/src/pages/Settings.tsx`），但没有一个直接的“测试生成别名邮箱”入口

用户明确要求：

1. 实现一个**单独的别名邮件生成代码入口**
2. 在前端增加一个**别名邮件生成测试入口**
3. 后端入口更接近**独立测试 API**，而不是复用正式注册任务主流程
4. 相关邮箱站点参数（如 `mailbox_base_url`、`mailbox_email`、`mailbox_password`）必须来自前端配置或请求数据，而不是写死在运行时代码里

## 目标

本次设计要新增一个“alias generation test”能力，使系统能够：

1. 在不启动正式注册任务的前提下，单独测试当前 alias source 配置是否可生成一个可用别名
2. 返回结构化测试结果，而不是只返回布尔值
3. 在前端设置页直接触发该测试，并展示 alias、source、capture、步骤日志和错误信息
4. 复用现有 alias pool / producer / runtime 体系，而不是新造一套测试专用 alias 逻辑
5. 保持一次只测一个 source，便于诊断多 source 配置中的单点问题

## 非目标

本次设计不包含以下范围：

- 不把独立测试入口做成新的长期运行任务系统
- 不把它扩展成完整的 alias 调试工作台或多页调试平台
- 不在这一步支持并行测试全部 source
- 不引入新的前端路由页面；默认入口放在 `Settings.tsx`
- 不改变正式 `/tasks/register` 主流程的行为
- 不把 `cxwsss.online` 或任何具体 mailbox 域名写死到测试入口 API 或运行时代码命名中

## 设计原则

### 1. 测试入口必须独立于正式注册任务

alias source 调试与正式账号注册是两个不同目标。前者只关心“当前 source 能不能生成 alias”，后者还要处理平台注册、验证码、并发、任务日志等。因此本次新增独立测试 API，而不是复用 `/tasks/register`。

### 2. 返回结果必须结构化且可诊断

测试 alias source 时，单纯返回“成功/失败”没有调试价值。必须返回：

- 生成出的 alias
- 对应真实邮箱
- source 类型与 source id
- 若适用，service account 标识
- capture summary
- step / logs
- error

这样前端才能真正充当调试入口。

### 3. 运行时参数以配置为真相源

这次入口面向“用当前配置做一次测试”。因此 mailbox 相关信息应来自：

- 已保存配置（默认）
- 或前端当前未保存表单值（可选）

绝不能在后端 helper / runtime 命名或实现中写死某个参考域名。

### 4. 复用现有 alias pool / producer / runtime

测试入口不是另一套 alias 体系。它应该重用：

- `normalize_cloudmail_alias_pool_config()`
- 现有 source 分发逻辑
- 现有 producer / runtime

只是把执行目标从“供注册任务消费”改为“执行一次单次 alias 测试并返回结果”。

### 5. 一次只测一个 source

如果当前配置里同时存在多个 alias source，测试入口必须要求选择其中一个 source，而不是一次全跑。否则：

- 返回结果会混杂
- 错误定位困难
- capture / logs 难以归因

## 总体设计

本次设计由两部分组成：

1. **后端独立 alias test API**
2. **前端 Settings 页面中的测试卡片**

二者共同复用当前 alias source 与 runtime 体系。

## 后端设计

### 新增独立测试 API

建议在后端新增一个专用 alias test 接口，例如挂在已有配置相关或 alias 相关路由下。路径本身不要求此时定死，但职责必须清晰：

- 输入当前配置与目标 source 标识
- 执行一次 alias source 测试
- 返回结构化结果

这个接口不应返回 task_id，也不应进入正式 `_task_store`。

### 请求模型

请求需要支持两种模式：

1. **使用已保存配置测试**
2. **使用前端当前未保存表单值测试**

推荐请求形状：

```json
{
  "sourceId": "vend-email-primary",
  "useDraftConfig": true,
  "config": {
    "mail_provider": "cloudmail",
    "cloudmail_alias_enabled": true,
    "sources": [ ... ]
  }
}
```

语义：

- `sourceId`：要测试的 source
- `useDraftConfig`：是否优先使用当前草稿配置
- `config`：当前前端表单值；当 `useDraftConfig=false` 时可省略

### 响应模型

响应必须结构化，建议包含：

```json
{
  "ok": true,
  "sourceType": "vend_email",
  "sourceId": "vend-email-primary",
  "aliasEmail": "vendcapdemo20260417@serf.me",
  "realMailboxEmail": "admin@example.com",
  "serviceEmail": "vend-service@example.com",
  "captureSummary": [ ... ],
  "steps": ["restore_session", "login", "list_forwarders", "create_forwarder"],
  "logs": ["loaded saved state", "created one alias"],
  "error": ""
}
```

其中：

- `aliasEmail`：本次生成/拿到的 alias
- `realMailboxEmail`：真实收件邮箱
- `serviceEmail`：当 source 基于服务账号时返回
- `captureSummary`：沿用 `VendEmailCaptureRecord` / 其他 source 对应的简化抓包摘要模型
- `steps`：结构化步骤名，面向程序判断
- `logs`：人类可读的诊断信息
- `error`：失败时的主错误描述

### 后端执行流

推荐执行流：

1. 读取已保存配置
2. 若 `useDraftConfig=true`，将请求携带的 `config` 覆盖到当前配置之上
3. 调用 `normalize_cloudmail_alias_pool_config()`
4. 根据 `sourceId` 选中单个 source
5. 构建该 source 对应的 producer/runtime
6. 执行一次“单次 alias generation test”
7. 返回结构化结果

### 单次测试执行边界

这个“单次 alias generation test”不等于完整 `load_into(manager)` 的批量行为。它更接近：

- 针对一个 source 获取一个 alias
- 若 source 为静态列表，则取第一个可用 alias
- 若 source 为 simple generator，则生成一个 alias
- 若 source 为 service-based（如 vend_email），则按 runtime 获取或创建一个 alias

因此建议新增一个独立 service 层，例如：

- `AliasGenerationTestService`
- 或 `AliasSourceProbeService`

职责是把 producer/runtime 的差异统一成“一次 probe”语义，而不是把 probe 逻辑散在 API 层。

### 与现有 alias pool 的关系

复用原则如下：

- 保留已有 normalize 逻辑
- 保留已有 source type 分发
- 保留已有 producer / runtime
- 不把 probe 结果写入正式任务级 alias pool

换句话说，测试入口和正式注册共享同一套 source 实现，但共享的是**能力**，不是共享某个 task pool 实例。

## 前端设计

### 入口位置

入口放在 `frontend/src/pages/Settings.tsx` 的邮箱服务设置区域，而不是 `RegisterTaskPage.tsx`。

原因：

- 用户是在配置邮箱与 alias source 时需要立即验证
- 设置页已经集中管理 mailbox / alias 配置
- 避免把测试工具和正式注册任务主表单混在一起

### UI 结构

新增一个“别名邮件生成测试”卡片，包含：

1. **source 选择**
   - 当只有一个 source 时自动选中
   - 多个 source 时必须选择一个 source

2. **配置来源开关**
   - 使用已保存配置测试
   - 使用当前未保存表单值测试

3. **测试按钮**
   - “测试生成别名邮箱”

4. **结果展示区**
   - 成功结果
   - 失败结果
   - 可折叠 capture / steps / logs

### 成功态展示

成功时显示：

- alias email
- real mailbox
- source type
- source id
- service email（如果适用）

### 失败态展示

失败时显示：

- error
- 最近一步失败位置
- logs / steps

### capture summary 展示

capture summary 默认折叠，展开后显示每条记录的：

- name
- method + url
- request/response 摘要
- captured_at

不要求这一步做复杂 JSON 浏览器，只需做到清晰可读。

## 多 source 行为

如果当前 alias 配置里：

- **只有一个 source**：默认直接测试它
- **有多个 source**：要求用户选择 source
- **没有 source**：前端禁用测试按钮并提示先配置 alias source

## 错误处理

### 后端

错误必须被归一化为结构化响应，而不是直接抛 500 给前端。至少区分：

- 配置错误（无 source、sourceId 不存在、字段缺失）
- source 执行错误（runtime/probe 失败）
- 结果为空（执行成功但没有拿到 alias）

### 前端

前端必须区分：

- 请求失败（API 异常）
- 测试失败（`ok=false`）
- 测试成功（`ok=true`）

## 测试设计

### 后端测试

新增或扩展测试覆盖：

1. 独立 alias test API 的请求/响应模型
2. 单 source 选择逻辑
3. 使用已保存配置 vs 草稿配置覆盖逻辑
4. simple_generator / static_list / vend_email 的 probe 行为
5. 错误响应聚合逻辑

### 前端测试

覆盖：

1. Settings 页面测试卡片的显示条件
2. 多 source 选择逻辑
3. 点击测试按钮后的 loading / success / error 状态
4. capture / logs 的展示

### 手动验证

至少验证：

1. simple_generator source 能生成一个 alias
2. vend_email source 在当前配置下能返回 alias 或明确错误
3. Settings 页面能完整显示结构化结果

## 影响范围

### 后端

- `api/` 下新增独立 alias test API
- 可能新增一个 alias probe/service 文件
- 复用现有 `core/alias_pool/*`

### 前端

- `frontend/src/pages/Settings.tsx`
- 可能新增一个 settings 子组件用于承载测试卡片

## 风险与取舍

### 1. probe 与正式装载语义不同

如果直接拿 `producer.load_into()` 生搬硬套，会把“单次测试”变成“批量装载”。因此需要一个明确的 probe 层把两者隔开。

### 2. 草稿配置测试可能与已保存配置不一致

这是有意设计：目的就是让用户在保存前先验证。前端必须明确当前测试使用的是哪一种配置来源。

### 3. vend_email 结果天然更复杂

service-based source 的返回结果可能包含 capture / serviceEmail / steps，而 static/simple source 可能没有这么多字段。因此响应模型允许字段按 source 类型部分为空。

## 验收标准

满足以下条件即可视为本次设计对应实现完成：

1. 后端存在独立 alias generation test API
2. 该 API 能按 sourceId 单独测试一个 alias source
3. API 返回结构化 alias/test 结果，而不是只返回字符串
4. Settings 页面存在“别名邮件生成测试”入口
5. 用户可以选择使用已保存配置或当前草稿配置测试
6. 用户可以在多 source 情况下选择测试目标 source
7. 前端能展示 alias、mailbox、capture、logs 和错误信息
8. 正式 `/tasks/register` 主流程行为不受影响
