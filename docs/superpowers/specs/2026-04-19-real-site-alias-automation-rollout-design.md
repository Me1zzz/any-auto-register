# 已调研别名服务真实站点自动化推进设计

## 背景

当前分支已经完成了别名服务 provider 子系统的第一阶段扩展：

- `vend_email` 仍是唯一已经接入真实站点链路的 provider
- `myalias_pro`
- `secureinseconds`
- `emailshield`
- `simplelogin`
- `alias_email`

都已经接入统一的 provider registry、alias-test API、前端固定单实例服务开关块，以及统一的 `AliasAutomationTestResult` / `accountIdentity` / `stages` / `failure` 结果模型。

但是，这 5 个新增 provider 当前大多仍处于 **contract / placeholder** 层，而不是 **真实站点自动化** 层：

- `core/alias_pool/myalias_pro_provider.py` 目前直接返回 `myalias-{index}@myalias.pro`
- `core/alias_pool/secureinseconds_provider.py` 目前直接返回 `secure-{index}@alias.secureinseconds.com`
- `core/alias_pool/emailshield_provider.py` 目前直接返回 `emailshield-{index}@emailshield.cc`
- `core/alias_pool/alias_email_provider.py` 目前直接返回 `alias-email-{index}@alias.email`
- `core/alias_pool/simplelogin_provider.py` 已实现已有账号选择、密码 fallback、signed option 解析与结构化失败语义，但还没有真实会话驱动的站点自动化流程

因此，当前前端“测试生成别名邮箱”按钮虽然已经可以真实触发 `/api/config/alias-test`，但其“成功”不等于对应 provider 已经打通真实站点。现状是：

- `vend_email`：真实 runtime
- `simplelogin`：真实 blocker 已暴露（`discover_alias_domains / signed domain options unavailable`）
- 其他 4 个新增 provider：多数还是 placeholder-contract success

本设计的目标，就是在不推翻现有 provider 子系统与前端/后端合同的前提下，把这 5 个新增 provider 从 placeholder 层推进到真实站点自动化层。

## 本轮需求

本轮设计基于以下已确认需求：

1. 不再只做 `simplelogin` 单点打穿，而是要 **并行推进所有服务**。
2. 但并行推进不能演变成 5 套互相打架的自动化代码，必须先冻结共享 runtime / adapter 边界。
3. `simplelogin` 优先使用已有账号：
   - 服务账号邮箱：`fust@fst.cxwsss.online`
   - 当前运营规则保持现状：如果 provider 配置里未显式填写密码，则沿用 existing-account provider 约定，默认密码回退为邮箱本身。
4. 前端“测试生成别名邮箱”入口继续保留，且要能区分：
   - 只是 contract 成功
   - 真实链路部分成功但被 gate 阻断
   - 真实链路完全成功

## 当前实现状态（作为设计输入）

### 1. 共享层现状

当前共享层已经具备：

- `core/alias_pool/interactive_provider_base.py`
- `core/alias_pool/interactive_provider_models.py`
- `core/alias_pool/interactive_provider_state.py`
- `core/alias_pool/interactive_state_repository.py`
- `core/alias_pool/interactive_provider_registry.py`

它们已经能提供：

- 统一的 `run_alias_generation_test(...)`
- 统一的 stage timeline
- 统一的 `AliasProviderFailure`
- 统一的 `accountIdentity`
- 统一的 `sources[]` 配置桥接

但当前共享层还没有真正意义上的：

- 浏览器会话 runtime
- 可恢复的站点页面状态容器
- provider-neutral 页面动作抽象
- 统一的邮件验证 / magic-link / forwarding-gate 读取执行器
- 真正驱动外站页面的 adapter 层

### 2. Provider 当前状态

| provider | 当前状态 | 是否真实站点自动化 |
|---|---|---|
| `vend_email` | 已接真实站点 | 是 |
| `simplelogin` | 已有账号、signed option parser、结构化失败 | 否 |
| `myalias_pro` | placeholder alias 返回 | 否 |
| `secureinseconds` | placeholder alias 返回 | 否 |
| `emailshield` | placeholder alias 返回 | 否 |
| `alias_email` | placeholder alias 返回 | 否 |

### 3. SimpleLogin 已知现场证据

本轮设计继续沿用已经验证过的现场事实：

1. `https://app.simplelogin.io/auth/login` 可直接访问
2. 使用 `fust@fst.cxwsss.online / fust@fst.cxwsss.online` 可以登录进入 dashboard
3. `https://app.simplelogin.io/dashboard/custom_alias` 页面包含 `signed-alias-suffix` 选择框
4. 每个选项的 value 是 **signed suffix token**，不是裸域名字符串
5. 已在真实页面上成功创建过非默认域名 alias，例如：
   - `sisyrun0419a.relearn763@aleeas.com`

这说明 SimpleLogin 的真实自动化主 blocker不是“站点不可访问”，而是：

- 需要把登录后页面获取、custom alias 页面进入、signed options 解析、alias 创建动作真正接到 provider runtime 里

## 目标

本轮设计目标如下：

1. 在现有 provider 子系统之上，新增一层 **真实站点自动化 runtime + adapter** 架构。
2. 允许 `simplelogin`、`myalias_pro`、`secureinseconds`、`emailshield`、`alias_email` 并行推进，但共享层边界必须先冻结。
3. 让每个 provider 都从 placeholder-contract 层逐步推进到 real-flow-complete 层。
4. 保持前端固定单实例服务块、后端 `sources[]`、以及 alias-test API 合同不变。
5. 让前端测试入口能够区分“contract 成功”和“真实站点成功”。

## 非目标

本设计明确不做以下事情：

1. 不重做 `vend_email` 的真实站点实现。
2. 不把整个系统改造成动态插件平台。
3. 不要求第一步就让 5 个服务全部一次性达到 real-flow-complete。
4. 不改变当前前端固定单实例服务块的交互模型。
5. 不实现 `manyme.com`。

## 推荐总体方案

### 总体结论

并行推进所有服务是可以的，但必须是：

- **共享 runtime 层先冻结**
- **provider adapter 层再并行**

也就是说，并行的不是“大家一起乱改 `InteractiveAliasProviderBase`”，而是：

1. 先定义稳定的共享 browser/session/runtime 接口
2. 再让 5 个 provider 分轨实现各自的 site adapter

否则并行只会把共享层变成不断被改写的流沙。

## 架构切分

### 1. 共享 runtime 层

建议新增一层 browser-driven shared runtime，例如：

- `core/alias_pool/browser_runtime.py`
- `core/alias_pool/browser_session_state.py`
- `core/alias_pool/browser_capture.py`

这一层负责：

1. 启动/复用浏览器会话
2. 页面打开与导航
3. cookie / localStorage / session state 恢复
4. 结构化抓包与关键请求摘要
5. 当前阶段记录
6. URL 安全检查

它 **不** 理解站点语义，不区分 `simplelogin` 或 `myalias_pro`。

### 2. 共享验证/邮箱层

建议新增一层 provider-neutral mailbox/gate 执行器，例如：

- `core/alias_pool/verification_runtime.py`
- `core/alias_pool/verification_mail_reader.py`

这一层负责：

1. 读取确认邮箱
2. 轮询验证码/验证信
3. 识别 magic-link / verification-link / forwarding-link
4. 对外返回结构化验证结果

它不负责决定“哪个 provider 要做什么 gate”，而是由 provider adapter 告诉它要消费什么类型的验证步骤。

### 3. provider adapter 层

建议把每个站点拆成真正的 adapter，而不是只靠 provider class 本身硬写：

- `SimpleLoginAdapter`
- `MyAliasProAdapter`
- `SecureInSecondsAdapter`
- `EmailShieldAdapter`
- `AliasEmailAdapter`

每个 adapter 都应实现统一的站点动作接口，例如：

```python
class AliasServiceAdapter(Protocol):
    def open_entrypoint(self, runtime) -> None: ...
    def authenticate_or_register(self, runtime, context) -> SiteSessionContext: ...
    def resolve_blocking_gate(self, runtime, gate, context) -> SiteSessionContext: ...
    def load_alias_surface(self, runtime, context) -> SiteSessionContext: ...
    def extract_domain_options(self, runtime, context) -> list[AliasDomainOption]: ...
    def submit_alias_creation(self, runtime, context, domain_option, alias_index: int) -> AliasCreatedRecord: ...
```

### 4. 现有 `InteractiveAliasProviderBase` 的角色

`InteractiveAliasProviderBase` 继续保留，但角色从“直接实现逻辑”收缩为“统一编排器”：

1. 组装 runtime
2. 调用 adapter
3. 记录阶段
4. 维护 `AliasAutomationTestResult`
5. 把 provider-specific 失败统一转成结构化 failure

换句话说，当前 provider class 里那些 placeholder `create_alias(...)` 返回假邮箱的逻辑，会被真实 adapter 行为替代。

## 并行分轨

建议把 5 个服务分成 3 条实现轨道，而不是 5 个完全独立项目。

### 轨道 A：existing-account + signed domain discovery

- `simplelogin`

特征：

1. 不做注册
2. 使用已有账号登录
3. 进入 custom alias 页面
4. 从页面/等价 bootstrap 中提取 signed options
5. 真实提交 alias 创建

这是最特殊的一条轨道。

### 轨道 B：register/login + account email verification gate

- `myalias_pro`
- `emailshield`

共享特征：

1. 需要注册新账号
2. 需要消费账号邮箱验证
3. 验证完成后才能继续登录或进入 alias surface

二者差异主要在 gate 出现位置，不在共享执行骨架本身。

### 轨道 C：继续权限 gate（forwarding / magic-link）

- `secureinseconds`
- `alias_email`

共享特征：

1. 主流程不会直接到 alias surface
2. 先要解决一个继续权限 gate
3. 再进入 domain discovery / alias creation

## 每个 provider 的真实验收标准

本轮必须明确：前端测试按钮的“成功”不再够用。每个 provider 都要按照以下等级验收。

### Level 1：contract-level

满足以下条件：

1. provider 能被测试卡片触发
2. 能返回结构化 `stages` / `failure` / `aliases`
3. 但 alias 可能仍然是本地拼出来的占位值

### Level 2：real-flow partial

满足以下条件：

1. 已经进入真实站点页面
2. 已执行部分真实动作
3. 但卡在真实 gate/blocker 上

例子：

- `simplelogin`：登录成功，但拿不到 signed options
- `emailshield`：登录成功，但 verify gate 尚未消费完成

### Level 3：real-flow complete

满足以下条件：

1. 完成真实站点关键流程
2. alias 由真实站点创建，而不是 provider 本地拼接
3. 测试结果里能拿到真实站点生成的 alias 数据

### SimpleLogin 真实完成标准

1. 使用 `fust@fst.cxwsss.online` 登录成功
2. 进入 custom alias 页面
3. 发现 signed domain options
4. 随机选择一个 signed option
5. 创建 3 个真实 alias
6. 返回结果中的 alias 不是固定模板字符串

### MyAlias Pro 真实完成标准

1. 真实注册
2. 收到并消费验证邮件
3. 登录成功
4. 真实创建 3 个 alias

### SecureInSeconds 真实完成标准

1. 真实注册/登录
2. 真实触发 forwarding verification gate
3. 收到并消费 forwarding verification
4. 真实创建 3 个 alias

### EmailShield 真实完成标准

1. 真实注册/登录
2. 真实触发 verify-email gate
3. 收到并消费验证邮件
4. 真实创建 3 个 alias

### Alias Email 真实完成标准

1. 真实请求 magic-link
2. 真实消费 magic-link
3. 拿到真实 domain bootstrap
4. 真实创建 3 个 alias

## 前端测试语义要求

当前前端测试卡片已经可以展示：

- `stages`
- `failure`
- `aliases`
- `accountIdentity`

本轮不一定要求增加新的大字段，但设计上必须把 3 类状态区分清楚：

1. `contract_ok`
2. `real_flow_partial`
3. `real_flow_complete`

实现上可以通过现有字段推导，但文档和 QA 判定必须明确区分：

- placeholder 成功
- 真实链路部分成功
- 真实链路完全成功

否则前端会出现“全绿但其实没打通”的误导。

## 推荐实施顺序

虽然用户要求并行推进所有服务，但推荐的技术顺序是：

### Phase 1：冻结共享 runtime 接口

1. 增加 browser runtime/shared verification/runtime 接口
2. 把 `InteractiveAliasProviderBase` 调整成编排器
3. 不在这个阶段打通任何站点，只稳定共享边界

### Phase 2：三轨并行实现 adapter

- 轨道 A：`simplelogin`
- 轨道 B：`myalias_pro` + `emailshield`
- 轨道 C：`secureinseconds` + `alias_email`

### Phase 3：统一 alias-test 验收提升

1. 把 provider 当前等级（contract / partial / complete）明确化
2. 把前端测试展示调整为可识别真实/占位状态
3. 跑整体验收

## 风险与处理

### 风险 1：并行推进时共享层反复被改写

处理：

- 共享层先冻结，再并行写 adapter

### 风险 2：SimpleLogin signed option 结构变化

处理：

- signed value 解析必须以 machine-readable token 为主，而不是依赖可见文本
- 必须保留结构化失败路径

### 风险 3：邮件验证链路时序不稳定

处理：

- 把邮件验证读取独立成共享 runtime
- 所有 provider 通过同一 verification reader 走

### 风险 4：前端测试按钮继续误导为“都已打通”

处理：

- 文档、QA 和展示语义都要显式区分 contract / partial / complete

## 与上一轮 spec 的关系

本设计不是替换 `2026-04-19-researched-alias-services-provider-expansion-design.md`，而是它的第二阶段。

两者关系如下：

1. 上一轮设计解决的是：
   - provider 子系统扩展
   - source model / frontend / alias-test 合同统一
   - 把 5 个新增 provider 接入统一架构

2. 本轮设计解决的是：
   - 如何把这 5 个 provider 从 placeholder-contract 推进到真实站点自动化
   - 如何在并行推进所有服务的前提下，避免共享 runtime 被反复改写

## 最终结论

本轮不应继续把 `myalias_pro / secureinseconds / emailshield / simplelogin / alias_email` 当成“已经接入”的终点，而应明确把它们看成：

- 已接入统一 provider 子系统
- 但尚未完成真实站点自动化

接下来的正确方向是：

1. 冻结共享 runtime / verification / adapter 接口
2. 按三条轨道并行推进 5 个服务
3. 用 contract / partial / complete 三层标准验收
4. 逐步把它们全部推进到 real-flow-complete

这也是在“并行做所有服务”的要求下，唯一既快又不至于把架构做烂的方式。
