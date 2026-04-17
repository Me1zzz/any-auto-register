# 别名邮箱服务自动化注册流程开发手册

## 文档目的

这份文档用于归档 **vend mail 别名邮箱服务自动化注册流程** 在本仓库中的通用开发范式，供后续其他别名邮箱服务（alias service）的自动化注册/登录/验证/生成 alias 开发复用。

它不是某个具体服务的实现说明，而是一份 **阶段式开发手册**。目标读者是后续要接入新 alias service 的开发者。文档重点回答的是：

- 新服务进来时应该先做什么
- 哪些能力必须抽象成通用层
- 哪些信息只能作为参考环境，不能写死到运行时代码
- 什么时候应该先做 standalone probe
- 什么时候才适合接入正式 alias provider / 前端测试入口

## 适用范围

适用于这类别名邮箱服务：

- 需要先注册服务账号
- 需要读取验证邮件或确认链接
- 需要登录目标站点
- 需要创建 alias / forwarder / mailbox 映射
- 最终要把 alias 输出给现有 alias pool / 独立 probe / 前端测试入口

典型例子：

- vend.email 这类“服务账号 + alias/forwarder 创建”型网站
- 需要外部邮箱验证站点协同完成确认的 alias service

不适用于：

- 本地纯算法生成 alias（如 `simple_generator`）
- 没有账号系统、没有验证邮件、没有外部站点状态的静态列表 alias source

---

# 阶段 0：先明确为什么要先做 standalone probe

## 目标

在接入正式 alias provider、任务主流程或前端 UI 之前，先证明：

> 当前 source 配置，能不能独立地生成一个真实可用 alias。

## 为什么必须先做

如果直接把一个新 alias service 接进正式注册流程，会把多个问题混在一起：

- 是 source 配置错了
- 是 mailbox verification 失败了
- 是 runtime 登录失败了
- 是 alias 创建失败了
- 还是平台注册主流程本身有问题

standalone probe 的价值，就是把这些问题从正式任务主链路中剥离出来，让开发者先证明：

- 单次 alias 生成链路是通的
- 结果和抓包摘要是结构化可读的
- 错误能被归因到某一步

## 产出物

- 单次 probe 能力
- 结构化 probe 结果
- 最小可用的手动测试入口 / API 入口

## 关键决策

- probe 和正式 provider **出口不同**，但底层 runtime 应共享
- 先做“能生成一个 alias”，再做“能批量供给 alias”

## 常见坑

- 一上来就把新服务塞进 `/tasks/register`
- 还没跑通单次 alias 生成，就开始做前端入口
- 把 probe 写成另一套平行逻辑，后面再和正式 provider 漂移

---

# 阶段 1：站点侦察与抓包

## 目标

搞清楚目标 alias service 的真实流程，并把关键请求样本沉淀下来。

## 要回答的问题

1. 注册入口是什么？
2. 登录入口是什么？
3. 确认邮件是链接还是验证码？
4. alias/forwarder 创建是表单、XHR、还是 API？
5. 服务的免费/付费域名、收件人语义是什么？

## 产出物

- 注册请求样本
- 重发确认请求样本
- 登录请求样本
- alias / forwarder 创建请求样本
- mailbox 站点取邮件请求样本

## 关键决策

- 先以真实浏览器/MCP 跑通流程，再考虑协议化
- 抓包不是临时调试信息，要结构化保存为 capture summary

## 建议抓取的最小请求集合

- register submit
- resend confirmation
- login submit
- list aliases / list forwarders
- create alias / create forwarder
- mailbox login
- mailbox email list / email detail

## 常见坑

- 只看页面提示，不抓网络请求
- 把一次临时抓包当成“实现完成”
- 忘记确认“创建的到底是 alias 还是 forwarder”

---

# 阶段 2：配置建模

## 目标

把真实运行所需参数收敛成配置模型，而不是把参考环境写死进代码。

## 必须配置驱动的字段

至少包括：

- `register_url`
- `mailbox_base_url`
- `mailbox_email`
- `mailbox_password`
- `alias_domain`
- 如果需要，还包括：
  - `mailbox_account_id`
  - `mailbox_token`
  - `confirmation_anchor`
  - `alias_domain_id`
  - `state_key`

## 产出物

- source 配置模型
- normalize 规则
- 运行时依赖字段列表

## 关键决策

- 配置字段必须够表达真实运行所需参数
- 参考环境的域名/账号/密码，只能作为样本，不是运行时代码默认值

## 常见坑

- 把 `cxwsss.online` 之类参考域名写进运行时代码命名
- 在 helper 或 runtime 里偷偷依赖某个固定账号/密码
- 把 UI 表单结构直接当 runtime 内部结构，不做 normalize

---

# 阶段 3：mailbox verification 适配器

## 目标

把“登录外部邮箱站点 → 拉全部邮件 → 提取确认链接/验证码”抽成一个可替换的 adapter/helper 层。

## 产出物

- mailbox login request builder
- mailbox token/session helper
- mailbox email list request builder
- confirmation link / code extractor

## 关键决策

- adapter 必须 **配置驱动**
- adapter 可以针对一种 mailbox web API contract 做 helper，但不能把参考域名写进命名
- “站点名”不是抽象边界，“职责”才是

## 推荐职责拆分

- 构造 mailbox 登录请求
- 从 storage 中提取 token
- 构造“全部邮件”请求
- 从邮件内容中提取 anchored link 或验证码

## 常见坑

- helper 名字写得像“通用邮箱协议层”，实际却只服务一种接口
- 在 adapter 里直接夹带目标 alias service 的站点名
- 让前端去理解 mailbox 登录或取件逻辑

---

# 阶段 4：runtime / state / capture 分层

## 目标

把 alias service 的运行时逻辑拆成：

- state
- runtime / orchestrator
- capture

让它既能服务正式 provider，也能服务 standalone probe。

## 1. service state

至少包括：

- `service_email`
- `service_password`
- `session_cookies`
- `session_storage`
- `known_aliases`
- `last_capture_summary`
- `last_error`

## 2. runtime / orchestrator

负责协调：

- restore session
- register
- fetch confirmation link
- confirm
- login
- list aliases / forwarders
- create alias / forwarder

## 3. capture summary

capture 不是“调试垃圾”，而是后续协议化资产。至少保留：

- name
- url
- method
- request headers white list
- request body excerpt
- response status
- response body excerpt
- captured_at

## 产出物

- `ServiceState`
- `CaptureRecord`
- `RuntimeExecutor` / `RuntimeService`

## 关键决策

- runtime 的职责是“编排”，executor 的职责是“执行”
- probe 不应该复制一份 runtime 逻辑
- state/capture 持久化必须在 probe 和 provider 之间共享

## 常见坑

- 把 runtime 逻辑塞进 provider 或 probe 里
- capture 记录格式不稳定，后面没法复用
- service state 和 mailbox config 混成一个概念

---

# 阶段 5：从 runtime 接到 probe / API / 前端入口

## 目标

把底层 runtime 能力一路接到：

- `AliasSourceProbeService`
- 独立 alias-test API
- `Settings` 测试卡片

## 推荐接法

### 1. probe 层

`AliasSourceProbeService` 只做：

- 选择 source
- 分发到合适的 probe/runtime
- 聚合 `AliasProbeResult`

**不要**在 probe 层平行重写一套 vend 逻辑。

### 2. API 层

独立 alias-test API 只做：

- 读 saved config / draft config
- normalize
- 选择 source
- 调用 probe service
- 返回结构化结果

### 3. 前端测试入口

前端只负责：

- 选择 source
- 选择 saved / draft 模式
- 发起请求
- 展示 alias / serviceEmail / steps / capture / error

## 产出物

- `AliasProbeResult`
- `/api/config/alias-test`
- `Settings` 测试卡片

## 关键决策

- 前端不承担流程逻辑，只负责触发和展示
- saved config 和 draft config 的 source 选择必须语义一致
- response contract 稳定优先，内部实现可以继续演进

## 常见坑

- probe 层直接 new 一套 vend 伪逻辑
- API 把 backend 内部实现细节原样暴露成不稳定 contract
- 前端在 saved/draft 模式切换时 source list 语义漂移

---

# 阶段 6：什么时候算“完成”

## 最低完成标准

一个新 alias service 至少满足以下条件，才算“可开始前端测试”：

1. standalone probe 可跑通
2. probe 返回结构化 alias 结果
3. capture summary 有稳定结构
4. mailbox 参数完全配置驱动
5. 前端测试入口能看到真实 alias / serviceEmail / error

## 更高一级完成标准

一个新 alias service 只有在以下条件满足时，才算“可接正式 alias provider”：

1. standalone probe 稳定
2. runtime / state / capture 复用良好
3. provider 复用的是同一套 runtime，而不是平行逻辑
4. alias provider 能向 alias pool 投递真实 alias

## 验收分层

- 单元/契约测试
- API/前端集成验证
- 手动真实站点验证

## 常见坑

- 只看 unittest 通过就宣布“服务已接通”
- 前端能显示 placeholder 结果就当作真实 probe 完成
- 正式 provider 和 standalone probe 走成两条不同实现线

---

# 强规则（Hard Rules）

这些规则建议作为后续接入任何 alias service 的硬约束：

1. **参考域名不是运行时语义**
   - 参考环境只能出现在样例、抓包记录、手动验证说明中
   - 不能进入运行时代码命名或默认行为

2. **probe 不得平行重写 runtime 逻辑**
   - probe 与正式 provider 可出口不同
   - 但底层 runtime 必须共享

3. **先做 standalone probe，再接 provider**
   - 没有独立 probe 的新服务，不应直接接进正式注册任务主流程

4. **capture summary 是资产，不是垃圾**
   - 关键请求样本必须结构化保存

5. **前端测试入口只负责触发和展示**
   - 所有服务流程逻辑都留在 backend runtime / adapter

6. **saved / draft 语义必须一致**
   - source 选择和配置来源不能彼此矛盾

---

# 反模式清单（Anti-Patterns）

以下做法在后续新服务开发中应视为反模式：

- 把参考域名写进类名、helper 名、默认 config
- 在 probe 层再手写一套 vendor 流程
- 前端根据 source type 自己分支流程逻辑
- capture 只保存在临时日志里，不进结构化结果
- 用 fake executor 冒充“真实接通”
- 正式 provider 和 standalone probe 使用两套不同 runtime

---

# 新 alias service 开发 checklist

## 设计前

- [ ] 确认站点属于“需要账号+验证+alias 创建”的类型
- [ ] 明确参考环境与运行时配置边界

## 抓包侦察

- [ ] 注册请求抓到
- [ ] 确认请求抓到
- [ ] 登录请求抓到
- [ ] alias / forwarder 创建请求抓到
- [ ] mailbox 登录与取件请求抓到

## 配置建模

- [ ] register_url
- [ ] mailbox_base_url
- [ ] mailbox_email
- [ ] mailbox_password
- [ ] alias_domain / domain_id
- [ ] state_key / 其他 runtime 必需字段

## 后端能力

- [ ] mailbox verification adapter
- [ ] service state / capture summary
- [ ] runtime / executor / orchestrator
- [ ] standalone probe
- [ ] alias-test API

## 前端入口

- [ ] Settings 卡片可选 source
- [ ] saved / draft 模式切换正确
- [ ] alias / serviceEmail / error 展示正常
- [ ] capture / steps / logs 可见

## 验收

- [ ] 单元/契约测试通过
- [ ] API tests 通过
- [ ] 前端 build 通过
- [ ] 真实手动验证跑通

---

# 与 vend mail 这次实践的关系

vend mail 这次的价值，不在于“它是一个特殊站点”，而在于它把一条完整链路都踩出来了：

- 参考环境抓包
- mailbox verification 抽象
- runtime/state/capture 分层
- standalone probe 入口
- 前端 Settings 测试卡片
- 从 placeholder 到真实 runtime 复用的演进

后续其他 alias service 开发时，应该把 vend 当作**方法论样本**，而不是把 vend 的具体域名、字段名、站点习惯直接复制过去。
