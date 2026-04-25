## 背景

当前 ChatGPT GUI OAuth 主链路由 `platforms/chatgpt/chatgpt_registration_mode_adapter.py` 选择 `CodexGUIRegistrationEngine` 执行，流程在 `platforms/chatgpt/codex_gui_registration_engine.py` 中按“注册工作流优先，必要时回退到登录工作流”编排。现有注册工作流定义在 `platforms/chatgpt/codex_gui/workflows/registration_workflow.py`，其中从 `SubmitRegistrationPasswordStep` 之后开始，OTP 提交、资料补全、终态判断、consent 收敛都已经具备可复用结构；现有登录补偿工作流定义在 `platforms/chatgpt/codex_gui/workflows/login_workflow.py`。

新需求不是简单替换某一步，而是新增一个跨多个模块的编排变体：官网注册、Team 工作空间加入、复用既有登录 OAuth、最后清理成员关系。该变体还依赖 Team/workspace 成员管理能力，而当前仓库只在 `platforms/chatgpt/__init__.py` 暴露了 invite/remove 包装函数，具体实现文件在当前 checkout 中不可见，因此设计必须把成员管理能力作为显式集成边界处理，而不是假定细节已经存在。

## 目标 / 非目标

**目标：**
- 为 ChatGPT GUI OAuth 增加一个可配置的新变体，明确区分“官网注册优先”与现有 CPA OAuth 入口链路。
- 只有当前端提供了 Team 会员账号配置时才启用官网注册变体；否则必须自动回退到现有 GUI 操控链路。
- 在不破坏现有默认 GUI 链路的前提下，复用已有注册尾段与登录工作流能力。
- 将 Team 工作空间加入与移除建模为显式步骤，纳入日志、结果元数据与失败策略。
- 让新变体在实现阶段可被拆分为可测试的 step/workflow/adapter 改动，而不是把逻辑散落在单个大函数中。

**非目标：**
- 不重写现有 `pyautogui`/`pywinauto` 检测与点击底层。
- 不在本次变更中重构整个 `CodexGUIRegistrationEngine` 为全新架构。
- 不假定存在公开的 ChatGPT Business 成员管理 API；成员加入/移除只抽象为仓库内已有或待补齐的辅助能力。
- 不扩展到其他平台或非 GUI 注册模式。

## 设计决策

### 1. 通过新增 GUI 子变体而不是覆写默认流程来接入
**决策：** 在 ChatGPT 注册模式适配层新增一个“official-signup”类 GUI 变体配置，但只有当前端提供了 Team 会员账号配置时才允许命中该变体；如果缺少 Team 会员账号配置，则必须自动回退到现有 GUI 链路。

**原因：** 当前稳定入口已经集中在 `chatgpt_registration_mode_adapter.py`。把“是否具备 Team 会员账号”这一前置条件放在适配层统一判定，可以避免 engine 内部出现过多前置分支，并能保证默认 GUI 行为保持不变。

**备选方案：**
- 直接替换现有 GUI 注册主链路：风险高，会影响已有 CPA OAuth 场景。
- 新建完全独立引擎：隔离性好，但与现有 step/workflow 复用面高度重叠，会造成重复实现。

### 2. 将流程拆成四段：官网注册、工作空间加入、OAuth 登录、工作空间移除
**决策：** 新变体按四个显式阶段编排，每个阶段映射到独立 workflow 或辅助调用，并在上下文中记录阶段结果。

**原因：** 该需求天然跨越注册、Team 管理和登录三个子系统。显式阶段化便于复用现有步骤、记录失败位置，并支持对“主流程成功但清理失败”做差异化处理。

**备选方案：**
- 把工作空间加入/移除塞进已有注册或登录 step：会模糊语义，也不利于后续测试。
- 完全只在引擎里串行调用若干 helper：实现快，但无法形成可维护的 step/workflow 边界。

### 3. 官网注册入口只替换前半段，密码后沿用现有注册尾段
**决策：** 新增官网注册起始步骤集合，用于打开官网注册页、进入邮箱/密码创建；从“密码提交完成”后的 OTP、资料补全、注册终态与 consent 逻辑复用现有 `registration_workflow.py` 中的后续步骤。

**原因：** 现有代码和测试已经表明密码后半段是明确的稳定分界点。重用这些步骤能减少选择器重复、保留既有错误恢复与 OTP 处理逻辑。

**备选方案：**
- 全量复制现有注册工作流再做官网入口改造：实现简单但后续维护会分叉。
- 完全抽象成任意可组合 step 图：灵活但对当前代码基来说过度设计。

### 4. Team 工作空间成员管理使用显式适配接口
**决策：** 设计中引入一个清晰的成员管理辅助边界，由引擎在“注册完成后、登录前”调用 invite/join，在“登录成功后或失败清理时”调用 remove。若仓库当前缺少具体实现，则实现阶段需先补齐该 helper 或兼容现有导出接口。

**原因：** 当前仓库只暴露了导出符号，未在本 checkout 中看到实现。把它设为明确依赖，可以让实现阶段先确认复用还是补齐，而不是把不确定性埋进 GUI step 内部。

**备选方案：**
- 直接在 GUI 流程里操控 Team 账号页面：没有证据表明现有仓库已经有这套 GUI 目标与步骤，且复杂度高。
- 依赖未验证的外部 API：风险不可控。

### 5. 成员移除必须在登录后无条件执行且必须成功
**决策：** 无论 OAuth 登录最终成功还是失败，只要已经进入 Team 工作空间加入阶段，就必须在登录阶段结束后执行成员移除；并且成员移除必须成功，流程才允许进入最终收口。若在多次重试后仍无法移除，则整个任务必须失败。

**原因：** 在这个链路里，成员移除不是可选清理，而是业务闭环的一部分。如果登录结束后仍残留在 Team 工作空间，会污染后续账号状态与工作空间状态，因此必须把“移除成功”视为流程成功的必要条件。

**备选方案：**
- 将清理失败视为主流程成功后的可忽略告警：不满足当前业务要求。
- 完全不重试，首次移除失败就终止：过于脆弱，不利于处理临时性失败。

### 6. 为“移除失败后的补偿路径”预留扩展口，但本次不实现
**决策：** 在 Team 成员管理 helper 与 engine 编排中预留补偿扩展口，用于未来在“移除多次失败后”切换新的 Team 会员账号执行后续邀请与移除；但本次变更只实现“重试后仍失败则整体任务失败”的主策略。

**原因：** 用户已经明确了后续可能需要补偿链路。如果现在不预留扩展点，后续会把重试、切换账号、补偿执行等逻辑硬塞进当前清理函数中，导致职责失控。

**备选方案：**
- 现在就实现 Team 会员账号切换补偿：超出本次范围，且缺少完整策略输入。
- 不预留扩展点：会提高后续补偿能力接入成本。

## 开发完成后的预期代码结构

下面给出按当前仓库组织方式推导出的**目标代码结构**。它描述的是开发完成后新增/修改代码应落在哪些目录，而不是要求一次性重构整个 ChatGPT GUI 子系统。

> 说明：由于“官网注册”起始页的页面描述和控件细节尚未最终提供，`steps/official_signup/` 目录下个别 step 文件名可以在实现时按真实页面微调，但目录分层与职责边界应保持不变。

```text
platforms/chatgpt/
├── chatgpt_registration_mode_adapter.py          # 修改：新增官网注册变体的模式路由与配置解析
├── codex_gui_registration_engine.py              # 修改：编排官网注册、工作空间加入、登录续跑、清理四阶段流程
├── team_workspace.py                             # 新增或补齐：Team 工作空间加入/移除 helper 边界
└── codex_gui/
    ├── context.py                                # 修改：补充分阶段状态、错误信息、清理结果元数据
    ├── targets/
    │   └── catalog.py                            # 修改：新增官网注册入口相关 target 定义与匹配锚点
    ├── workflows/
    │   ├── registration_workflow.py              # 复用：继续承担密码后的注册尾段
    │   ├── login_workflow.py                     # 复用：继续承担 OAuth 登录续跑
    │   └── official_signup_workflow.py           # 新增：官网注册前半段工作流
    ├── steps/
    │   ├── official_signup/                      # 新增：官网注册前半段 step 集合
    │   │   ├── __init__.py
    │   │   ├── open_official_signup_entry_step.py
    │   │   ├── navigate_official_signup_step.py
    │   │   ├── submit_official_signup_email_step.py
    │   │   └── submit_official_signup_password_step.py
    │   ├── registration/                         # 复用：OTP、资料补全、注册终态、consent
    │   └── login/                                # 复用：登录续跑与 OAuth 收敛
    └── services/
        └── email_code_service.py                 # 复用：邮箱验证码拉取与去重逻辑

tests/
├── test_chatgpt_registration_mode_adapter.py     # 修改：覆盖官网注册变体路由
├── test_codex_gui_registration_engine.py         # 修改：覆盖四阶段编排与结果语义
├── test_chatgpt_official_signup_workflow.py      # 新增：覆盖官网注册前半段工作流
└── test_chatgpt_team_workspace.py                # 新增：覆盖工作空间加入/移除 helper 边界与重试/扩展口行为
```

### 目录职责约束

- `workflows/official_signup_workflow.py` 只负责官网注册前半段编排，不承担工作空间加入与移除。
- `steps/official_signup/` 只放 GUI 页面识别、输入、点击、跳转验证相关 step，不混入 Team 管理逻辑。
- `team_workspace.py` 负责 Team 工作空间成员加入/移除的能力边界，避免把这部分逻辑写进 GUI step。
- `codex_gui_registration_engine.py` 负责跨阶段总编排与最终结果汇总，不应再次下沉为页面级识别实现。
- “是否具备 Team 会员账号从而允许启用官网注册变体”的判定放在适配层或 engine 入口层，不放在 step 内做隐式判断。
- “移除失败后的重试和未来补偿扩展口”放在 `team_workspace.py` 与 engine 编排层，不放在 workflow/step 层做业务兜底。
- 测试目录要与主代码分层对应，保证“变体路由 / 官网注册工作流 / 工作空间 helper / 引擎总编排”四部分都能单独验证。

### 建议类名、主要函数与职责细化

下面的命名遵循当前 `codex_gui` 子系统已有风格：
- 工作流使用 `XxxWorkflow`
- step 使用 `XxxStep`
- 运行期数据仍通过 `CodexGUIFlowContext` 和 `FlowStepResult` 传递
- 文件导出通过各目录下的 `__init__.py` 统一暴露

#### 1. `platforms/chatgpt/chatgpt_registration_mode_adapter.py`

- **建议新增函数：** `resolve_codex_gui_variant(extra_config) -> str`
  - 输入：`extra_config`
  - 输出：当前 GUI 子变体标识，例如 `default` / `official-signup`
  - 职责：从现有配置中解析官网注册变体，并在缺少 Team 会员账号配置时强制回退到 `default`

- **建议调整函数：** `build_chatgpt_registration_mode_adapter(...)`
  - 输入：现有适配器构建参数
  - 输出：具体 registration adapter
  - 职责：在保持默认行为不变的前提下，把官网注册变体路由给现有 GUI engine 扩展路径

#### 2. `platforms/chatgpt/codex_gui_registration_engine.py`

- **建议保留主类：** `CodexGUIRegistrationEngine`

- **建议新增成员：**
  - `self._official_signup_workflow = OfficialSignupWorkflow()`
  - 职责：与 `RegistrationWorkflow()`、`LoginWorkflow()` 保持并列关系

- **建议新增函数：** `def _resolve_gui_variant(self) -> str`
  - 输入：无（读取 `self.extra_config`）
  - 输出：GUI 变体标识
  - 职责：统一决定本次运行使用默认 GUI 注册链路还是官网注册变体，并保证“无 Team 会员账号 => 必须回退”

- **建议新增函数：** `def _run_official_signup_flow(self, ctx: CodexGUIFlowContext) -> FlowStepResult`
  - 输入：`ctx`
  - 输出：`FlowStepResult`
  - 职责：调用 `OfficialSignupWorkflow.run(...)`，只负责官网注册前半段

- **建议新增函数：** `def _enroll_team_workspace(self, ctx: CodexGUIFlowContext) -> dict[str, Any]`
  - 输入：`ctx`
  - 输出：工作空间加入结果字典，如 `{"success": bool, "workspace_id": str, ...}`
  - 职责：调用 `team_workspace.py` 中的 helper，把新账号加入目标工作空间，并把结果写回上下文/元数据

- **建议新增函数：** `def _cleanup_team_workspace_membership(self, ctx: CodexGUIFlowContext) -> dict[str, Any]`
  - 输入：`ctx`
  - 输出：清理结果字典
  - 职责：在登录阶段结束后无条件执行成员移除，驱动重试逻辑，并把 cleanup 结果显式记录下来

- **建议新增函数：** `def _finalize_after_cleanup(self, result: RegistrationResult, ctx: CodexGUIFlowContext) -> RegistrationResult`
  - 输入：`result`、`ctx`
  - 输出：最终 `RegistrationResult`
  - 职责：只有在 cleanup 成功后才允许进入最终收口；若 cleanup 失败，则把整个任务结果置为失败

- **建议调整函数：** `def _build_flow_context(...) -> CodexGUIFlowContext`
  - 新增上下文字段初始化：GUI 变体、官网注册阶段结果、工作空间加入结果、cleanup 结果

- **建议调整函数：** `def _finalize_success_result(...) -> RegistrationResult`
  - 输出中新增分阶段元数据，例如：
    - `codex_gui_variant`
    - `codex_gui_official_signup_completed`
    - `codex_gui_workspace_enrolled`
    - `codex_gui_workspace_cleanup_completed`
    - `codex_gui_cleanup_retry_count`
    - `codex_gui_cleanup_required`

#### 3. `platforms/chatgpt/team_workspace.py`

- **建议新增数据类：** `ChatGPTTeamWorkspaceResult`
  - 字段建议：`success`、`workspace_id`、`member_email`、`action`、`detail`、`payload`
  - 职责：统一承载加入/移除工作空间的结果，避免 engine 直接处理松散字典

- **建议新增函数：** `invite_chatgpt_team_member(...) -> ChatGPTTeamWorkspaceResult`
  - 输入：目标邮箱、工作空间配置、Team 账号配置、日志函数等
  - 输出：加入结果
  - 职责：封装新账号加入目标工作空间的单一动作

- **建议新增函数：** `remove_chatgpt_team_member(...) -> ChatGPTTeamWorkspaceResult`
  - 输入：目标邮箱、工作空间配置、Team 账号配置、日志函数等
  - 输出：移除结果
  - 职责：封装流程尾部的成员清理动作

- **建议新增函数：** `remove_chatgpt_team_member_with_retry(...) -> ChatGPTTeamWorkspaceResult`
  - 输入：目标邮箱、工作空间配置、Team 账号配置、最大重试次数、日志函数等
  - 输出：最终移除结果
  - 职责：把“多次重试直到成功或最终失败”的策略集中封装，避免 engine 和 step 重复实现重试逻辑

- **建议新增函数：** `build_cleanup_compensation_context(...) -> dict[str, Any]`
  - 输入：失败场景下的 Team 账号、工作空间、目标成员、失败详情
  - 输出：补偿上下文字典
  - 职责：为未来“切换新的 Team 会员账号再执行邀请与移除”的扩展策略预留统一输入，不在本次实际执行补偿

- **建议新增函数：** `ensure_team_workspace_config(extra_config: dict[str, Any]) -> None`
  - 输入：`extra_config`
  - 输出：无，异常时直接抛错
  - 职责：在进入加入/移除流程前校验关键配置是否齐全

#### 4. `platforms/chatgpt/codex_gui/workflows/official_signup_workflow.py`

- **建议新增类：** `OfficialSignupWorkflow`
- **建议主函数：** `def run(self, engine, ctx: CodexGUIFlowContext) -> FlowStepResult`
  - 输入：`engine`、`ctx`
  - 输出：最后一个 `FlowStepResult`
  - 职责：仿照 `RegistrationWorkflow` / `LoginWorkflow` 的写法，顺序执行官网注册前半段 step，并响应 `ctx.pending_step_id`

- **建议 steps 顺序：**
  1. `OpenOfficialSignupEntryStep()`
  2. `NavigateOfficialSignupStep()`
  3. `SubmitOfficialSignupEmailStep()`
  4. `SubmitOfficialSignupPasswordStep()`

#### 5. `platforms/chatgpt/codex_gui/steps/official_signup/__init__.py`

- **建议导出类：**
  - `OpenOfficialSignupEntryStep`
  - `NavigateOfficialSignupStep`
  - `SubmitOfficialSignupEmailStep`
  - `SubmitOfficialSignupPasswordStep`

- **职责：** 与现有 `steps/registration/__init__.py` 风格一致，统一导出官网注册前半段 step

#### 6. `open_official_signup_entry_step.py`

- **建议类名：** `OpenOfficialSignupEntryStep`
- **继承：** `BaseFlowStep`
- **建议 step_id：** `official_signup.open_entry`
- **建议 stage_name：** `官网注册-打开入口页`

- **建议主要函数：**
  - `precheck(self, engine, ctx) -> None`
  - `prepare(self, engine, ctx) -> None`
  - `execute(self, engine, ctx) -> FlowStepResult`
  - `verify(self, engine, ctx, result) -> None`
  - `on_error(self, engine, ctx, error) -> StepErrorDecision`

- **输入职责：** 读取官网注册起始 URL 或入口配置
- **输出职责：** 返回命中的入口页 URL / marker
- **核心职责：** 打开官网起始页并确认已经进入“官网注册入口态”

#### 7. `navigate_official_signup_step.py`

- **建议类名：** `NavigateOfficialSignupStep`
- **建议 step_id：** `official_signup.navigate_signup`
- **建议 stage_name：** `官网注册-进入注册页`

- **建议主要函数：** 与 `BaseFlowStep` 标准生命周期一致
- **输入职责：** 基于当前页识别结果，点击或导航到真正的注册表单页
- **输出职责：** 返回注册页命中结果
- **核心职责：** 解决“官网首页 ≠ 注册表单页”的过渡问题

#### 8. `submit_official_signup_email_step.py`

- **建议类名：** `SubmitOfficialSignupEmailStep`
- **建议 step_id：** `official_signup.submit_email`
- **建议 stage_name：** `官网注册-输入邮箱`

- **建议主要函数：** 与现有 `SubmitRegistrationEmailStep` 保持同样的生命周期结构
- **输入职责：** 使用 `ctx.identity.email` 作为邮箱输入值
- **输出职责：** 返回进入密码页前后的命中结果
- **核心职责：** 在官网注册前半段完成邮箱输入和下一步跳转

#### 9. `submit_official_signup_password_step.py`

- **建议类名：** `SubmitOfficialSignupPasswordStep`
- **建议 step_id：** `official_signup.submit_password`
- **建议 stage_name：** `官网注册-进入验证码页`

- **建议主要函数：** 与现有 `SubmitRegistrationPasswordStep` 保持一致
- **输入职责：** 使用 `ctx.identity.password` 作为密码输入值
- **输出职责：** 返回密码提交成功后的 `FlowStepResult`
- **核心职责：** 成为官网注册前半段和现有注册尾段之间的稳定衔接点

#### 10. `platforms/chatgpt/codex_gui/context.py`

- **建议扩展字段：**
  - `gui_variant: str = "default"`
  - `official_signup_completed: bool = False`
  - `workspace_enroll_result: dict[str, Any] = field(default_factory=dict)`
  - `workspace_cleanup_result: dict[str, Any] = field(default_factory=dict)`
  - `cleanup_required: bool = False`
  - `cleanup_retry_count: int = 0`
  - `cleanup_compensation_context: dict[str, Any] = field(default_factory=dict)`

- **职责：** 继续作为所有 workflow/step 的共享上下文，不新增第二套 context 类型

#### 11. `platforms/chatgpt/codex_gui/targets/catalog.py`

- **建议新增函数或目录项：** 为官网入口页、官网注册页、官网邮箱输入页、官网密码页补充 target 映射
- **输入职责：** 逻辑 target 名称
- **输出职责：** DOM/UIA 锚点策略
- **核心职责：** 让 `official_signup` 相关 step 仍然走既有 target 解析路径，而不是绕开 catalog 单独硬编码

### 预期调用关系

```text
chatgpt_registration_mode_adapter.py
        │
        ▼
CodexGUIRegistrationEngine.run()
        │
        ├─ _resolve_gui_variant()
        │      ├─ default -> RegistrationWorkflow.run()
        │      └─ official-signup -> OfficialSignupWorkflow.run()
        │                                 │
        │                                 └─ SubmitOfficialSignupPasswordStep
        │                                        ▼
        │                                RegistrationWorkflow.run()  # 复用密码后尾段
        │
        ├─ _enroll_team_workspace()
        │      └─ team_workspace.invite_chatgpt_team_member(...)
        │
        ├─ LoginWorkflow.run()  # 复用现有登录续跑
        │
        ├─ _cleanup_team_workspace_membership()
        │      └─ team_workspace.remove_chatgpt_team_member_with_retry(...)
        │
        └─ _finalize_after_cleanup()
```

### 输入 / 输出总原则

- **step 层输入**：优先只从 `ctx` 读取 identity、auth_url、extra_config、上一步阶段状态
- **step 层输出**：统一返回 `FlowStepResult`
- **workflow 层输入**：`engine + ctx`
- **workflow 层输出**：最后一步的 `FlowStepResult`
- **helper 层输入**：显式参数，不直接依赖 GUI step 内部状态
- **engine 层输出**：最终仍然汇总到 `RegistrationResult`
- **最终收口原则**：无论登录成功或失败，只要进入了 Team 成员加入阶段，就必须先完成移除成功，再允许给出最终任务结果

这样做的目的，是让“官网注册前半段”“工作空间加入/移除”“现有登录续跑”三部分既能复用现有结构，又不会把职责混在同一层里。

## 风险与权衡

- **[官网注册页与现有 OAuth 注册页目标不同]** → 通过新增目标目录项与起始步骤隔离官网入口，仅复用密码后的稳定步骤。
- **[Team 成员管理 helper 在当前仓库不可见]** → 实现阶段先确认现有实现来源；若不存在，则以单独 helper 封装并在任务里显式补齐测试。
- **[主流程跨多个阶段，失败面扩大]** → 为每个阶段记录独立状态与错误码，避免最终只有笼统失败。
- **[清理动作与主流程结果冲突]** → 将“移除成功”提升为最终成功的必要条件，并通过重试与扩展口减少临时失败影响。
- **[GUI 变体增加后选择器和步骤测试负担上升]** → 优先复用现有步骤与测试夹具，只为新增官网入口和成员管理边界补最小覆盖。
- **[缺少 Team 会员账号配置时误入官网注册变体]** → 在适配层与 engine 入口双重保证回退到默认 GUI 链路。

## 迁移方案

- 新变体通过新配置开关或枚举值启用，且只有在 Team 会员账号配置完整时才实际命中；否则默认回退到现有 GUI 链路，因此不需要数据迁移。
- 发布时先落地代码与测试，再通过配置显式选择新变体进行验证。
- 如发现新变体不稳定，可直接切回现有 GUI 模式，不影响默认链路。

## 待确认问题

- 当前仓库之外是否已有 `team_workspace` 实现可直接复用，还是需要在本仓库补齐？
- Team 成员加入/移除是通过已有内部 API、外部服务，还是另一个 GUI 流程完成？
- 新变体配置应作为独立 registration mode，还是作为 `codex_gui` 下的子模式字段？
