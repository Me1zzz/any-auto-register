# CloudMail 别名邮箱来源池化架构设计

## 背景

当前 CloudMail 注册链路中，别名邮箱来源只有一种：配置中的“别名邮箱列表”。实际生产路径位于 `core/base_mailbox.py` 的 `CloudMailMailbox._pick_alias_email()`，其行为是从 `cloudmail_alias_emails` 中随机选择一个别名邮箱，并在 CloudMail 的 `emailList` 中结合真实收件邮箱上下文读取验证邮件。

现阶段需要为该链路扩展新的别名邮箱来源，并为后续多个“在别名邮箱服务站点自动注册账号、完成验证、登录并生成别名邮箱”的来源预留统一架构。用户已明确以下约束：

1. 一次任务中的邮箱来源可能同时来自：
   - 别名邮箱列表
   - A 别名邮箱服务
   - B 别名邮箱服务
   - 后续新增的更多别名邮箱服务
2. 别名邮箱服务的邮箱生成应做成异步补货，而不是主链路同步现取。
3. 系统应维护“任务级总别名邮箱池”，主注册链路从池中取可用邮箱。
4. 所有启用的别名邮箱服务在任务启动时就开始异步执行注册、登录、验证和别名生成流程，并持续向池中投递邮箱。
5. 每种别名邮箱服务在池中的可持有邮箱数有独立上限。
6. CloudMail 继续负责验证邮件读取，不改成新的收件后端。
7. 旧的 static list 配置必须兼容。

## 目标

构建一个可扩展的、任务级的别名邮箱供应架构，使注册主链路不再直接依赖“别名邮箱列表”这一单一来源，而是统一从总别名邮箱池消费。该架构需要同时支持：

- 现有静态别名邮箱列表
- 多个异步运行的别名邮箱服务生产者
- CloudMail 作为验证邮件读取后端
- 每来源独立容量控制
- source 级 / session 级 / item 级失败隔离
- 对现有平台注册链路保持最小侵入

## 非目标

本次设计不包含以下范围：

- 不在本次设计中实现任何具体别名邮箱服务站点的自动化逻辑
- 不把别名邮箱池做成跨任务共享的全局池
- 不把 CloudMail 替换为新的邮箱 provider
- 不设计完整前端新界面，只要求后端配置模型可兼容旧前端，并为后续 UI 升级预留结构
- 不把“别名服务账号”设计成长期持久化资源池；本阶段采用任务内临时 session

## 现状总结

### 当前关键耦合点

- `core/base_mailbox.py`
  - `create_mailbox(...)` 为 `cloudmail` 构建 `CloudMailMailbox`
  - `CloudMailMailbox._pick_alias_email()` 只支持 list-only 来源
  - `CloudMailMailbox.get_email()` 返回给平台注册链路的邮箱身份
  - `CloudMailMailbox.wait_for_code()` 从 CloudMail `emailList` 读取验证码
- `api/tasks.py`
  - `_run_register()` 负责构建 mailbox 并注入平台注册流程
- `platforms/chatgpt/plugin.py`
  - 平台通过 `GenericEmailService` 消费 mailbox 能力
- `tests/test_cloudmail_mailbox.py`
  - 覆盖当前 alias 选择、收件匹配与验证码轮询行为

### 当前问题

1. 别名来源硬编码为静态列表
2. 主链路无法从多个来源统一消费
3. 没有异步补货能力
4. 没有针对不同来源的容量控制与失败隔离
5. CloudMailMailbox 同时承担“来源选择”和“收件查码”两类职责，边界偏重

## 总体设计

### 核心思想

将当前“CloudMailMailbox 直接从静态列表取别名邮箱”的模型，改为“任务级总别名邮箱池 + 多 source 异步 producer 补货 + CloudMailMailbox 只负责消费当前租用邮箱并读取验证码”的模型。

设计后的职责分层如下：

1. **AliasEmailPoolManager** 维护任务级总别名邮箱池
2. **AliasSourceProducer** 表示一个具体来源的异步生产者
3. **StaticAliasListProducer** 将现有静态列表注入池中
4. **AliasServiceProducer** 在后台执行站点注册/验证/登录/生成 alias，并持续补货
5. **CloudMailMailbox** 不再决定“去哪里拿 alias”，只负责：
   - 从 pool 取得当前 alias lease
   - 根据 alias / real mailbox 上下文读取 CloudMail 验证邮件
6. **平台侧注册逻辑** 继续通过 mailbox/email service 接口消费邮箱，不感知来源差异

## 架构组件

### 1. AliasEmailLease

表示一个可被主注册链路消费的别名邮箱租约，不能只用字符串表示。建议字段：

- `alias_email`: 实际用于平台注册的邮箱地址
- `real_mailbox_email`: CloudMail 真实收件邮箱
- `source_kind`: 来源类型，如 `static_list`、`alias_service_a`
- `source_id`: 来源配置标识
- `source_session_id`: 该来源当前会话标识
- `status`: `available` / `leased` / `consumed` / `invalid`
- `metadata`: 调试和追踪信息，例如注册邮箱、生成序号、站点账号标识、错误上下文
- `created_at`: 生成时间

该对象是主链路、pool manager、mailbox 三方之间的统一载体。

### 2. AliasEmailPoolManager

任务级总池管理器，负责：

- 保存所有来源投递的 `AliasEmailLease`
- 维护 lease 生命周期状态
- 为主注册链路提供 `acquire_alias()` 能力
- 追踪各 producer 的运行状态
- 实现池空等待和最终失败判定
- 实现每来源在池中的 available 数上限

该组件不负责具体站点注册逻辑，只负责池状态与消费协调。

### 3. AliasSourceProducer

统一的来源生产者接口，每种 source 都实现同一协议。建议能力包括：

- `start()`
- `stop()`
- `run()`
- `state()`
- `fill_pool_if_needed()`

其职责是：按来源配置生成 alias 并投递到 pool。

### 4. StaticAliasListProducer

对现有静态列表来源的兼容实现。行为要求：

- 任务启动时将 `cloudmail_alias_emails` 或归一化后的静态列表配置装载为 `AliasEmailLease`
- 每个条目进入池时即处于 `available`
- 不涉及 session、登录、验证、异步外部站点流程
- 仍保留现有随机/轮转选择策略的兼容空间

这是新架构下对旧逻辑的直接映射。

### 5. AliasServiceProducer

表示一个具体站点型别名服务来源。该 producer 负责：

1. 生成 CloudMail 域名注册邮箱
2. 在别名邮箱服务站点注册账号
3. 在 CloudMail 管理员邮箱 `emailList` 中找到验证邮件
4. 驱动无头浏览器完成验证
5. 登录站点并获得 cookie/token/session 等认证信息
6. 按当前 session 连续生成 alias
7. 把生成出的 alias 作为 lease 投递到池中
8. 当达到 session 上限或 session 失效时，重建临时 session

### 6. SourceSessionFactory / AliasServiceSession

站点型来源不应把所有逻辑直接塞在 producer 中。建议再拆一层临时 session 抽象：

- `SourceSessionFactory`: 负责创建一个新的站点临时账号会话
- `AliasServiceSession`: 表示一个任务内临时可用的站点账号上下文

该 session 至少应持有：

- 注册邮箱
- 登录态 / cookie / token
- 当前已生成数量
- session 状态
- 调试信息

该 session 生命周期仅限于当前任务，不做长期持久化账号池。

### 7. CapacityPolicy

统一表达容量和重建规则。需要覆盖两层上限：

1. **来源在池中的 available 上限**
   - 防止某个 source 无限补货占满总池
2. **单个 session 的最大生成数**
   - 达到上限后重建新的临时 session

建议最小配置项：

- `pool_max_available_per_source`
- `session_max_generated`
- `session_max_retries`
- `item_max_retries`
- `acquire_timeout_seconds`
- `pool_poll_interval_seconds`

## 运行模型

### 任务启动阶段

注册任务启动时，执行如下流程：

1. 初始化 `AliasEmailPoolManager`
2. 对旧配置和新配置做归一化
3. 创建所有启用的 source producers
4. 由 `StaticAliasListProducer` 先把静态邮箱装入池中
5. 并行启动所有 `AliasServiceProducer`
6. 主注册链路开始通过 `acquire_alias()` 从池中获取可用邮箱

### 主注册链路

主注册链路不直接向某个 source 请求邮箱，而是：

1. 向 pool manager 请求一个 `available` lease
2. 将该 lease 绑定到当前 `CloudMailMailbox`
3. 用 `alias_email` 完成平台注册
4. 在验证码阶段由 `CloudMailMailbox` 使用：
   - `alias_email`
   - `real_mailbox_email`
   - CloudMail `emailList`
   来匹配目标邮件
5. 在注册结果明确后回写 lease 状态：
   - 成功使用完成 -> `consumed`
   - 明确不可用 -> `invalid`
   - 若后续确有需要，可为未真正消耗的 lease 增加回收策略；本阶段默认不复用已租出 lease

### Producer 异步补货链路

每个 source producer 独立运行，逻辑如下：

1. `boot`
   - 读取 source 配置
   - 注册到 pool manager
2. `prepare_session`
   - static list 无需 session
   - 站点型 source 创建新的临时 session
3. `generate_aliases`
   - 在当前 session 下持续生成 alias
   - 为每个 alias 创建 lease 并投递到池中
4. `throttle_on_capacity`
   - 当该来源在池中的 available 数达到上限时暂停补货
5. `rotate_session`
   - 当前 session 达到最大可生成数，或 session 明确失效时，重建 session
6. `failed / exhausted`
   - 达到本任务内允许的最大失败次数，或来源明确不可用时退出

### 水位控制

每个 source producer 不是无限制生成邮箱，而是按池中水位补货：

- 当该 source 的 `available` 数低于上限时继续补货
- 当达到上限时暂停
- 当主链路消费后，producer 可恢复补货

该策略保证：

- 不会在任务启动后立刻把所有来源全部造满
- 每个来源只持有受控数量的待用邮箱
- 来源之间可以公平共存于同一总池

## 失败分类与隔离

为避免所有错误都被同一种重试逻辑处理，设计中明确三层失败：

### 1. Item 级失败

表示某个 alias 条目本身无效，但不意味着 session 或 source 失效。示例：

- 生成出的 alias 已存在
- alias 格式非法
- 该条目被平台注册链路判定无效

处理方式：

- 将该 lease 标记为 `invalid`
- producer 继续在当前 session 中生成下一个 alias

### 2. Session 级失败

表示当前站点临时账号会话不可继续使用。示例：

- 达到站点单账号最大别名生成数
- cookie / token 失效
- 账号验证状态异常
- 登录态损坏

处理方式：

- 丢弃当前 `AliasServiceSession`
- 重新生成 CloudMail 注册邮箱
- 重建新的站点 session
- 不影响其他 source producer 继续运行

### 3. Producer / Source 级失败

表示某个来源在当前任务中不可继续。示例：

- 来源配置缺失
- 目标站点不可达
- 页面结构变化导致自动化失效
- 连续多次 session 重建失败

处理方式：

- 将该 producer 标记为 `failed` 或 `exhausted`
- 停止其后续补货
- 不影响其他 source 继续供给

## 池空等待与最终失败判定

主注册链路调用 `acquire_alias()` 时，可能遇到池暂时为空的情况。此时应按如下规则处理：

1. 如果池中没有 `available` lease，但仍有 producer 在运行，则等待补货
2. 等待应使用配置化超时，而不是无限阻塞
3. 只有在以下条件同时成立时，才判定 alias 供应失败：
   - 池中没有可用 lease
   - 所有 producers 都已进入 `failed` / `exhausted` / `stopped`

这一定义可以避免“池暂时为空但后台正在补货”时过早失败。

## 配置模型

### 新配置结构

建议将配置升级为两层：pool 级配置 + sources 列表。

#### Pool 配置

- `enabled`
- `acquire_timeout_seconds`
- `pool_poll_interval_seconds`
- `selection_policy`：`fifo` / `random` / `weighted`
- `max_total_available`（可选，先预留）

#### Source 配置

每个 source 一项，建议字段：

- `id`
- `type`
- `enabled`
- `priority` 或 `weight`
- `pool_max_available`
- `session_max_generated`
- `session_max_retries`
- `item_max_retries`

其中：

- `static_list` 额外包含 `emails`
- 站点型 source 额外包含 `base_url`、注册超时、验证超时、登录参数等

### 旧配置兼容策略

当前已存在字段：

- `cloudmail_alias_enabled`
- `cloudmail_alias_emails`
- `cloudmail_alias_mailbox_email`

兼容原则：

1. 后端继续读取旧字段
2. 在任务启动时统一做一次配置归一化
3. 若只提供旧字段，则自动映射为：
   - 一个默认 pool 配置
   - 一个 `static_list` source
4. 新逻辑只消费归一化后的配置结构

这样可以在不立刻改动前端所有配置界面的情况下完成后端架构升级。

## 代码边界与建议拆分

不建议继续把新逻辑塞进 `core/base_mailbox.py`。建议新增独立目录，例如 `core/alias_pool/`，拆分如下：

### `core/alias_pool/base.py`

负责定义：

- `AliasEmailLease`
- `AliasSourceProducer` 抽象接口
- 状态枚举
- 错误类型

### `core/alias_pool/manager.py`

负责实现：

- `AliasEmailPoolManager`
- `acquire_alias()`
- lease 状态流转
- producer 状态追踪
- 池空等待与最终失败判定

### `core/alias_pool/static_list.py`

负责：

- `StaticAliasListProducer`
- 旧静态列表兼容投递

### `core/alias_pool/service_base.py`

负责：

- 站点型来源 producer 基类
- `AliasServiceSession` / `SourceSessionFactory`
- session 重建与通用容量逻辑

### `core/alias_pool/config.py`

负责：

- 新旧配置归一化
- 默认配置补全
- 配置合法性检查

### `core/base_mailbox.py`

保留：

- `CloudMailMailbox` 收件与验证码读取能力
- alias / real mailbox 匹配逻辑

调整：

- 不再自己决定 alias 来源
- 改为消费当前 `AliasEmailLease`

### `api/tasks.py`

调整为：

- 在任务启动时初始化 task-scoped pool manager
- 启动 producers
- 将 pool-aware / lease-aware mailbox 注入平台注册流程

## 测试设计要求

本次实现必须保留并扩展现有 mailbox 测试语义，至少覆盖：

1. 旧 static list 配置可被归一化并成功进入池中
2. 主链路可从总池拿到 lease
3. 多 source 可并发补货，且互不覆盖
4. 单 source 在池中的 available 数达到上限后会暂停补货
5. session 达到生成上限后会重建
6. 某个 source failed 不影响其他 source 继续供给
7. 池暂时为空但 producer 仍在运行时，主链路会等待而不是立刻失败
8. 当全部 producers 终止且池为空时，主链路正确失败
9. `CloudMailMailbox` 仍能基于 alias / real mailbox 读取验证码

## 演进顺序建议

推荐按以下顺序实施：

1. 先引入 `AliasEmailLease` 与 `AliasEmailPoolManager`
2. 把旧 static list 迁移为 `StaticAliasListProducer`
3. 让 `CloudMailMailbox` 改为消费 lease，而不是 list-only 选择
4. 打通 task-scoped pool 初始化与主链路消费
5. 再接入首个 `AliasServiceProducer` 基类与 session 生命周期
6. 最后接入具体站点 provider 实现

这样可以先在不引入真实站点自动化的情况下，把新架构主干搭稳。

## 设计结论

本设计将“别名邮箱来源”从 CloudMailMailbox 的内部细节，升级为任务级的独立供应子系统：

- 主注册链路统一消费总别名邮箱池
- static list 与多个站点型来源可以同时供给
- 站点型来源在后台异步补货
- CloudMail 继续作为验证码读取后端
- 每来源容量受控，失败隔离明确
- 旧配置可平滑兼容

该架构满足当前需求，也为后续增加多个别名邮箱站点来源保留了稳定扩展点。
