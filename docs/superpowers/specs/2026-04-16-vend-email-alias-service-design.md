# Vend.email 别名邮箱服务设计

## 背景

当前 CloudMail alias pool 已经完成了 phase-2 级别的来源抽象：

- `AliasEmailPoolManager` 负责任务级别名池
- `StaticAliasListProducer` 负责静态列表来源
- `SimpleAliasGeneratorProducer` 负责最小动态生成来源
- `AliasServiceProducerBase` 仍然只是未实现骨架

也就是说，仓库已经具备“从多个 source producer 向任务级 alias pool 投递 lease”的结构，但还没有一个真正的**站点型别名服务**实现，来验证这条架构如何承接“注册账号 → 收验证邮件 → 登录 → 生成 alias → 向 pool 供给邮箱”。

本次目标是将 `vend.email` 固化为首个真实的 alias service provider。当前阶段会使用 `@cxwsss.online` 域名与 `admin@cxwsss.online` 管理邮箱完成抓包和流程摸底，但这组信息只作为**参考验证环境**，不应被写死为运行时唯一依赖：

- 注册入口：`https://www.vend.email/auth/register`
- CloudMail 管理端：`https://cxwsss.online/`
- 参考管理邮箱：`admin@cxwsss.online`
- 参考管理邮箱密码：`1103@Icity`

用户明确要求该服务最终既要：

1. 对外向任务分发可用 alias email
2. 内部沉淀 vend.email 侧账号/会话，用于后续复用、补货与追踪

用户补充约束：

- `cxwsss.online` 相关信息只在当前抓包和流程验证阶段需要使用
- 实际服务运行时可能改用别的域名和别的真实收件邮箱来源

## 目标

构建一个最小但真实可用的 `vend_email` alias service provider，使其能够：

1. 在 vend.email 注册新账号或恢复已有账号会话
2. 通过可配置的真实收件邮箱来源读取 vend.email 的验证邮件
3. 完成 vend.email 账号验证与登录
4. 在 vend.email 中生成 alias 邮箱并读取 alias 列表
5. 将 alias 投递为 `AliasEmailLease`，供现有 CloudMail alias pool 消费
6. 持久化 vend.email 服务账号状态与关键抓包样本，便于后续复用与协议化探索

## 非目标

本次设计不包含以下范围：

- 不把 vend.email 自动化抽象成通用浏览器编排框架
- 不在本次同时实现多个 alias service 网站
- 不在本次把“真实收件邮箱来源”抽象成完整通用插件市场；只要求 vend.email provider 运行时不要写死 `cxwsss.online`
- 不承诺第一阶段就实现纯 HTTP/协议化注册与 alias 创建
- 不新增前端界面来管理 vend.email 服务账号
- 不把 vend.email 账号做成跨环境共享的集中式账号池服务

## 设计原则

### 1. 先以真实浏览器流程跑通，再沉淀协议信息

vend.email 是当前第一个真实站点型 alias service provider。为了降低首个实现的失败风险，第一阶段以 MCP/Playwright 驱动真实页面为真相源，确保：

- 注册链路真实可跑
- 邮件验证真实可跑
- 登录和 alias 创建真实可跑

与此同时，不把抓包当成一次性调试信息，而是将关键请求样本结构化保存，为后续半协议化或纯协议化迁移提供基础。

这里的“真实可跑”允许先基于 `cxwsss.online` 这套参考环境做抓包和流程确认，但 provider 设计必须把“alias 域名”和“真实收件邮箱来源”保留为运行时配置项。

### 2. alias pool 只消费 lease，不感知站点细节

现有 alias pool 的价值在于把“邮箱来源”从主注册链路中抽离出来，因此 vend.email provider 不能把站点细节泄漏到 pool 或平台层。对 pool 来说，它仍然只接收：

- `alias_email`
- `real_mailbox_email`
- source 元数据
- session 元数据

平台注册主链路仍通过现有 mailbox / alias lease 消费邮箱，不需要理解 vend.email 的 cookie、token 或页面流程。

### 3. 服务账号状态和 alias 供给状态分离

vend.email provider 对外提供的是 alias 邮箱，但内部必须维护服务账号状态。两者职责不同：

- **service account state**：vend.email 注册邮箱、密码、cookie/local storage、最近登录时间、抓包样本
- **alias lease state**：alias 是否已投递到 pool、是否已被租出、是否被主链路消耗

这样后续即便 alias 被消耗完，也可以复用现有 vend.email 会话继续补货，而不是每次都重新注册账号。

### 4. 首次实现只做 vend.email provider，不过度泛化

虽然这是 `alias_service` 路线的首个真实实现，但本次不额外引入“大而全”的 provider 框架。需要补齐的是：

- `AliasServiceProducerBase` 的真实可运行子类
- vend.email runtime 及其状态持久化
- 抓包记录结构

不会为了假想中的第二、第三个站点提前引入过重抽象。

## 总体设计

### 职责分层

本次实现采用四层分工：

1. **配置归一化层**
   - 识别 `type: "vend_email"` 的 alias source
   - 归一化 vend.email 所需参数
   - 归一化可替换的 alias 域名与真实收件邮箱来源参数

2. **Alias service producer 层**
   - 新增 `VendEmailAliasServiceProducer`
   - 在 `load_into(manager)` 中准备服务账号、拉取 alias、向 pool 投递 lease

3. **Vend.email runtime 层**
   - 负责浏览器自动化、邮件验证、会话恢复、alias 创建、抓包采集
   - 负责 service account state 的读写

4. **状态与抓包存储层**
   - 保存 vend.email 会话快照
   - 保存关键抓包样本摘要
   - 保存 alias 列表快照和最近一次运行信息

### 运行边界

`api/tasks.py::_build_alias_pool()` 读到 `vend_email` source 后：

1. 实例化 `VendEmailAliasServiceProducer`
2. 注册到 `AliasEmailPoolManager`
3. 调用 `producer.load_into(manager)`

对 task register 主链路来说，变化仍然发生在 alias pool 构建阶段，不要求平台侧注册逻辑改协议。

## 配置模型

新增显式 source type：`vend_email`

推荐配置结构：

```python
{
  "cloudmail_alias_enabled": True,
  "sources": [
    {
      "id": "vend-email-primary",
      "type": "vend_email",
      "register_url": "https://www.vend.email/auth/register",
      "mailbox_base_url": "https://cxwsss.online/",
      "mailbox_email": "admin@cxwsss.online",
      "mailbox_password": "1103@Icity",
      "alias_domain": "cxwsss.online",
      "alias_count": 5,
      "state_key": "vend-email-primary",
    }
  ],
}
```

字段说明：

- `id`: source 标识
- `type`: 固定为 `vend_email`
- `register_url`: vend.email 注册入口
- `mailbox_base_url`: 真实收件邮箱管理端地址；当前抓包阶段可指向 `https://cxwsss.online/`
- `mailbox_email`: 真实收件邮箱地址；当前抓包阶段可使用 `admin@cxwsss.online`
- `mailbox_password`: 对应真实收件邮箱密码
- `alias_domain`: vend.email 中期望生成的 alias 域名，运行时必须可替换，不能写死为 `cxwsss.online`
- `alias_count`: 本次任务初始化阶段最少尝试供给多少个 alias
- `state_key`: service account state 的持久化标识，缺省时可回退为 `id`

### 归一化规则

`core/alias_pool/config.py` 需要扩展 `_normalize_sources()`，在当前 `static_list` 与 `simple_generator` 基础上加入 `vend_email`：

```python
{
  "id": "vend-email-primary",
  "type": "vend_email",
  "register_url": "https://www.vend.email/auth/register",
  "mailbox_base_url": "https://cxwsss.online/",
  "mailbox_email": "admin@cxwsss.online",
  "mailbox_password": "1103@Icity",
  "alias_domain": "cxwsss.online",
  "alias_count": 5,
  "state_key": "vend-email-primary",
}
```

约束：

- `alias_count <= 0` 时，仍识别该 source，但本次不投递 alias
- URL 与邮箱字段统一做字符串清洗
- `mailbox_email` 统一转小写
- `state_key` 缺省时使用 `id`
- `alias_domain` 必须来自配置，provider 内部不得写死默认业务域名

## Producer 设计

### VendEmailAliasServiceProducer

新增一个真正可运行的 alias service producer，例如放在：

- `core/alias_pool/vend_email_service.py`

其职责是：

1. 根据 source 配置初始化 vend.email runtime
2. 恢复或创建 vend.email 服务账号状态
3. 让 runtime 确保存在可用登录态
4. 拉取或创建足够数量的 alias
5. 将 alias 包装为 `AliasEmailLease` 投递到 `AliasEmailPoolManager`

### producer 状态模型

沿用当前 `AliasSourceState`：

- 初始：`IDLE`
- 正在准备会话 / 抓取 alias：`ACTIVE`
- 本次 `load_into()` 已完成并成功供给：`EXHAUSTED`
- 无法恢复会话或无法供给 alias：`FAILED`

这里的 `EXHAUSTED` 表示“本次同步装载过程已结束”，而不是 vend.email 账号永久失效。

### `load_into()` 执行流

推荐同步执行流：

1. 将 producer 状态置为 `ACTIVE`
2. 读取本地 `VendEmailServiceState`
3. 若 state 中存在会话快照，优先尝试恢复登录态
4. 若恢复失败，则执行浏览器登录流程
5. 若登录失败且尚无有效服务账号，则执行浏览器注册流程
6. 在注册流程中通过配置的真实收件邮箱来源收验证邮件并完成验证
7. 登录成功后读取 vend.email 当前 alias 列表
8. 若现有 alias 数不足 `alias_count`，则继续创建 alias
9. 对 alias 列表做去重和过滤
10. 将 alias 作为 `AliasEmailLease` 投递到 manager
11. 保存最新 state 与抓包摘要
12. 将 producer 状态置为 `EXHAUSTED`

若其中任一步骤抛出致命异常：

- 记录结构化错误事件
- 保存失败上下文
- producer 状态置为 `FAILED`
- 异常继续向外抛出

## Vend.email runtime 设计

runtime 负责所有“站点交互真相源”行为，建议拆成小型、聚焦的组件，而不是把所有逻辑塞进 producer。

### 1. `VendEmailBrowserRuntime`

负责通过 MCP/Playwright 驱动浏览器：

- 打开 vend.email 注册页/登录页
- 填表、点击、等待页面跳转
- 抓取当前页面中的账号信息、alias 列表、错误提示
- 记录网络请求样本

### 2. `VendEmailVerificationMailbox`

负责登录配置中的真实收件邮箱管理端，并在对应邮件列表中：

- 轮询 vend.email 验证邮件
- 提取验证链接或验证码
- 产出统一的验证结果对象

当前参考实现与抓包阶段可先适配 `https://cxwsss.online/` 的 `emaillist` 结构，但对外职责应定义为“可配置真实收件邮箱来源适配器”，而不是 `cxwsss.online` 专用硬编码类。

### 3. `VendEmailSessionOrchestrator`

负责编排：

- 会话恢复
- 登录回退
- 注册回退
- alias 列表读取
- alias 创建流程

也就是说，producer 只负责“要多少 alias”，而 orchestrator 决定“通过什么顺序拿到这些 alias”。

## 服务账号状态持久化

### `VendEmailServiceState`

新增一个轻量状态对象，至少保存：

- `state_key`
- `service_email`：注册到 vend.email 的邮箱地址
- `service_password`
- `session_cookies`
- `session_storage`
- `last_login_at`
- `last_verified_at`
- `known_aliases`
- `last_capture_summary`
- `last_error`

### 状态恢复策略

运行顺序固定为：

1. **恢复现有会话**
2. **会话失效则重新登录**
3. **仍无可用账号时重新注册**

这样可以降低：

- vend.email 风控触发概率
- 反复收验证邮件的频率
- 首个 provider 的整体不稳定性

### 存储边界

第一阶段只要求本地仓库运行环境内可恢复，不要求跨机器同步。状态持久化可以使用仓库内现有轻量持久化方式或新增一个专用状态文件，但必须：

- 不污染 alias lease 模型
- 能按 `state_key` 定位
- 能保存最近一次可用会话快照

## 抓包设计

### 目标

抓包不是为了完整 HAR 归档，而是为了沉淀未来协议化所需的关键请求样本。

本次至少采集以下类别：

1. vend.email 注册提交
2. vend.email 邮件验证确认
3. vend.email 登录提交
4. vend.email alias 创建请求
5. vend.email alias 列表查询请求

### 保存内容

每类请求记录摘要：

- `name`
- `url`
- `method`
- `request_headers_whitelist`
- `request_body_excerpt`
- `response_status`
- `response_body_excerpt`
- `captured_at`

### 保存原则

- 不要求保存完整无删减包体
- 优先保存对协议复现有价值的字段
- 敏感字段允许掩码处理
- 抓包样本要和 `VendEmailServiceState` 关联，以便知道样本来自哪个服务账号状态

## Alias lease 装配

从 vend.email 拉取到 alias 后，统一包装为：

- `alias_email`: vend.email 提供的 alias 邮箱
- `real_mailbox_email`: 使用当前 source 配置中的 `mailbox_email`
- `source_kind`: `vend_email`
- `source_id`: 对应 source 配置 `id`
- `source_session_id`: 当前 vend.email service state / session 标识

这样现有主链路对 vend.email 和其他 source 没有消费差异。

## 任务装配路径

`api/tasks.py::_build_alias_pool()` 当前已支持：

- `static_list`
- `simple_generator`

本次扩展为：

- `static_list` → `StaticAliasListProducer`
- `simple_generator` → `SimpleAliasGeneratorProducer`
- `vend_email` → `VendEmailAliasServiceProducer`

统一保持以下流程：

1. 创建 `AliasEmailPoolManager`
2. 遍历归一化后的 `sources`
3. 为每个 source 实例化 producer
4. `manager.register_source(producer)`
5. `producer.load_into(manager)`

## 错误处理

### 1. 页面流程错误

例如 vend.email 页面结构变化、按钮失效、登录表单消失。

处理策略：

- 记录页面步骤上下文
- 保存失败截图或页面快照路径
- producer 状态转 `FAILED`

### 2. 收信错误

例如在当前配置的真实收件邮箱来源中没有等到验证邮件，或邮件内容无法提取链接/验证码。

处理策略：

- 允许有限轮询超时
- 保存最后一次邮件列表摘要
- 将错误写入 service state 的 `last_error`

### 3. 会话恢复错误

例如 cookie 已过期、恢复后页面仍显示未登录。

处理策略：

- 自动降级到重新登录
- 不直接判定服务彻底失效

### 4. alias 创建错误

例如 alias 已存在、接口返回验证失败、单个 alias 创建失败。

处理策略：

- 优先把已存在 alias 列表拉回本地再决定是否继续创建
- 若至少能供给部分 alias，则允许本次部分成功
- 只有完全无法供给时才将 source 视为失败

## 测试设计

保持当前仓库的 `unittest` 风格，测试分为两层。

### 1. 自动化单元测试

在仓库测试中覆盖：

1. `config normalize`
   - `vend_email` source 被正确归一化
2. `producer contract`
   - producer 初始状态 / 成功状态 / 失败状态
   - 投递出的 lease 字段正确
3. `state restore decision`
   - 有可用会话时优先恢复
   - 恢复失败时回退登录
   - 登录失败时回退注册
4. `capture record format`
   - 抓包记录摘要字段完整
5. `task integration`
   - `_build_alias_pool()` 在 `vend_email` source 下能装配 producer

这些测试使用 fake runtime / mock state store，不依赖真实 vend.email 网站。

### 2. 手动 smoke / 抓包验证

真实站点交互采用手动或半自动 smoke：

1. 用 MCP/Playwright 打开 `https://www.vend.email/auth/register`
2. 完成注册与邮箱验证
3. 完成登录
4. 创建 alias
5. 导出关键网络请求摘要

这是这次实现能否进入仓库的关键验收依据之一，因为 provider 的真相源是外部站点，不应仅靠 mock 测试声称“已经支持”。

## 影响范围

### 新增文件

- `docs/superpowers/specs/2026-04-16-vend-email-alias-service-design.md`
- `core/alias_pool/vend_email_service.py`
- 视具体拆分情况，可能新增 vend.email runtime / state / capture 相关文件

### 修改文件

- `core/alias_pool/config.py`
- `api/tasks.py`
- `tests/test_alias_pool.py`
- `tests/test_register_task_controls.py`
- 视最终落点，可能新增或修改 vend.email / alias service 专项测试文件

## 风险与取舍

### 1. 外部站点不稳定

vend.email 页面结构、风控策略或接口字段可能变化，因此第一阶段必须保留浏览器自动化真相源，而不是一开始就强行协议化。

### 2. 真实收件邮箱读取链路依赖外部站点

当前抓包阶段依赖的 `cxwsss.online` 只是参考环境；无论最终接入哪个真实收件邮箱站点，只要该站点管理端交互不稳定，都会直接影响注册验证，因此收信读取组件必须独立且可诊断。

### 3. 会话恢复与首次注册耦合

如果不做 service state 持久化，后续每次任务都重新注册 vend.email 账号，风险和成本都会明显增高。因此这次即使不做复杂账号池，也必须有最小状态持久化。

### 4. 先跑通优先于抽象完美

这次的重点是“把第一个真实 alias service provider 真正接进 alias pool”，不是一次性做出最终框架。只要职责边界清楚，vend.email 特有逻辑允许先集中在 provider/runtime 子树中。

## 验收标准

满足以下条件即可视为本次设计对应的实现完成：

1. `vend_email` source 能被 config normalize 识别
2. `_build_alias_pool()` 能装配 `VendEmailAliasServiceProducer`
3. producer 能通过 runtime 恢复或建立 vend.email 会话
4. 能通过当前配置的真实收件邮箱来源完成 vend.email 验证邮件读取
5. 能在 vend.email 中获得至少一个可用 alias 并投递到 alias pool
6. lease 可被现有主链路像其他 source 一样消费
7. vend.email 服务账号状态可持久化并在下一次运行中优先恢复
8. 关键抓包样本摘要被保存，后续可用于协议化分析
