## 背景与目的

当前 ChatGPT 的 GUI OAuth 链路只覆盖通过 CPA 提供的 OAuth 链接进入注册/登录的路径，无法覆盖“先在官网完成账号注册，再进入 Team 工作空间，再复用既有登录链路完成 OAuth”的业务变体。现在需要把这条变体纳入同一套自动化体系，以便复用现有 GUI 登录能力、支持 Team 场景下的账号初始化流程，并在流程结束后完成工作空间清理。

## 变更内容

- 为 ChatGPT 的 Codex GUI OAuth 链路新增一个“官网注册优先”的流程变体，但仅在前端明确提供 Team 会员账号配置时才启用该变体。
- 如果前端未提供 Team 会员账号配置，则必须自动回退到现有 GUI 操控链路，而不是尝试进入官网注册变体。
- 在该变体中，注册入口改为 ChatGPT 官网注册页，而不是直接从 CPA OAuth 链接进入注册。
- 从“创建密码完成”之后开始，尽量复用现有 GUI 注册链路中的 OTP、资料补全、终态判断与 consent 处理能力。
- 在注册完成后插入 Team 工作空间成员管理步骤：由一个 Team 会员账号将新账号加入目标工作空间。
- 加入工作空间后，复用现有 GUI 登录链路完成 OAuth 登录与后续授权收敛。
- 在登录阶段结束后，无论登录成功还是失败，都必须执行 Team 会员账号移除当前子账号的清理步骤。
- 成员移除必须成功才允许流程继续；若多次重试后仍无法移除，则整个任务必须失败。
- 为后续“移除失败后切换新的 Team 会员账号继续邀请与移除”的补偿能力预留设计扩展口，但本次不实现该补偿逻辑。
- 为新变体补充配置、结果元数据、错误边界与测试覆盖，避免影响现有默认 GUI OAuth 注册/登录链路。

## 能力清单

### 新增能力
- `chatgpt-oauth-official-signup-variant`: 定义 ChatGPT GUI OAuth 的官网注册变体，包括官网注册、加入工作空间、复用登录 OAuth、以及流程结束后的移除工作空间成员清理。

### 修改能力

## 影响范围

- 受影响代码：`platforms/chatgpt/chatgpt_registration_mode_adapter.py`、`platforms/chatgpt/codex_gui_registration_engine.py`、`platforms/chatgpt/codex_gui/workflows/*`、`platforms/chatgpt/codex_gui/steps/*`，以及 Team/workspace 相关辅助模块。
- 受影响集成：ChatGPT 官网注册页、CLIProxyAPI 提供的现有 OAuth 登录入口、Team 工作空间成员管理能力。
- 受影响配置：ChatGPT GUI 模式配置需要支持“仅当提供 Team 会员账号时启用官网注册变体”的判定，并提供 Team 会员账号、目标工作空间、移除重试策略等所需参数。
- 受影响测试：`tests/test_codex_gui_registration_engine.py` 及与 ChatGPT 注册模式、OAuth/workspace 处理相关的测试需要新增场景。
