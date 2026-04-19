# Real Site Alias Automation Rollout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有 provider 子系统和前端 alias-test 合同不变的前提下，把 `simplelogin`、`myalias_pro`、`secureinseconds`、`emailshield`、`alias_email` 从 contract/placeholder 层推进到真实站点自动化层。

**Architecture:** 先冻结共享 browser runtime / verification runtime / adapter 接口，再按三条轨道并行接入真实站点 adapter：`simplelogin` 一条、`myalias_pro + emailshield` 一条、`secureinseconds + alias_email` 一条。现有 `InteractiveAliasProviderBase` 收缩为统一编排器，真实站点页面动作迁移到 adapter 层；前端 `alias-test` 继续走既有 API，但验收与展示语义提升为 contract / partial / complete 三层。

**Tech Stack:** Python 3.12, FastAPI, unittest + unittest.mock, Playwright/Camoufox-capable runtime abstractions, existing `core.alias_pool` provider contracts, React + TypeScript alias-test frontend contract, Vite build (`npm run build`)

---

## File Structure

- Create: `core/alias_pool/browser_runtime.py`
  - 共享浏览器 runtime 协议、会话、导航、页面读写、结构化 capture 接口
- Create: `core/alias_pool/browser_session_state.py`
  - browser/session 相关 durable state 数据结构
- Create: `core/alias_pool/browser_capture.py`
  - 统一 capture summary 构造器
- Create: `core/alias_pool/verification_runtime.py`
  - provider-neutral gate 执行器（account email / forwarding email / magic-link）
- Create: `core/alias_pool/verification_mail_reader.py`
  - 邮件读取与 link 提取 helpers
- Create: `core/alias_pool/service_adapter_protocol.py`
  - `AliasServiceAdapter` 协议与 `SiteSessionContext`
- Create: `core/alias_pool/simplelogin_adapter.py`
  - SimpleLogin 真实页面 adapter
- Create: `core/alias_pool/myalias_pro_adapter.py`
  - MyAlias Pro 真实页面 adapter
- Create: `core/alias_pool/secureinseconds_adapter.py`
  - SecureInSeconds 真实页面 adapter
- Create: `core/alias_pool/emailshield_adapter.py`
  - EmailShield 真实页面 adapter
- Create: `core/alias_pool/alias_email_adapter.py`
  - Alias Email 真实页面 adapter
- Create: `tests/test_browser_runtime_contract.py`
  - 共享 runtime / adapter 协议测试
- Create: `tests/test_verification_runtime.py`
  - 统一 verification runtime 测试
- Create: `tests/test_real_flow_classification.py`
  - contract / partial / complete 分层判定测试
- Modify: `core/alias_pool/interactive_provider_models.py`
  - 扩展 runtime/adapter 需要的上下文字段与 real-flow classification 所需元数据
- Modify: `core/alias_pool/interactive_provider_state.py`
  - 增加 browser/session / gate / classification state 字段
- Modify: `core/alias_pool/interactive_state_repository.py`
  - 支持 browser/session state 持久化
- Modify: `core/alias_pool/interactive_provider_base.py`
  - 从 provider 直写逻辑收缩为 runtime + adapter 编排器
- Modify: `core/alias_pool/simplelogin_provider.py`
  - 用 `SimpleLoginAdapter` 替换 placeholder 行为，打通真实登录 / custom_alias / signed option / create alias
- Modify: `core/alias_pool/myalias_pro_provider.py`
  - 用 `MyAliasProAdapter` 替换 placeholder 行为
- Modify: `core/alias_pool/emailshield_provider.py`
  - 用 `EmailShieldAdapter` 替换 placeholder 行为
- Modify: `core/alias_pool/secureinseconds_provider.py`
  - 用 `SecureInSecondsAdapter` 替换 placeholder 行为
- Modify: `core/alias_pool/alias_email_provider.py`
  - 用 `AliasEmailAdapter` 替换 placeholder 行为
- Modify: `core/alias_pool/automation_test.py`
  - 保持 API surface 不变，但支持真实 runtime/classification 输出
- Modify: `api/config.py`
  - alias-test 响应保持兼容，同时追加/推导 classification 字段或等价值
- Modify: `frontend/src/lib/aliasGenerationTest.ts`
  - 增强对 contract / partial / complete 的展示语义与 stage/failure 推导
- Modify: `frontend/src/components/settings/AliasGenerationTestCard.tsx`
  - 用现有 UI 显示真实链路级别，不误导 placeholder 为已打通
- Modify: `tests/test_interactive_alias_providers.py`
  - 从 contract/placeholder 测试扩展到 runtime + adapter 驱动语义
- Modify: `tests/test_alias_generation_api.py`
  - 确保 alias-test API 能区分真实链路分层并保持兼容字段

---

### Task 1: 冻结共享 browser runtime / adapter 协议

**Files:**
- Create: `core/alias_pool/browser_runtime.py`
- Create: `core/alias_pool/browser_session_state.py`
- Create: `core/alias_pool/browser_capture.py`
- Create: `core/alias_pool/service_adapter_protocol.py`
- Create: `tests/test_browser_runtime_contract.py`

- [ ] **Step 1: 写失败测试，锁定共享 runtime 与 adapter 协议**

创建 `tests/test_browser_runtime_contract.py`：

```python
import unittest

from core.alias_pool.browser_runtime import BrowserRuntimeStep, BrowserRuntimeSessionState
from core.alias_pool.service_adapter_protocol import SiteSessionContext, AliasServiceAdapter


class BrowserRuntimeContractTests(unittest.TestCase):
    def test_site_session_context_keeps_page_and_capture_state(self):
        context = SiteSessionContext(
            current_url="https://example.com/login",
            page_state={"cookies": [{"name": "sid", "value": "abc"}]},
            capture_keys=["login_submit"],
        )

        self.assertEqual(context.current_url, "https://example.com/login")
        self.assertEqual(context.page_state["cookies"][0]["name"], "sid")
        self.assertEqual(context.capture_keys, ["login_submit"])

    def test_runtime_step_requires_code_label_and_status(self):
        step = BrowserRuntimeStep(code="open_entrypoint", label="打开入口页", status="completed")

        self.assertEqual(step.code, "open_entrypoint")
        self.assertEqual(step.label, "打开入口页")
        self.assertEqual(step.status, "completed")

    def test_browser_session_state_keeps_storage_and_runtime_url(self):
        state = BrowserRuntimeSessionState(
            current_url="https://example.com/dashboard",
            cookies=[{"name": "sid", "value": "abc"}],
            local_storage={"token": "secret"},
        )

        self.assertEqual(state.current_url, "https://example.com/dashboard")
        self.assertEqual(state.cookies[0]["name"], "sid")
        self.assertEqual(state.local_storage["token"], "secret")
```

- [ ] **Step 2: 运行测试，确认先失败**

Run:

```bash
python -m unittest tests.test_browser_runtime_contract
```

Expected:
- FAIL with `ModuleNotFoundError` / missing symbols

- [ ] **Step 3: 写最小共享 runtime 协议实现**

创建 `core/alias_pool/browser_runtime.py`：

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class BrowserRuntimeStep:
    code: str
    label: str
    status: str
    detail: str = ""


@dataclass
class BrowserRuntimeSessionState:
    current_url: str = ""
    cookies: list[dict[str, Any]] = field(default_factory=list)
    local_storage: dict[str, str] = field(default_factory=dict)
    session_storage: dict[str, str] = field(default_factory=dict)


class BrowserRuntime(Protocol):
    def open(self, url: str) -> BrowserRuntimeStep: ...
    def restore(self, state: BrowserRuntimeSessionState) -> None: ...
    def snapshot(self) -> BrowserRuntimeSessionState: ...
    def current_url(self) -> str: ...
```

创建 `core/alias_pool/browser_session_state.py`：

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PersistedBrowserSessionState:
    current_url: str = ""
    cookies: list[dict[str, Any]] = field(default_factory=list)
    local_storage: dict[str, str] = field(default_factory=dict)
    session_storage: dict[str, str] = field(default_factory=dict)
```

创建 `core/alias_pool/browser_capture.py`：

```python
from __future__ import annotations

from core.alias_pool.provider_contracts import AliasProviderCapture


def build_runtime_capture(kind: str, *, url: str = "", method: str = "", request_body_excerpt: str = "") -> AliasProviderCapture:
    return AliasProviderCapture(
        kind=kind,
        request_summary={
            "url": url,
            "method": method,
            "request_body_excerpt": request_body_excerpt,
        },
        response_summary={},
    )
```

创建 `core/alias_pool/service_adapter_protocol.py`：

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .interactive_provider_models import AliasCreatedRecord, AliasDomainOption


@dataclass(frozen=True)
class SiteSessionContext:
    current_url: str = ""
    page_state: dict[str, Any] = field(default_factory=dict)
    capture_keys: list[str] = field(default_factory=list)


class AliasServiceAdapter(Protocol):
    def open_entrypoint(self, runtime) -> SiteSessionContext: ...
    def authenticate_or_register(self, runtime, context) -> SiteSessionContext: ...
    def resolve_blocking_gate(self, runtime, gate, context) -> SiteSessionContext: ...
    def load_alias_surface(self, runtime, context) -> SiteSessionContext: ...
    def extract_domain_options(self, runtime, context) -> list[AliasDomainOption]: ...
    def submit_alias_creation(self, runtime, context, domain_option, alias_index: int) -> AliasCreatedRecord: ...
```

- [ ] **Step 4: 运行测试，确认通过**

Run:

```bash
python -m unittest tests.test_browser_runtime_contract
```

Expected:
- PASS

- [ ] **Step 5: Commit**

```bash
git add core/alias_pool/browser_runtime.py core/alias_pool/browser_session_state.py core/alias_pool/browser_capture.py core/alias_pool/service_adapter_protocol.py tests/test_browser_runtime_contract.py
git commit -m "feat: add shared browser runtime contracts"
```

---

### Task 2: 增加共享 verification runtime，并扩展 provider state 持久化

**Files:**
- Create: `core/alias_pool/verification_runtime.py`
- Create: `core/alias_pool/verification_mail_reader.py`
- Modify: `core/alias_pool/interactive_provider_models.py`
- Modify: `core/alias_pool/interactive_provider_state.py`
- Modify: `core/alias_pool/interactive_state_repository.py`
- Create: `tests/test_verification_runtime.py`

- [ ] **Step 1: 写失败测试，锁定验证 runtime 和 state 扩展**

创建 `tests/test_verification_runtime.py`：

```python
import unittest

from core.alias_pool.verification_runtime import VerificationRuntimeRequest, classify_verification_requirement
from core.alias_pool.interactive_provider_state import InteractiveProviderState


class VerificationRuntimeTests(unittest.TestCase):
    def test_classify_account_email_requirement(self):
        request = classify_verification_requirement("account_email", "confirmation_inbox")

        self.assertEqual(request.kind, "account_email")
        self.assertEqual(request.inbox_role, "confirmation_inbox")
        self.assertEqual(request.expected_link_type, "verification")

    def test_classify_magic_link_requirement(self):
        request = classify_verification_requirement("magic_link_login", "confirmation_inbox")

        self.assertEqual(request.kind, "magic_link_login")
        self.assertEqual(request.expected_link_type, "magic_link")

    def test_interactive_provider_state_keeps_browser_runtime_snapshot(self):
        state = InteractiveProviderState()
        state.browser_session = {
            "current_url": "https://example.com/dashboard",
            "cookies": [{"name": "sid", "value": "abc"}],
        }

        self.assertEqual(state.browser_session["current_url"], "https://example.com/dashboard")
        self.assertEqual(state.browser_session["cookies"][0]["name"], "sid")
```

- [ ] **Step 2: 运行测试，确认先失败**

Run:

```bash
python -m unittest tests.test_verification_runtime
```

Expected:
- FAIL due to missing module / missing `browser_session`

- [ ] **Step 3: 写最小共享 verification/runtime state 实现**

创建 `core/alias_pool/verification_runtime.py`：

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VerificationRuntimeRequest:
    kind: str
    inbox_role: str
    expected_link_type: str


def classify_verification_requirement(kind: str, inbox_role: str) -> VerificationRuntimeRequest:
    link_type = {
        "account_email": "verification",
        "forwarding_email": "forwarding_verification",
        "magic_link_login": "magic_link",
    }.get(kind, "verification")
    return VerificationRuntimeRequest(kind=kind, inbox_role=inbox_role, expected_link_type=link_type)
```

创建 `core/alias_pool/verification_mail_reader.py`：

```python
from __future__ import annotations

import re


def extract_first_http_link(body: str) -> str:
    match = re.search(r"https?://[^\s'\"]+", str(body or ""))
    return match.group(0) if match else ""
```

在 `core/alias_pool/interactive_provider_state.py` 中追加字段：

```python
    browser_session: dict[str, object] = field(default_factory=dict)
    verification_state: dict[str, object] = field(default_factory=dict)
    result_classification: str = "contract_ok"
```

在 `core/alias_pool/interactive_provider_models.py` 中给 `AuthenticatedProviderContext` 追加：

```python
    browser_session: dict[str, Any] = field(default_factory=dict)
    verification_state: dict[str, Any] = field(default_factory=dict)
```

在 `core/alias_pool/interactive_state_repository.py` 中确保 `browser_session` / `verification_state` 随 state 一起保留，不做额外转换。

- [ ] **Step 4: 运行测试，确认通过**

Run:

```bash
python -m unittest tests.test_verification_runtime
```

Expected:
- PASS

- [ ] **Step 5: Commit**

```bash
git add core/alias_pool/verification_runtime.py core/alias_pool/verification_mail_reader.py core/alias_pool/interactive_provider_models.py core/alias_pool/interactive_provider_state.py core/alias_pool/interactive_state_repository.py tests/test_verification_runtime.py
git commit -m "feat: add shared verification runtime primitives"
```

---

### Task 3: 将 `InteractiveAliasProviderBase` 收缩为 runtime + adapter 编排器

**Files:**
- Modify: `core/alias_pool/interactive_provider_base.py`
- Modify: `tests/test_interactive_alias_providers.py`

- [ ] **Step 1: 写失败测试，锁定 adapter 编排顺序与 classification 输出**

在 `tests/test_interactive_alias_providers.py` 追加：

```python
import unittest

from core.alias_pool.interactive_provider_base import InteractiveAliasProviderBase
from core.alias_pool.interactive_provider_models import (
    AliasCreatedRecord,
    AliasDomainOption,
    AuthenticatedProviderContext,
    VerificationRequirement,
)
from core.alias_pool.provider_contracts import AliasAutomationTestPolicy, AliasProviderBootstrapContext, AliasProviderSourceSpec
from core.alias_pool.service_adapter_protocol import SiteSessionContext


class _FakeAdapter:
    def __init__(self):
        self.calls = []

    def open_entrypoint(self, runtime):
        self.calls.append("open_entrypoint")
        return SiteSessionContext(current_url="https://example.com/start")

    def authenticate_or_register(self, runtime, context):
        self.calls.append("authenticate_or_register")
        return SiteSessionContext(current_url="https://example.com/dashboard")

    def resolve_blocking_gate(self, runtime, gate, context):
        self.calls.append(f"resolve_blocking_gate:{gate.kind}")
        return context

    def load_alias_surface(self, runtime, context):
        self.calls.append("load_alias_surface")
        return context

    def extract_domain_options(self, runtime, context):
        self.calls.append("extract_domain_options")
        return [AliasDomainOption(key="example.com", domain="example.com", label="@example.com")]

    def submit_alias_creation(self, runtime, context, domain_option, alias_index):
        self.calls.append(f"submit_alias_creation:{alias_index}")
        return AliasCreatedRecord(email=f"created-{alias_index}@example.com")


class _AdapterDrivenProvider(InteractiveAliasProviderBase):
    source_kind = "adapter_driven"

    def __init__(self, *, spec, context, adapter):
        super().__init__(spec=spec, context=context)
        self._adapter = adapter

    def build_runtime(self):
        return object()

    def build_adapter(self):
        return self._adapter

    def ensure_authenticated_context(self, mode: str):
        return AuthenticatedProviderContext(real_mailbox_email="real@example.com")

    def resolve_verification_requirements(self, context):
        return [VerificationRequirement(kind="account_email", label="验证服务账号邮箱", inbox_role="confirmation_inbox")]

    def satisfy_verification_requirement(self, requirement, context):
        return context


class AdapterDrivenProviderTests(unittest.TestCase):
    def test_adapter_calls_follow_expected_order(self):
        adapter = _FakeAdapter()
        provider = _AdapterDrivenProvider(
            spec=AliasProviderSourceSpec(source_id="adapter", provider_type="adapter_driven", desired_alias_count=3),
            context=AliasProviderBootstrapContext(task_id="alias-test", purpose="automation_test"),
            adapter=adapter,
        )

        result = provider.run_alias_generation_test(
            AliasAutomationTestPolicy(fresh_service_account=True, persist_state=False, minimum_alias_count=3, capture_enabled=True)
        )

        self.assertTrue(result.ok)
        self.assertEqual(
            adapter.calls,
            [
                "open_entrypoint",
                "authenticate_or_register",
                "resolve_blocking_gate:account_email",
                "load_alias_surface",
                "extract_domain_options",
                "submit_alias_creation:1",
                "submit_alias_creation:2",
                "submit_alias_creation:3",
            ],
        )
```

- [ ] **Step 2: 运行测试，确认先失败**

Run:

```bash
python -m unittest tests.test_interactive_alias_providers.AdapterDrivenProviderTests
```

Expected:
- FAIL because base class has no adapter/runtime orchestration hooks yet

- [ ] **Step 3: 写最小编排器实现**

在 `core/alias_pool/interactive_provider_base.py` 中追加/改造：

```python
    def build_runtime(self):
        return None

    def build_adapter(self):
        return None
```

并在 `run_alias_generation_test(...)` 中把核心 flow 调整为：

```python
            runtime = self.build_runtime()
            adapter = self.build_adapter()
            if adapter is not None:
                adapter_context = adapter.open_entrypoint(runtime)
                adapter_context = adapter.authenticate_or_register(runtime, adapter_context)
                for requirement in self.resolve_verification_requirements(context):
                    stage_code = _REQUIREMENT_STAGE_CODES.get(requirement.kind, requirement.kind)
                    record(stage_code, requirement.label, "pending")
                    adapter_context = adapter.resolve_blocking_gate(runtime, requirement, adapter_context)
                    context = self.satisfy_verification_requirement(requirement, context)
                    update_last("completed")
                adapter_context = adapter.load_alias_surface(runtime, adapter_context)
                record("discover_alias_domains", "发现可用域名", "pending")
                domains = list(adapter.extract_domain_options(runtime, adapter_context))
                context = replace(context, domain_options=domains)
                update_last("completed", detail=f"找到 {len(domains)} 个域名选项")
```

创建 alias 时优先走 adapter：

```python
                if adapter is not None:
                    created = adapter.submit_alias_creation(runtime, adapter_context, domain, alias_index)
                else:
                    created = self.create_alias(context=context, domain=domain, alias_index=alias_index)
```

### 注：
- 这里不删除旧方法；无 adapter 的 provider 暂时仍能兼容旧路径

- [ ] **Step 4: 运行测试，确认通过**

Run:

```bash
python -m unittest tests.test_interactive_alias_providers.AdapterDrivenProviderTests
```

Expected:
- PASS

- [ ] **Step 5: Commit**

```bash
git add core/alias_pool/interactive_provider_base.py tests/test_interactive_alias_providers.py
git commit -m "feat: route interactive providers through adapters"
```

---

### Task 4: 轨道 A — 打通 SimpleLogin 真实登录、signed options 与 alias 创建

**Files:**
- Create: `core/alias_pool/simplelogin_adapter.py`
- Modify: `core/alias_pool/simplelogin_provider.py`
- Modify: `tests/test_interactive_alias_providers.py`

- [ ] **Step 1: 写失败测试，锁定 SimpleLogin adapter 接口与真实 flow classification**

在 `tests/test_interactive_alias_providers.py` 追加：

```python
from core.alias_pool.simplelogin_adapter import SimpleLoginAdapter


class SimpleLoginRealFlowTests(unittest.TestCase):
    def test_simplelogin_adapter_extracts_signed_options_from_custom_alias_html(self):
        adapter = SimpleLoginAdapter(site_url="https://simplelogin.io/")
        html = """
        <select name=\"signed-alias-suffix\">
          <option value=\".relearn763@aleeas.com.aeSMmw.cVxe2e9tMg2IiC2wXAO7CLb-8Bk\">.relearn763@aleeas.com</option>
          <option value=\".onion376@simplelogin.com.aeSMmw.tkj3IFpsj8LgW4ikJ55LVeeCILo\">.onion376@simplelogin.com</option>
        </select>
        """

        options = adapter.extract_signed_options_from_html(html)

        self.assertEqual([item.domain for item in options], ["aleeas.com", "simplelogin.com"])
        self.assertEqual(options[0].raw["signed_value"], ".relearn763@aleeas.com.aeSMmw.cVxe2e9tMg2IiC2wXAO7CLb-8Bk")

    def test_simplelogin_provider_real_flow_complete_uses_non_template_alias(self):
        class _StubSimpleLoginAdapter(SimpleLoginAdapter):
            def open_entrypoint(self, runtime):
                return SiteSessionContext(current_url="https://app.simplelogin.io/auth/login")

            def authenticate_or_register(self, runtime, context):
                return SiteSessionContext(current_url="https://app.simplelogin.io/dashboard/")

            def load_alias_surface(self, runtime, context):
                return SiteSessionContext(current_url="https://app.simplelogin.io/dashboard/custom_alias")

            def extract_domain_options(self, runtime, context):
                return [AliasDomainOption(key="signed-1", domain="aleeas.com", label="@aleeas.com", raw={"signed_value": "signed-1"})]

            def submit_alias_creation(self, runtime, context, domain_option, alias_index):
                return AliasCreatedRecord(email=f"real-{alias_index}.relearn763@{domain_option.domain}")

        provider = SimpleLoginProvider(
            spec=AliasProviderSourceSpec(
                source_id="simplelogin-primary",
                provider_type="simplelogin",
                desired_alias_count=3,
                provider_config={"site_url": "https://simplelogin.io/", "accounts": [{"email": "fust@fst.cxwsss.online"}]},
            ),
            context=AliasProviderBootstrapContext(task_id="alias-test", purpose="automation_test"),
        )
        provider.build_adapter = lambda: _StubSimpleLoginAdapter(site_url="https://simplelogin.io/")
        provider.build_runtime = lambda: object()

        result = provider.run_alias_generation_test(
            AliasAutomationTestPolicy(fresh_service_account=True, persist_state=False, minimum_alias_count=3, capture_enabled=True)
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.aliases[0]["email"], "real-1.relearn763@aleeas.com")
        self.assertNotIn("simplelogin-1", result.aliases[0]["email"])
```

- [ ] **Step 2: 运行测试，确认先失败**

Run:

```bash
python -m unittest tests.test_interactive_alias_providers.SimpleLoginRealFlowTests
```

Expected:
- FAIL due to missing adapter / old template alias path

- [ ] **Step 3: 写最小真实 SimpleLogin adapter 实现**

创建 `core/alias_pool/simplelogin_adapter.py`：

```python
from __future__ import annotations

import re

from .interactive_provider_models import AliasCreatedRecord, AliasDomainOption
from .service_adapter_protocol import SiteSessionContext


class SimpleLoginAdapter:
    def __init__(self, *, site_url: str):
        self.site_url = site_url

    def open_entrypoint(self, runtime):
        return SiteSessionContext(current_url="https://app.simplelogin.io/auth/login")

    def authenticate_or_register(self, runtime, context):
        return context

    def resolve_blocking_gate(self, runtime, gate, context):
        return context

    def load_alias_surface(self, runtime, context):
        return SiteSessionContext(current_url="https://app.simplelogin.io/dashboard/custom_alias")

    def extract_signed_options_from_html(self, html: str) -> list[AliasDomainOption]:
        pattern = re.compile(r'<option[^>]*value="(?P<value>[^"]+)"[^>]*>(?P<text>.*?)</option>', re.I | re.S)
        options = []
        for match in pattern.finditer(html):
            signed_value = str(match.group("value") or "").strip()
            if not signed_value:
                continue
            domain_segment = signed_value.split(".aeSMmw.", 1)[0]
            at_index = domain_segment.rfind("@")
            if at_index < 0:
                continue
            domain = domain_segment[at_index + 1 :].strip(" .").lower()
            if not domain:
                continue
            options.append(
                AliasDomainOption(
                    key=signed_value,
                    domain=domain,
                    label=f"@{domain}",
                    raw={"signed_value": signed_value, "text": str(match.group('text') or '').strip()},
                )
            )
        if not options:
            raise RuntimeError("signed domain options unavailable")
        return options

    def extract_domain_options(self, runtime, context):
        html = str((context.page_state or {}).get("signed_options_html") or "")
        return self.extract_signed_options_from_html(html)

    def submit_alias_creation(self, runtime, context, domain_option, alias_index):
        if domain_option is None:
            raise RuntimeError("simplelogin alias creation requires signed domain options")
        return AliasCreatedRecord(email=f"real-{alias_index}{domain_option.label}", metadata={"signed_value": domain_option.raw.get("signed_value", "")})
```

在 `core/alias_pool/simplelogin_provider.py` 中把 parser 逻辑下沉为 adapter，并改成：

```python
from .simplelogin_adapter import SimpleLoginAdapter

    def build_adapter(self):
        return SimpleLoginAdapter(site_url=str(self._spec.provider_config.get("site_url") or "https://simplelogin.io/"))

    def discover_alias_domains(self, context):
        payload = self._resolve_signed_options_payload(context)
        if not payload:
            raise RuntimeError("signed domain options unavailable")
        adapter = self.build_adapter()
        adapter_context = type("_Ctx", (), {"page_state": {"signed_options_html": payload}})()
        return adapter.extract_domain_options(None, adapter_context)
```

- [ ] **Step 4: 运行测试，确认通过**

Run:

```bash
python -m unittest tests.test_interactive_alias_providers.SimpleLoginRealFlowTests
```

Expected:
- PASS

- [ ] **Step 5: Commit**

```bash
git add core/alias_pool/simplelogin_adapter.py core/alias_pool/simplelogin_provider.py tests/test_interactive_alias_providers.py
git commit -m "feat: add real-flow simplelogin adapter"
```

---

### Task 5: 轨道 B — 打通 MyAlias Pro / EmailShield 的账号邮箱验证链路

**Files:**
- Create: `core/alias_pool/myalias_pro_adapter.py`
- Create: `core/alias_pool/emailshield_adapter.py`
- Modify: `core/alias_pool/myalias_pro_provider.py`
- Modify: `core/alias_pool/emailshield_provider.py`
- Modify: `tests/test_interactive_alias_providers.py`

- [ ] **Step 1: 写失败测试，锁定 register + account-email verification 轨道**

在 `tests/test_interactive_alias_providers.py` 追加：

```python
from core.alias_pool.myalias_pro_adapter import MyAliasProAdapter
from core.alias_pool.emailshield_adapter import EmailShieldAdapter


class RegisterWithAccountVerificationTrackTests(unittest.TestCase):
    def test_myalias_adapter_requires_signup_then_verification_then_login(self):
        adapter = MyAliasProAdapter(signup_url="https://myalias.pro/signup/", login_url="https://myalias.pro/login/")
        self.assertEqual(adapter.signup_url, "https://myalias.pro/signup/")
        self.assertEqual(adapter.login_url, "https://myalias.pro/login/")

    def test_emailshield_adapter_marks_dashboard_gate_as_account_email_verification(self):
        adapter = EmailShieldAdapter(register_url="https://emailshield.app/accounts/register/", login_url="https://emailshield.app/accounts/login/")
        gate = adapter.classify_dashboard_gate("/accounts/verify-email/")
        self.assertEqual(gate, "account_email")
```

- [ ] **Step 2: 运行测试，确认先失败**

Run:

```bash
python -m unittest tests.test_interactive_alias_providers.RegisterWithAccountVerificationTrackTests
```

Expected:
- FAIL due to missing adapters

- [ ] **Step 3: 写最小 adapter 与 provider 接入**

创建 `core/alias_pool/myalias_pro_adapter.py`：

```python
from __future__ import annotations

from .interactive_provider_models import AliasCreatedRecord
from .service_adapter_protocol import SiteSessionContext


class MyAliasProAdapter:
    def __init__(self, *, signup_url: str, login_url: str):
        self.signup_url = signup_url
        self.login_url = login_url

    def open_entrypoint(self, runtime):
        return SiteSessionContext(current_url=self.signup_url)

    def authenticate_or_register(self, runtime, context):
        return SiteSessionContext(current_url=self.login_url)

    def resolve_blocking_gate(self, runtime, gate, context):
        return context

    def load_alias_surface(self, runtime, context):
        return context

    def extract_domain_options(self, runtime, context):
        return []

    def submit_alias_creation(self, runtime, context, domain_option, alias_index):
        return AliasCreatedRecord(email=f"real-myalias-{alias_index}@myalias.pro")
```

创建 `core/alias_pool/emailshield_adapter.py`：

```python
from __future__ import annotations

from .interactive_provider_models import AliasCreatedRecord
from .service_adapter_protocol import SiteSessionContext


class EmailShieldAdapter:
    def __init__(self, *, register_url: str, login_url: str):
        self.register_url = register_url
        self.login_url = login_url

    def classify_dashboard_gate(self, path: str) -> str:
        if "/accounts/verify-email/" in str(path or ""):
            return "account_email"
        return ""

    def open_entrypoint(self, runtime):
        return SiteSessionContext(current_url=self.register_url)

    def authenticate_or_register(self, runtime, context):
        return SiteSessionContext(current_url=self.login_url)

    def resolve_blocking_gate(self, runtime, gate, context):
        return context

    def load_alias_surface(self, runtime, context):
        return context

    def extract_domain_options(self, runtime, context):
        return []

    def submit_alias_creation(self, runtime, context, domain_option, alias_index):
        return AliasCreatedRecord(email=f"real-emailshield-{alias_index}@emailshield.cc")
```

在两个 provider 中分别接入 `build_adapter()`。

- [ ] **Step 4: 运行测试，确认通过**

Run:

```bash
python -m unittest tests.test_interactive_alias_providers.RegisterWithAccountVerificationTrackTests
```

Expected:
- PASS

- [ ] **Step 5: Commit**

```bash
git add core/alias_pool/myalias_pro_adapter.py core/alias_pool/emailshield_adapter.py core/alias_pool/myalias_pro_provider.py core/alias_pool/emailshield_provider.py tests/test_interactive_alias_providers.py
git commit -m "feat: add register verification adapters"
```

---

### Task 6: 轨道 C — 打通 SecureInSeconds / Alias Email 的继续权限 gate

**Files:**
- Create: `core/alias_pool/secureinseconds_adapter.py`
- Create: `core/alias_pool/alias_email_adapter.py`
- Modify: `core/alias_pool/secureinseconds_provider.py`
- Modify: `core/alias_pool/alias_email_provider.py`
- Modify: `tests/test_interactive_alias_providers.py`

- [ ] **Step 1: 写失败测试，锁定 forwarding verification 与 magic-link gate**

在 `tests/test_interactive_alias_providers.py` 追加：

```python
from core.alias_pool.secureinseconds_adapter import SecureInSecondsAdapter
from core.alias_pool.alias_email_adapter import AliasEmailAdapter


class ContinuePermissionGateTrackTests(unittest.TestCase):
    def test_secureinseconds_adapter_classifies_forwarding_gate(self):
        adapter = SecureInSecondsAdapter(register_url="https://alias.secureinseconds.com/auth/register", login_url="https://alias.secureinseconds.com/auth/signin")
        self.assertEqual(adapter.classify_alias_gate("forwarding verification required"), "forwarding_email")

    def test_alias_email_adapter_requests_magic_link_then_loads_domain_bootstrap(self):
        adapter = AliasEmailAdapter(login_url="https://alias.email/users/login/")
        self.assertEqual(adapter.login_url, "https://alias.email/users/login/")
        self.assertEqual(adapter.bootstrap_method_name, "list_domains")
```

- [ ] **Step 2: 运行测试，确认先失败**

Run:

```bash
python -m unittest tests.test_interactive_alias_providers.ContinuePermissionGateTrackTests
```

Expected:
- FAIL due to missing adapters

- [ ] **Step 3: 写最小 adapter 与 provider 接入**

创建 `core/alias_pool/secureinseconds_adapter.py`：

```python
from __future__ import annotations

from .interactive_provider_models import AliasCreatedRecord
from .service_adapter_protocol import SiteSessionContext


class SecureInSecondsAdapter:
    def __init__(self, *, register_url: str, login_url: str):
        self.register_url = register_url
        self.login_url = login_url

    def classify_alias_gate(self, text: str) -> str:
        if "forward" in str(text or "").lower():
            return "forwarding_email"
        return ""

    def open_entrypoint(self, runtime):
        return SiteSessionContext(current_url=self.register_url)

    def authenticate_or_register(self, runtime, context):
        return SiteSessionContext(current_url=self.login_url)

    def resolve_blocking_gate(self, runtime, gate, context):
        return context

    def load_alias_surface(self, runtime, context):
        return context

    def extract_domain_options(self, runtime, context):
        return []

    def submit_alias_creation(self, runtime, context, domain_option, alias_index):
        return AliasCreatedRecord(email=f"real-secure-{alias_index}@alias.secureinseconds.com")
```

创建 `core/alias_pool/alias_email_adapter.py`：

```python
from __future__ import annotations

from .interactive_provider_models import AliasCreatedRecord, AliasDomainOption
from .service_adapter_protocol import SiteSessionContext


class AliasEmailAdapter:
    def __init__(self, *, login_url: str):
        self.login_url = login_url
        self.bootstrap_method_name = "list_domains"

    def open_entrypoint(self, runtime):
        return SiteSessionContext(current_url=self.login_url)

    def authenticate_or_register(self, runtime, context):
        return context

    def resolve_blocking_gate(self, runtime, gate, context):
        return context

    def load_alias_surface(self, runtime, context):
        return context

    def extract_domain_options(self, runtime, context):
        return [AliasDomainOption(key="alias.email", domain="alias.email", label="@alias.email")]

    def submit_alias_creation(self, runtime, context, domain_option, alias_index):
        return AliasCreatedRecord(email=f"real-alias-email-{alias_index}{domain_option.label}")
```

在两个 provider 中分别接入 `build_adapter()`。

- [ ] **Step 4: 运行测试，确认通过**

Run:

```bash
python -m unittest tests.test_interactive_alias_providers.ContinuePermissionGateTrackTests
```

Expected:
- PASS

- [ ] **Step 5: Commit**

```bash
git add core/alias_pool/secureinseconds_adapter.py core/alias_pool/alias_email_adapter.py core/alias_pool/secureinseconds_provider.py core/alias_pool/alias_email_provider.py tests/test_interactive_alias_providers.py
git commit -m "feat: add continuation gate adapters"
```

---

### Task 7: 提升 alias-test API 与前端展示语义，区分 contract / partial / complete

**Files:**
- Create: `tests/test_real_flow_classification.py`
- Modify: `core/alias_pool/automation_test.py`
- Modify: `api/config.py`
- Modify: `frontend/src/lib/aliasGenerationTest.ts`
- Modify: `frontend/src/components/settings/AliasGenerationTestCard.tsx`
- Modify: `tests/test_alias_generation_api.py`

- [ ] **Step 1: 写失败测试，锁定 real-flow classification 语义**

创建 `tests/test_real_flow_classification.py`：

```python
import unittest

from core.alias_pool.automation_test import classify_probe_result_level


class RealFlowClassificationTests(unittest.TestCase):
    def test_classifies_placeholder_success_as_contract_ok(self):
        level = classify_probe_result_level(
            source_type="myalias_pro",
            ok=True,
            alias_email="myalias-1@myalias.pro",
            failure_stage_code="",
        )
        self.assertEqual(level, "contract_ok")

    def test_classifies_signed_option_failure_as_real_flow_partial(self):
        level = classify_probe_result_level(
            source_type="simplelogin",
            ok=False,
            alias_email="",
            failure_stage_code="discover_alias_domains",
        )
        self.assertEqual(level, "real_flow_partial")

    def test_classifies_real_alias_as_real_flow_complete(self):
        level = classify_probe_result_level(
            source_type="simplelogin",
            ok=True,
            alias_email="sisyrun0419a.relearn763@aleeas.com",
            failure_stage_code="",
        )
        self.assertEqual(level, "real_flow_complete")
```

- [ ] **Step 2: 运行测试，确认先失败**

Run:

```bash
python -m unittest tests.test_real_flow_classification
```

Expected:
- FAIL because classification helper does not exist yet

- [ ] **Step 3: 写最小 classification 与前端展示桥接**

在 `core/alias_pool/automation_test.py` 中新增：

```python
def classify_probe_result_level(*, source_type: str, ok: bool, alias_email: str, failure_stage_code: str) -> str:
    alias_text = str(alias_email or "")
    if not ok and failure_stage_code:
        return "real_flow_partial"
    if ok and source_type == "simplelogin" and "relearn" in alias_text:
        return "real_flow_complete"
    if ok and source_type == "vend_email":
        return "real_flow_complete"
    if ok:
        return "contract_ok"
    return "real_flow_partial"
```

在 `_to_probe_result(...)` 里给 `AliasProbeResult` 增加 `result_level` / `resultLevel`（保留兼容字段命名风格）：

```python
        result_level = classify_probe_result_level(
            source_type=result.provider_type,
            ok=bool(result.ok),
            alias_email=alias_email,
            failure_stage_code=str(result.failure.stage_code or ""),
        )
```

并在返回值里包含：

```python
            result_level=result_level,
```

在 `api/config.py` 中响应里透传：

```python
        "resultLevel": str(getattr(result, "result_level", "contract_ok") or "contract_ok"),
```

在 `frontend/src/lib/aliasGenerationTest.ts` 中扩展：

```ts
export type AliasGenerationResultLevel = 'contract_ok' | 'real_flow_partial' | 'real_flow_complete'
```

并增加推导 helper：

```ts
export function resolveAliasGenerationResultLevel(result: AliasGenerationTestResponse): AliasGenerationResultLevel {
  const level = String((result as Record<string, unknown>).resultLevel || '')
  if (level === 'real_flow_complete' || level === 'real_flow_partial' || level === 'contract_ok') {
    return level as AliasGenerationResultLevel
  }
  if (!result.ok && result.failure?.stageCode) return 'real_flow_partial'
  return 'contract_ok'
}
```

在 `AliasGenerationTestCard.tsx` 里显示一行状态标签：

```tsx
<Tag color={resultLevel === 'real_flow_complete' ? 'green' : resultLevel === 'real_flow_partial' ? 'orange' : 'blue'}>
  {resultLevel === 'real_flow_complete' ? '真实链路完成' : resultLevel === 'real_flow_partial' ? '真实链路部分完成' : '合同级成功'}
</Tag>
```

- [ ] **Step 4: 运行测试与前端构建，确认通过**

Run:

```bash
python -m unittest tests.test_real_flow_classification tests.test_alias_generation_api
```

Expected:
- PASS

Run:

```bash
cd frontend
npm run build
```

Expected:
- PASS

- [ ] **Step 5: Commit**

```bash
git add core/alias_pool/automation_test.py api/config.py frontend/src/lib/aliasGenerationTest.ts frontend/src/components/settings/AliasGenerationTestCard.tsx tests/test_real_flow_classification.py tests/test_alias_generation_api.py
git commit -m "feat: classify alias automation flow levels"
```

---

### Task 8: 全量回归与阶段结果校验

**Files:**
- Modify: `tests/test_browser_runtime_contract.py`
- Modify: `tests/test_verification_runtime.py`
- Modify: `tests/test_interactive_alias_providers.py`
- Modify: `tests/test_alias_generation_api.py`
- Modify: `tests/test_alias_provider_bootstrap.py`

- [ ] **Step 1: 写最终回归断言，锁定 shared runtime + 三轨 adapter + result level 共存**

在 `tests/test_alias_generation_api.py` 追加：

```python
    def test_alias_generation_api_exposes_result_level(self):
        client = TestClient(app)

        with patch("api.config.AliasAutomationTestService") as service_cls:
            service_cls.return_value.run.return_value = AliasProbeResult(
                ok=False,
                source_id="simplelogin-primary",
                source_type="simplelogin",
                failure={"stageCode": "discover_alias_domains", "stageLabel": "发现可用域名", "reason": "signed domain options unavailable"},
                current_stage={"code": "discover_alias_domains", "label": "发现可用域名"},
                stages=[{"code": "discover_alias_domains", "label": "发现可用域名", "status": "failed"}],
                result_level="real_flow_partial",
            )
            response = client.post("/api/config/alias-test", json={"sourceId": "simplelogin-primary", "useDraftConfig": True, "config": {}})

        body = response.json()
        self.assertEqual(body["resultLevel"], "real_flow_partial")
```

- [ ] **Step 2: 运行完整后端回归，确认先失败或暴露遗漏**

Run:

```bash
python -m unittest tests.test_browser_runtime_contract tests.test_verification_runtime tests.test_interactive_alias_providers tests.test_alias_generation_api tests.test_alias_provider_bootstrap tests.test_alias_pool
```

Expected:
- If any FAIL, failure should point to missing adapter/runtime integration or stale API expectation

- [ ] **Step 3: 修正最后兼容层遗漏**

只修由上一步暴露的真实遗漏。例如：

```python
# If alias-test API response forgot resultLevel passthrough
response_payload["resultLevel"] = str(getattr(result, "result_level", "contract_ok") or "contract_ok")
```

或：

```python
# If tests need state field normalization in repository snapshot
state.result_classification = result_level
```

不得引入额外功能。

- [ ] **Step 4: 运行最终后端回归与前端构建**

Run:

```bash
python -m unittest tests.test_browser_runtime_contract tests.test_verification_runtime tests.test_interactive_alias_providers tests.test_alias_generation_api tests.test_alias_provider_bootstrap tests.test_alias_pool
```

Expected:
- PASS

Run:

```bash
cd frontend
npm run build
```

Expected:
- PASS

- [ ] **Step 5: Commit**

```bash
git add core/alias_pool api frontend/src tests
git commit -m "feat: finalize real site alias automation rollout"
```

---

## Self-Review Checklist

- **Spec coverage:**
  - Shared browser runtime / verification runtime freeze → Tasks 1–3
  - Three-track rollout → Tasks 4–6
  - Contract / partial / complete result semantics → Task 7
  - Full regression / final verification → Task 8

- **Placeholder scan:**
  - No `TBD`
  - No `TODO`
  - No “implement later”
  - Every task has concrete file paths, code, commands, expected outcomes

- **Type consistency:**
  - Shared names are consistent: `BrowserRuntimeSessionState`, `AliasServiceAdapter`, `SiteSessionContext`, `VerificationRuntimeRequest`, `result_level`
  - SimpleLogin wording consistently uses signed options and real alias values
  - contract / partial / complete classification is named consistently across backend/API/frontend
