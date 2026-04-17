# 别名邮箱服务自动化开发 Checklist

> 快速版。用于在开始一个新的 alias service 自动化注册/登录/验证/生成 alias 开发前，快速过一遍关键步骤与硬规则。详细说明请看：`docs/superpowers/alias-service-automation-development-guide.md`

---

## 0. 先判断是否需要走这套范式

适用：

- [ ] 需要注册服务账号
- [ ] 需要读取验证邮件或确认链接
- [ ] 需要登录站点
- [ ] 需要创建 alias / forwarder / mailbox 映射
- [ ] 最终需要把 alias 接到 alias pool / standalone probe / 前端测试入口

不适用：

- [ ] 纯算法生成 alias（如 `simple_generator`）
- [ ] 纯静态 alias 列表

---

## 1. 一定先做 standalone probe

- [ ] 不要一上来就接 `/tasks/register`
- [ ] 先证明“当前 source 配置能独立生成一个真实 alias”
- [ ] probe 和正式 provider 出口可不同，但底层 runtime 必须共享

最低产出物：

- [ ] 单次 probe 能力
- [ ] 结构化 probe 结果
- [ ] 最小 API 或手动测试入口

---

## 2. 站点侦察与抓包

至少抓到：

- [ ] register submit
- [ ] resend confirmation
- [ ] login submit
- [ ] list aliases / list forwarders
- [ ] create alias / create forwarder
- [ ] mailbox login
- [ ] mailbox email list / email detail

必须回答：

- [ ] 注册入口是什么
- [ ] 登录入口是什么
- [ ] 确认邮件是链接还是验证码
- [ ] 创建的是 alias 还是 forwarder
- [ ] 免费/付费域名与收件人语义是什么

---

## 3. 配置建模

必须配置驱动的字段至少包括：

- [ ] `register_url`
- [ ] `mailbox_base_url`
- [ ] `mailbox_email`
- [ ] `mailbox_password`
- [ ] `alias_domain`

如有需要继续补：

- [ ] `mailbox_account_id`
- [ ] `mailbox_token`
- [ ] `confirmation_anchor`
- [ ] `alias_domain_id`
- [ ] `state_key`

硬规则：

- [ ] 参考域名/账号/密码只能是样例，不能写死成运行时代码默认值
- [ ] UI 表单结构不能直接当 runtime 内部结构，必须做 normalize

---

## 4. mailbox verification 适配器

应该抽出来的 helper：

- [ ] mailbox login request builder
- [ ] token/session helper
- [ ] mailbox email list request builder
- [ ] confirmation link / code extractor

硬规则：

- [ ] helper 必须配置驱动
- [ ] 命名不能绑定参考域名
- [ ] 前端不理解 mailbox 登录或取件逻辑

---

## 5. runtime / state / capture 分层

### state

- [ ] `service_email`
- [ ] `service_password`
- [ ] `session_cookies`
- [ ] `session_storage`
- [ ] `known_aliases`
- [ ] `last_capture_summary`
- [ ] `last_error`

### runtime / orchestrator

- [ ] restore session
- [ ] register
- [ ] fetch confirmation link
- [ ] confirm
- [ ] login
- [ ] list aliases / forwarders
- [ ] create alias / forwarder

### capture summary

- [ ] `name`
- [ ] `url`
- [ ] `method`
- [ ] `request headers`
- [ ] `request body excerpt`
- [ ] `response status`
- [ ] `response body excerpt`
- [ ] `captured_at`

硬规则：

- [ ] runtime 编排，executor 执行
- [ ] probe 不得复制一份 runtime 逻辑
- [ ] state/capture 持久化必须在 probe 和 provider 之间共享

---

## 6. 从 runtime 接到 probe / API / 前端

### probe 层

- [ ] 只负责选择 source / 分发 / 聚合结果
- [ ] 不平行重写 vendor 流程

### API 层

- [ ] 读 saved config / draft config
- [ ] normalize
- [ ] 选择 source
- [ ] 调用 probe service
- [ ] 返回结构化结果

### 前端测试入口

- [ ] 选择 source
- [ ] 选择 saved / draft 模式
- [ ] 发起请求
- [ ] 展示 alias / serviceEmail / steps / capture / error

硬规则：

- [ ] 前端只负责触发和展示
- [ ] saved / draft 的 source 选择语义必须一致

---

## 7. 验收标准

### 可开始前端测试

- [ ] standalone probe 已跑通
- [ ] probe 返回结构化 alias 结果
- [ ] capture summary 结构稳定
- [ ] mailbox 参数完全配置驱动
- [ ] 前端入口能展示 alias / serviceEmail / error

### 可接正式 alias provider

- [ ] standalone probe 稳定
- [ ] runtime / state / capture 已分层
- [ ] provider 与 standalone probe 共享同一套 runtime
- [ ] alias provider 能向 alias pool 投递真实 alias

---

## 强规则（Hard Rules）

- [ ] 参考域名不是运行时语义
- [ ] probe 不得平行重写 runtime 逻辑
- [ ] 先做 standalone probe，再接 provider
- [ ] capture summary 是资产，不是调试垃圾
- [ ] 前端测试入口只负责触发和展示
- [ ] saved / draft 语义必须一致

---

## 反模式（Anti-Patterns）

- [ ] 把参考域名写进类名、helper 名、默认 config
- [ ] 在 probe 层再手写一套 vendor 流程
- [ ] 前端根据 source type 自己分支流程逻辑
- [ ] capture 只写临时日志，不进结构化结果
- [ ] 用 fake executor 冒充“真实接通”
- [ ] 正式 provider 与 standalone probe 使用两套不同 runtime

---

## 最后检查（开工前 / 提交前）

开工前：

- [ ] 我现在做的是 standalone probe 还是正式 provider？
- [ ] 参考环境有没有被我写成运行时代码语义？
- [ ] 我是否已经抓到关键请求样本？

提交前：

- [ ] 单元/契约测试通过
- [ ] API tests 通过
- [ ] 前端 build 通过
- [ ] probe 结果结构化可读
- [ ] 正式 provider 和 standalone probe 没有走成两套逻辑
