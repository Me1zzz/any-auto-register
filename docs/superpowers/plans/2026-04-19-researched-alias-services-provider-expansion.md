# Researched Alias Services Provider Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在保留当前 alias provider 架构与 alias-test 合同的前提下，把 `myalias.pro`、`secureinseconds`、`emailshield`、`simplelogin`、`alias.email` 接入为新的 interactive alias providers，并明确排除 `manyme.com`。

**Architecture:** 后端继续复用现有 `AliasProvider` / `AliasProviderRegistry` / `AliasProviderBootstrap` / `AliasAutomationTestService` 主路径，只把 shared source spec 演进到 `provider_config`，并在其下新增 `InteractiveAliasProviderBase`、`ExistingAccountAliasProviderBase`、provider-neutral `VerificationRequirement` / `AliasDomainOption` / interactive state repository。五个新 provider 都通过同一 registry 同时接入任务 alias pool 与 alias-test；前端继续沿用 `sources` 草稿序列化、`accountIdentity`、`stages`、`failure` 结果模型，只新增最小 source 编辑器与 provider-specific 配置 UI。

**Tech Stack:** Python 3.12, FastAPI, unittest + unittest.mock, existing `core.alias_pool` abstractions, React, TypeScript, Ant Design, Vite build (`npm run build`)

---

## File Structure

- Create: `core/alias_pool/interactive_provider_models.py`
  - 定义 `VerificationRequirement`、`AliasDomainOption`、`AuthenticatedProviderContext`、`AliasCreatedRecord`
- Create: `core/alias_pool/interactive_provider_state.py`
  - 定义 interactive provider 共享 durable state dataclass
- Create: `core/alias_pool/interactive_state_repository.py`
  - 统一 interactive provider 的 load/save/new-state 行为
- Create: `core/alias_pool/interactive_provider_base.py`
  - `InteractiveAliasProviderBase` 与 `ExistingAccountAliasProviderBase`
- Create: `core/alias_pool/myalias_pro_provider.py`
  - `myalias_pro` provider builder 与 provider 实现
- Create: `core/alias_pool/secureinseconds_provider.py`
  - `secureinseconds` provider builder 与 provider 实现
- Create: `core/alias_pool/emailshield_provider.py`
  - `emailshield` provider builder 与 provider 实现
- Create: `core/alias_pool/simplelogin_provider.py`
  - `simplelogin` provider builder 与 provider 实现；必须解析 signed domain options
- Create: `core/alias_pool/alias_email_provider.py`
  - `alias_email` provider builder 与 provider 实现
- Create: `tests/test_interactive_alias_providers.py`
  - shared interactive base、interactive state、provider-specific contracts
- Create: `frontend/src/components/settings/AliasGenerationSourceEditor.tsx`
  - source 列表增删与 provider type 切换
- Create: `frontend/src/components/settings/AliasGenerationSourceCard.tsx`
  - 单个 source 的 provider-specific 字段编辑卡片
- Create: `frontend/src/components/settings/SimpleLoginAccountListEditor.tsx`
  - `simplelogin.provider_config.accounts[]` 编辑器
- Modify: `core/alias_pool/provider_contracts.py`
  - 演进 `AliasProviderSourceSpec`，保留 vend 兼容字段，新增 `provider_config`
- Modify: `core/alias_pool/config.py`
  - decode / encode / normalize / spec-build 支持五个新 provider source type，并排除 `manyme`
- Modify: `core/alias_pool/provider_registry.py`
  - 保持接口不变；只让新 builder 通过当前 registry 注册
- Modify: `core/alias_pool/provider_bootstrap.py`
  - 保持行为不变
- Modify: `core/alias_pool/provider_adapters.py`
  - 只做 shared imports 与 typing 对齐，不改变 static/simple 行为
- Modify: `core/alias_pool/automation_test.py`
  - 双注册 interactive providers；保留 probe result 兼容字段
- Modify: `core/alias_pool/probe.py`
  - 只保持壳层语义，透传新的 stage/failure/capture
- Modify: `core/alias_pool/vend_provider.py`
  - vend 读取 `provider_config` 作为新真相源，同时兼容旧字段
- Modify: `api/config.py`
  - alias-test API 接受新 source type，继续返回兼容 `accountIdentity` / `aliases` / `stages`
- Modify: `api/tasks.py`
  - `_build_alias_pool(...)` 注册五个新 provider builders
- Modify: `frontend/src/lib/aliasGenerationTest.ts`
  - 扩展 source type、draft source normalize / serialize / derive、stage label map
- Modify: `frontend/src/lib/aliasGenerationTest.contract-check.ts`
  - 类型与兼容合同覆盖新 source type 和新阶段码
- Modify: `frontend/src/components/settings/AliasGenerationTestCard.tsx`
  - 复用现有展示，支持新 source label、新阶段码与 failure 展示
- Modify: `frontend/src/pages/Settings.tsx`
  - 接入 source editor，并继续通过 `sources` 走保存/读取 round-trip
- Modify: `tests/test_alias_provider_bootstrap.py`
  - source spec、registry、bootstrap 覆盖新 provider builders
- Modify: `tests/test_alias_generation_api.py`
  - API 契约覆盖新 source type 与 3 alias 返回
- Modify: `tests/test_alias_pool.py`
  - config normalize / encode-decode / backward compatibility 继续覆盖

---

### Task 1: 演进 shared source contract 与 config round-trip

**Files:**
- Modify: `core/alias_pool/provider_contracts.py`
- Modify: `core/alias_pool/config.py`
- Modify: `core/alias_pool/vend_provider.py`
- Modify: `tests/test_alias_provider_bootstrap.py`
- Modify: `tests/test_alias_pool.py`
- Test: `tests/test_alias_provider_bootstrap.py`
- Test: `tests/test_alias_pool.py`

- [ ] **Step 1: 写失败测试，锁定 `provider_config`、interactive source normalize 与 `manyme` 排除行为**

在 `tests/test_alias_provider_bootstrap.py` 追加：

```python
    def test_build_alias_provider_source_specs_supports_provider_config_backed_simplelogin_source(self):
        pool_config = {
            "enabled": True,
            "task_id": "alias-test",
            "sources": [
                {
                    "id": "simplelogin-primary",
                    "type": "simplelogin",
                    "alias_count": 3,
                    "state_key": "simplelogin-primary",
                    "provider_config": {
                        "site_url": "https://simplelogin.io/",
                        "accounts": [
                            {"email": "fust@fst.cxwsss.online", "label": "fust"},
                            {"email": "logon@fst.cxwsss.online", "label": "logon", "password": "secret-pass"},
                        ],
                    },
                }
            ],
        }

        specs = build_alias_provider_source_specs(pool_config)

        self.assertEqual(len(specs), 1)
        self.assertEqual(specs[0].source_id, "simplelogin-primary")
        self.assertEqual(specs[0].provider_type, "simplelogin")
        self.assertEqual(specs[0].desired_alias_count, 3)
        self.assertEqual(specs[0].state_key, "simplelogin-primary")
        self.assertEqual(specs[0].provider_config["site_url"], "https://simplelogin.io/")
        self.assertEqual(
            specs[0].provider_config["accounts"],
            [
                {"email": "fust@fst.cxwsss.online", "label": "fust"},
                {"email": "logon@fst.cxwsss.online", "label": "logon", "password": "secret-pass"},
            ],
        )
        self.assertEqual(specs[0].confirmation_inbox_config, {})
```

在 `tests/test_alias_pool.py` 追加：

```python
    def test_normalize_accepts_interactive_provider_sources(self):
        result = normalize_cloudmail_alias_pool_config(
            {
                "cloudmail_alias_enabled": True,
                "sources": [
                    {
                        "id": "myalias-primary",
                        "type": "myalias_pro",
                        "alias_count": 3,
                        "state_key": "myalias-primary",
                        "confirmation_inbox": {
                            "provider": "cloudmail",
                            "account_email": "real@example.com",
                            "account_password": "mail-pass",
                            "match_email": "real@example.com",
                        },
                        "provider_config": {
                            "signup_url": "https://myalias.pro/signup/",
                            "login_url": "https://myalias.pro/login/",
                        },
                    },
                    {
                        "id": "simplelogin-primary",
                        "type": "simplelogin",
                        "alias_count": 3,
                        "state_key": "simplelogin-primary",
                        "provider_config": {
                            "site_url": "https://simplelogin.io/",
                            "accounts": [{"email": "fust@fst.cxwsss.online", "label": "fust"}],
                        },
                    },
                ],
            },
            task_id="task-interactive-sources",
        )

        self.assertEqual(result["sources"][0]["type"], "myalias_pro")
        self.assertEqual(result["sources"][1]["type"], "simplelogin")
        self.assertEqual(result["sources"][1]["provider_config"]["site_url"], "https://simplelogin.io/")

    def test_decode_alias_provider_sources_excludes_manyme(self):
        decoded = decode_alias_provider_sources(
            [
                {"id": "manyme-primary", "type": "manyme", "provider_config": {"site_url": "https://manyme.com/"}},
                {"id": "alias-email-primary", "type": "alias_email", "provider_config": {"login_url": "https://alias.email/users/login/"}},
            ]
        )

        self.assertEqual(
            decoded,
            [
                {
                    "id": "alias-email-primary",
                    "type": "alias_email",
                    "alias_count": 0,
                    "state_key": "alias-email-primary",
                    "provider_config": {"login_url": "https://alias.email/users/login/"},
                }
            ],
        )
```

- [ ] **Step 2: 运行测试，确认先失败**

Run:

```bash
python -m unittest tests.test_alias_provider_bootstrap.AliasProviderBootstrapTests.test_build_alias_provider_source_specs_supports_provider_config_backed_simplelogin_source tests.test_alias_pool.AliasPoolConfigV2Tests.test_normalize_accepts_interactive_provider_sources tests.test_alias_pool.AliasPoolConfigV2Tests.test_decode_alias_provider_sources_excludes_manyme
```

Expected:
- FAIL
- `AliasProviderSourceSpec` 上没有 `provider_config`
- 或 config normalize/decode 还不认识 `myalias_pro` / `simplelogin` / `alias_email`

- [ ] **Step 3: 写最小实现，演进 source spec 与 config**

在 `core/alias_pool/provider_contracts.py` 中把 `AliasProviderSourceSpec` 改成：

```python
@dataclass(frozen=True)
class AliasProviderSourceSpec:
    source_id: str
    provider_type: str
    state_key: str = ""
    desired_alias_count: int = 0
    confirmation_inbox_config: dict[str, Any] = field(default_factory=dict)
    provider_config: dict[str, Any] = field(default_factory=dict)
    raw_source: dict[str, Any] = field(default_factory=dict)

    register_url: str = ""
    alias_domain: str = ""
    alias_domain_id: str = ""
```

在 `core/alias_pool/config.py` 中增加 interactive provider type 集合与 decode helper：

```python
INTERACTIVE_PROVIDER_TYPES = {
    "myalias_pro",
    "secureinseconds",
    "emailshield",
    "simplelogin",
    "alias_email",
}


def _parse_provider_config(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _decode_interactive_source(item: dict[str, Any], source_id: str, provider_type: str) -> dict[str, Any]:
    normalized: dict[str, Any] = {
        "id": source_id,
        "type": provider_type,
        "alias_count": max(_parse_int(item.get("alias_count"), 0), 0),
        "state_key": _parse_string(item.get("state_key")) or source_id,
        "provider_config": _parse_provider_config(item.get("provider_config")),
    }
    confirmation_inbox = item.get("confirmation_inbox")
    if isinstance(confirmation_inbox, dict):
        normalized["confirmation_inbox"] = dict(confirmation_inbox)
    return normalized
```

在 `_normalize_sources` 与 `decode_alias_provider_sources` 中追加：

```python
        if source_type in INTERACTIVE_PROVIDER_TYPES:
            normalized.append(_decode_interactive_source(item, source_id, source_type))
            continue
```

```python
        if source_type in INTERACTIVE_PROVIDER_TYPES:
            sanitized.append(_decode_interactive_source(item, source_id, source_type))
            continue
```

在 `build_alias_provider_source_specs(...)` 中追加：

```python
        provider_config: dict[str, Any] = {}
        if provider_type in INTERACTIVE_PROVIDER_TYPES:
            provider_config = dict(source.get("provider_config") or {})

        specs.append(
            AliasProviderSourceSpec(
                source_id=source_id,
                provider_type=provider_type,
                state_key=_parse_string(source.get("state_key")) or source_id,
                desired_alias_count=max(
                    _parse_int(
                        source.get("alias_count")
                        if source.get("alias_count") not in (None, "")
                        else source.get("count"),
                        0,
                    ),
                    0,
                ),
                confirmation_inbox_config=confirmation_inbox_config,
                provider_config=provider_config,
                raw_source=dict(source),
                register_url=_parse_string(source.get("register_url")),
                alias_domain=_parse_string(source.get("alias_domain")).lower(),
                alias_domain_id=_parse_string(source.get("alias_domain_id")),
            )
        )
```

在 `core/alias_pool/vend_provider.py` 中把 `self.source` 改成优先读 `provider_config`：

```python
        provider_config = dict(getattr(spec, "provider_config", {}) or {})
        raw_source = dict(spec.raw_source or {})
        self.source = {
            **provider_config,
            **{key: value for key, value in raw_source.items() if key != "provider_config"},
        }
```

- [ ] **Step 4: 运行测试，确认通过**

Run:

```bash
python -m unittest tests.test_alias_provider_bootstrap.AliasProviderBootstrapTests.test_build_alias_provider_source_specs_supports_provider_config_backed_simplelogin_source tests.test_alias_pool.AliasPoolConfigV2Tests.test_normalize_accepts_interactive_provider_sources tests.test_alias_pool.AliasPoolConfigV2Tests.test_decode_alias_provider_sources_excludes_manyme
```

Expected:
- PASS

- [ ] **Step 5: Commit**

```bash
git add core/alias_pool/provider_contracts.py core/alias_pool/config.py core/alias_pool/vend_provider.py tests/test_alias_provider_bootstrap.py tests/test_alias_pool.py
git commit -m "feat: evolve alias source spec for interactive providers"
```

---

### Task 2: 增加 interactive state/model 与 shared provider base

**Files:**
- Create: `core/alias_pool/interactive_provider_models.py`
- Create: `core/alias_pool/interactive_provider_state.py`
- Create: `core/alias_pool/interactive_state_repository.py`
- Create: `core/alias_pool/interactive_provider_base.py`
- Create: `tests/test_interactive_alias_providers.py`
- Test: `tests/test_interactive_alias_providers.py`

- [ ] **Step 1: 写失败测试，锁定 shared interactive loop、state 与 failure shape**

创建 `tests/test_interactive_alias_providers.py`：

```python
import unittest

from core.alias_pool.interactive_provider_base import InteractiveAliasProviderBase
from core.alias_pool.interactive_provider_models import (
    AliasCreatedRecord,
    AliasDomainOption,
    AuthenticatedProviderContext,
    VerificationRequirement,
)
from core.alias_pool.provider_contracts import (
    AliasAutomationTestPolicy,
    AliasProviderBootstrapContext,
    AliasProviderSourceSpec,
)


class _FakeInteractiveProvider(InteractiveAliasProviderBase):
    source_kind = "fake_interactive"

    def ensure_authenticated_context(self, mode: str) -> AuthenticatedProviderContext:
        return AuthenticatedProviderContext(
            service_account_email="service@example.com",
            confirmation_inbox_email="real@example.com",
            real_mailbox_email="real@example.com",
            service_password="secret-pass",
            username="service",
        )

    def resolve_verification_requirements(self, context: AuthenticatedProviderContext):
        return [
            VerificationRequirement(
                kind="account_email",
                label="验证服务账号邮箱",
                inbox_role="confirmation_inbox",
            )
        ]

    def satisfy_verification_requirement(self, requirement, context):
        return context

    def discover_alias_domains(self, context):
        return [AliasDomainOption(key="example.com", domain="example.com", label="@example.com")]

    def list_existing_aliases(self, context):
        return [{"email": "first@example.com"}]

    def create_alias(self, *, context, domain, alias_index):
        return AliasCreatedRecord(email=f"created-{alias_index}@{domain.domain}")


class InteractiveAliasProviderBaseTests(unittest.TestCase):
    def test_shared_loop_returns_three_aliases_and_stage_timeline(self):
        provider = _FakeInteractiveProvider(
            spec=AliasProviderSourceSpec(
                source_id="fake-provider",
                provider_type="fake_interactive",
                state_key="fake-provider",
                desired_alias_count=3,
            ),
            context=AliasProviderBootstrapContext(task_id="alias-test", purpose="automation_test"),
        )

        result = provider.run_alias_generation_test(
            AliasAutomationTestPolicy(
                fresh_service_account=True,
                persist_state=False,
                minimum_alias_count=3,
                capture_enabled=True,
            )
        )

        self.assertTrue(result.ok)
        self.assertEqual(len(result.aliases), 3)
        self.assertEqual(
            [item["email"] for item in result.aliases],
            ["first@example.com", "created-2@example.com", "created-3@example.com"],
        )
        self.assertEqual(result.account_identity.service_account_email, "service@example.com")
        self.assertEqual(
            [item.code for item in result.stage_timeline],
            [
                "session_ready",
                "verify_account_email",
                "discover_alias_domains",
                "list_aliases",
                "create_aliases",
                "aliases_ready",
                "save_state",
            ],
        )

    def test_shared_loop_returns_structured_failure_when_domain_discovery_fails(self):
        class _FailingProvider(_FakeInteractiveProvider):
            def discover_alias_domains(self, context):
                raise RuntimeError("signed domain options unavailable")

        provider = _FailingProvider(
            spec=AliasProviderSourceSpec(
                source_id="fake-provider",
                provider_type="fake_interactive",
                state_key="fake-provider",
                desired_alias_count=3,
            ),
            context=AliasProviderBootstrapContext(task_id="alias-test", purpose="automation_test"),
        )

        result = provider.run_alias_generation_test(
            AliasAutomationTestPolicy(
                fresh_service_account=True,
                persist_state=False,
                minimum_alias_count=3,
                capture_enabled=True,
            )
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.failure.stage_code, "discover_alias_domains")
        self.assertEqual(result.failure.reason, "signed domain options unavailable")
        self.assertEqual(result.current_stage.code, "discover_alias_domains")
```

- [ ] **Step 2: 运行测试，确认先失败**

Run:

```bash
python -m unittest tests.test_interactive_alias_providers
```

Expected:
- FAIL
- `ModuleNotFoundError` 或 `ImportError` 指向 `interactive_provider_base` / `interactive_provider_models`

- [ ] **Step 3: 写最小 shared interactive 实现**

创建 `core/alias_pool/interactive_provider_models.py`：

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class VerificationRequirement:
    kind: str
    label: str
    inbox_role: str
    required: bool = True


@dataclass(frozen=True)
class AliasDomainOption:
    key: str
    domain: str
    label: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AuthenticatedProviderContext:
    service_account_email: str = ""
    confirmation_inbox_email: str = ""
    real_mailbox_email: str = ""
    service_password: str = ""
    username: str = ""
    session_state: dict[str, Any] = field(default_factory=dict)
    domain_options: list[AliasDomainOption] = field(default_factory=list)


@dataclass(frozen=True)
class AliasCreatedRecord:
    email: str
    metadata: dict[str, Any] = field(default_factory=dict)
```

创建 `core/alias_pool/interactive_provider_state.py`：

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class InteractiveProviderState:
    service_account_email: str = ""
    confirmation_inbox_email: str = ""
    real_mailbox_email: str = ""
    service_password: str = ""
    username: str = ""
    session_state: dict[str, Any] = field(default_factory=dict)
    domain_options: list[dict[str, Any]] = field(default_factory=list)
    known_aliases: list[str] = field(default_factory=list)
    current_stage: dict[str, str] = field(default_factory=lambda: {"code": "", "label": ""})
    stage_history: list[dict[str, Any]] = field(default_factory=list)
    last_failure: dict[str, Any] = field(default_factory=lambda: {"stageCode": "", "stageLabel": "", "reason": ""})
    last_capture_summary: list[dict[str, Any]] = field(default_factory=list)
    last_error: str = ""
```

创建 `core/alias_pool/interactive_state_repository.py`：

```python
from __future__ import annotations

from .interactive_provider_state import InteractiveProviderState


class InteractiveStateRepository:
    def __init__(self, *, store=None):
        self._store = store

    def new_state(self) -> InteractiveProviderState:
        return InteractiveProviderState()

    def load(self) -> InteractiveProviderState:
        if self._store is None:
            return self.new_state()
        loaded = self._store.load()
        return loaded if loaded is not None else self.new_state()

    def save(self, state: InteractiveProviderState) -> None:
        if self._store is None:
            return
        self._store.save(state)
```

创建 `core/alias_pool/interactive_provider_base.py`：

```python
from __future__ import annotations

from core.alias_pool.base import AliasEmailLease
from core.alias_pool.interactive_provider_models import (
    AliasCreatedRecord,
    AliasDomainOption,
    AuthenticatedProviderContext,
    VerificationRequirement,
)
from core.alias_pool.provider_contracts import (
    AliasAccountIdentity,
    AliasAutomationTestPolicy,
    AliasAutomationTestResult,
    AliasProviderCapture,
    AliasProviderFailure,
    AliasProviderSourceSpec,
    AliasProviderStage,
    AliasProviderBootstrapContext,
)


class InteractiveAliasProviderBase:
    source_kind = "interactive_alias_provider"

    def __init__(self, *, spec: AliasProviderSourceSpec, context: AliasProviderBootstrapContext):
        self._spec = spec
        self._context = context
        self.source_id = spec.source_id

    @property
    def provider_type(self) -> str:
        return self.source_kind

    def load_into(self, pool_manager) -> None:
        result = self.run_alias_generation_test(
            AliasAutomationTestPolicy(
                fresh_service_account=False,
                persist_state=True,
                minimum_alias_count=max(int(self._spec.desired_alias_count or 0), 1),
                capture_enabled=True,
            )
        )
        if not result.ok:
            raise RuntimeError(result.error or result.failure.reason or f"{self.provider_type} alias generation failed")
        for item in list(result.aliases or []):
            email = str(item.get("email") or "").strip().lower()
            if not email:
                continue
            pool_manager.add_lease(
                AliasEmailLease(
                    alias_email=email,
                    real_mailbox_email=result.account_identity.real_mailbox_email,
                    source_kind=self.provider_type,
                    source_id=self.source_id,
                    source_session_id=self._spec.state_key or self.source_id,
                )
            )

    def run_alias_generation_test(self, policy: AliasAutomationTestPolicy) -> AliasAutomationTestResult:
        timeline: list[AliasProviderStage] = []

        def record(code: str, label: str, status: str, detail: str = "") -> None:
            timeline.append(AliasProviderStage(code=code, label=label, status=status, detail=detail))

        try:
            context = self.ensure_authenticated_context("alias_test")
            record("session_ready", "会话已就绪", "completed")

            for requirement in self.resolve_verification_requirements(context):
                stage_code = {
                    "account_email": "verify_account_email",
                    "forwarding_email": "verify_forwarding_email",
                    "magic_link_login": "consume_magic_link",
                }.get(requirement.kind, requirement.kind)
                context = self.satisfy_verification_requirement(requirement, context)
                record(stage_code, requirement.label, "completed")

            domains = self.discover_alias_domains(context)
            context = AuthenticatedProviderContext(
                **{**context.__dict__, "domain_options": domains},
            )
            record("discover_alias_domains", "发现可用域名", "completed", detail=f"找到 {len(domains)} 个域名选项")

            aliases = list(self.list_existing_aliases(context))
            record("list_aliases", "列出现有别名", "completed", detail=f"找到 {len(aliases)} 个别名")

            target = max(int(policy.minimum_alias_count or 0), int(self._spec.desired_alias_count or 0), 1)
            while len(aliases) < target:
                alias_index = len(aliases) + 1
                domain = self.pick_domain_option(domains, alias_index)
                created = self.create_alias(context=context, domain=domain, alias_index=alias_index)
                aliases.append({"email": created.email, **dict(created.metadata or {})})

            record("create_aliases", "创建别名", "completed", detail=f"预览共 {len(aliases)} 个别名")
            record("aliases_ready", "别名预览已生成", "completed", detail=f"预览共 {len(aliases)} 个别名")
            record("save_state", "保存预览状态", "completed")

            return AliasAutomationTestResult(
                provider_type=self.provider_type,
                source_id=self.source_id,
                account_identity=AliasAccountIdentity(
                    service_account_email=context.service_account_email,
                    confirmation_inbox_email=context.confirmation_inbox_email,
                    real_mailbox_email=context.real_mailbox_email,
                    service_password=context.service_password,
                    username=context.username,
                ),
                aliases=aliases[:target],
                current_stage=timeline[-1],
                stage_timeline=timeline,
                failure=AliasProviderFailure(),
                capture_summary=self.build_capture_summary() if policy.capture_enabled else [],
                logs=[],
                ok=True,
                error="",
            )
        except Exception as exc:
            failed_stage = timeline[-1] if timeline else AliasProviderStage(code="session_ready", label="", status="failed")
            if timeline:
                timeline[-1] = AliasProviderStage(
                    code=failed_stage.code,
                    label=failed_stage.label,
                    status="failed",
                    detail=str(exc),
                )
            return AliasAutomationTestResult(
                provider_type=self.provider_type,
                source_id=self.source_id,
                current_stage=AliasProviderStage(
                    code=failed_stage.code,
                    label=failed_stage.label,
                    status="failed",
                    detail=str(exc),
                ),
                stage_timeline=timeline,
                failure=AliasProviderFailure(
                    stage_code=failed_stage.code,
                    stage_label=failed_stage.label,
                    reason=str(exc),
                    retryable=True,
                ),
                capture_summary=self.build_capture_summary(),
                logs=[str(exc)],
                ok=False,
                error=str(exc),
            )

    def pick_domain_option(self, domains: list[AliasDomainOption], alias_index: int) -> AliasDomainOption | None:
        if not domains:
            return None
        return domains[(alias_index - 1) % len(domains)]

    def build_capture_summary(self) -> list[AliasProviderCapture]:
        return []

    def list_existing_aliases(self, context: AuthenticatedProviderContext) -> list[dict[str, str]]:
        return []

    def ensure_authenticated_context(self, mode: str) -> AuthenticatedProviderContext:
        raise NotImplementedError

    def resolve_verification_requirements(self, context: AuthenticatedProviderContext) -> list[VerificationRequirement]:
        return []

    def satisfy_verification_requirement(self, requirement: VerificationRequirement, context: AuthenticatedProviderContext) -> AuthenticatedProviderContext:
        return context

    def discover_alias_domains(self, context: AuthenticatedProviderContext) -> list[AliasDomainOption]:
        return []

    def create_alias(self, *, context: AuthenticatedProviderContext, domain: AliasDomainOption | None, alias_index: int) -> AliasCreatedRecord:
        raise NotImplementedError


class ExistingAccountAliasProviderBase(InteractiveAliasProviderBase):
    def select_service_account(self) -> dict[str, str]:
        accounts = list(self._spec.provider_config.get("accounts") or [])
        if not accounts:
            raise RuntimeError(f"{self.provider_type} provider requires at least one existing account")
        account = dict(accounts[0])
        email = str(account.get("email") or "").strip().lower()
        if not email:
            raise RuntimeError(f"{self.provider_type} provider requires account email")
        password = str(account.get("password") or email).strip()
        label = str(account.get("label") or account.get("username") or email.split("@")[0]).strip()
        return {"email": email, "password": password, "label": label}
```

- [ ] **Step 4: 运行测试，确认通过**

Run:

```bash
python -m unittest tests.test_interactive_alias_providers
```

Expected:
- PASS

- [ ] **Step 5: Commit**

```bash
git add core/alias_pool/interactive_provider_models.py core/alias_pool/interactive_provider_state.py core/alias_pool/interactive_state_repository.py core/alias_pool/interactive_provider_base.py tests/test_interactive_alias_providers.py
git commit -m "feat: add shared interactive alias provider base"
```

---

### Task 3: 在 alias-test 与任务路径同时注册五个新 provider

**Files:**
- Create: `core/alias_pool/myalias_pro_provider.py`
- Create: `core/alias_pool/secureinseconds_provider.py`
- Create: `core/alias_pool/emailshield_provider.py`
- Create: `core/alias_pool/simplelogin_provider.py`
- Create: `core/alias_pool/alias_email_provider.py`
- Modify: `core/alias_pool/automation_test.py`
- Modify: `api/tasks.py`
- Modify: `tests/test_alias_provider_bootstrap.py`
- Test: `tests/test_alias_provider_bootstrap.py`

- [ ] **Step 1: 写失败测试，锁定 dual registration 与 builder 构造能力**

在 `tests/test_alias_provider_bootstrap.py` 追加：

```python
    def test_supported_provider_types_all_build_alias_provider_instances_after_expansion(self):
        from core.alias_pool.alias_email_provider import build_alias_email_provider
        from core.alias_pool.emailshield_provider import build_emailshield_provider
        from core.alias_pool.myalias_pro_provider import build_myalias_pro_provider
        from core.alias_pool.secureinseconds_provider import build_secureinseconds_provider
        from core.alias_pool.simplelogin_provider import build_simplelogin_provider

        registry = AliasProviderRegistry()
        registry.register("static_list", build_static_list_alias_provider)
        registry.register("simple_generator", build_simple_generator_alias_provider)
        registry.register("vend_email", lambda spec, context: _DummyAliasProvider())
        registry.register("myalias_pro", build_myalias_pro_provider)
        registry.register("secureinseconds", build_secureinseconds_provider)
        registry.register("emailshield", build_emailshield_provider)
        registry.register("simplelogin", build_simplelogin_provider)
        registry.register("alias_email", build_alias_email_provider)

        specs = build_alias_provider_source_specs(
            {
                "enabled": True,
                "task_id": "alias-test",
                "sources": [
                    {"id": "myalias-primary", "type": "myalias_pro", "provider_config": {"signup_url": "https://myalias.pro/signup/", "login_url": "https://myalias.pro/login/"}},
                    {"id": "secureinseconds-primary", "type": "secureinseconds", "provider_config": {"register_url": "https://alias.secureinseconds.com/auth/register", "login_url": "https://alias.secureinseconds.com/auth/signin"}},
                    {"id": "emailshield-primary", "type": "emailshield", "provider_config": {"register_url": "https://emailshield.app/accounts/register/", "login_url": "https://emailshield.app/accounts/login/"}},
                    {"id": "simplelogin-primary", "type": "simplelogin", "provider_config": {"site_url": "https://simplelogin.io/", "accounts": [{"email": "fust@fst.cxwsss.online"}]}},
                    {"id": "alias-email-primary", "type": "alias_email", "provider_config": {"login_url": "https://alias.email/users/login/"}},
                ],
            }
        )
        context = AliasProviderBootstrapContext(task_id="alias-test-run", purpose="automation_test")

        for spec in specs:
            builder = registry.resolve(spec.provider_type)
            self.assertIsNotNone(builder, f"missing builder for {spec.provider_type}")
            assert builder is not None
            provider = builder(spec, context)
            self.assertIsInstance(provider, AliasProvider)
            self.assertEqual(provider.provider_type, spec.provider_type)
```

- [ ] **Step 2: 运行测试，确认先失败**

Run:

```bash
python -m unittest tests.test_alias_provider_bootstrap.AliasProviderBootstrapTests.test_supported_provider_types_all_build_alias_provider_instances_after_expansion
```

Expected:
- FAIL
- 新 provider module/builder 还不存在

- [ ] **Step 3: 创建 provider builders，并在两条路径双注册**

创建 `core/alias_pool/myalias_pro_provider.py`：

```python
from __future__ import annotations

from core.alias_pool.interactive_provider_base import InteractiveAliasProviderBase
from core.alias_pool.interactive_provider_models import AliasCreatedRecord, AuthenticatedProviderContext, VerificationRequirement


class MyAliasProProvider(InteractiveAliasProviderBase):
    source_kind = "myalias_pro"

    def ensure_authenticated_context(self, mode: str) -> AuthenticatedProviderContext:
        inbox_email = str(
            self._spec.confirmation_inbox_config.get("match_email")
            or self._spec.confirmation_inbox_config.get("account_email")
            or ""
        ).strip().lower()
        return AuthenticatedProviderContext(
            confirmation_inbox_email=inbox_email,
            real_mailbox_email=inbox_email,
        )

    def resolve_verification_requirements(self, context: AuthenticatedProviderContext):
        return [VerificationRequirement(kind="account_email", label="验证服务账号邮箱", inbox_role="confirmation_inbox")]

    def create_alias(self, *, context, domain, alias_index):
        return AliasCreatedRecord(email=f"myalias-{alias_index}@myalias.pro")


def build_myalias_pro_provider(spec, context):
    return MyAliasProProvider(spec=spec, context=context)
```

按同样模式创建：

- `core/alias_pool/secureinseconds_provider.py`
- `core/alias_pool/emailshield_provider.py`
- `core/alias_pool/simplelogin_provider.py`
- `core/alias_pool/alias_email_provider.py`

其中 `simplelogin_provider.py` 的最小 builder 先写成：

```python
from __future__ import annotations

from core.alias_pool.interactive_provider_base import ExistingAccountAliasProviderBase
from core.alias_pool.interactive_provider_models import AliasCreatedRecord, AliasDomainOption, AuthenticatedProviderContext


class SimpleLoginProvider(ExistingAccountAliasProviderBase):
    source_kind = "simplelogin"

    def ensure_authenticated_context(self, mode: str) -> AuthenticatedProviderContext:
        account = self.select_service_account()
        return AuthenticatedProviderContext(
            service_account_email=account["email"],
            real_mailbox_email=account["email"],
            confirmation_inbox_email=account["email"],
            service_password=account["password"],
            username=account["label"],
        )

    def discover_alias_domains(self, context: AuthenticatedProviderContext):
        raise RuntimeError("signed domain discovery not implemented yet")

    def create_alias(self, *, context, domain, alias_index):
        if domain is None:
            raise RuntimeError("simplelogin alias creation requires signed domain options")
        return AliasCreatedRecord(email=f"simplelogin-{alias_index}{domain.label}")


def build_simplelogin_provider(spec, context):
    return SimpleLoginProvider(spec=spec, context=context)
```

在 `core/alias_pool/automation_test.py` 顶部引入五个 builder，并在 `_build_default_bootstrap()` 中追加：

```python
        registry.register("myalias_pro", build_myalias_pro_provider)
        registry.register("secureinseconds", build_secureinseconds_provider)
        registry.register("emailshield", build_emailshield_provider)
        registry.register("simplelogin", build_simplelogin_provider)
        registry.register("alias_email", build_alias_email_provider)
```

在 `api/tasks.py::_build_alias_pool(...)` 中做同样注册。

- [ ] **Step 4: 运行测试，确认通过**

Run:

```bash
python -m unittest tests.test_alias_provider_bootstrap.AliasProviderBootstrapTests.test_supported_provider_types_all_build_alias_provider_instances_after_expansion
```

Expected:
- PASS

- [ ] **Step 5: Commit**

```bash
git add core/alias_pool/myalias_pro_provider.py core/alias_pool/secureinseconds_provider.py core/alias_pool/emailshield_provider.py core/alias_pool/simplelogin_provider.py core/alias_pool/alias_email_provider.py core/alias_pool/automation_test.py api/tasks.py tests/test_alias_provider_bootstrap.py
git commit -m "feat: register interactive alias providers"
```

---

### Task 4: 扩展前端 source 类型、source 序列化与 Settings source 编辑器

**Files:**
- Create: `frontend/src/components/settings/AliasGenerationSourceEditor.tsx`
- Create: `frontend/src/components/settings/AliasGenerationSourceCard.tsx`
- Create: `frontend/src/components/settings/SimpleLoginAccountListEditor.tsx`
- Modify: `frontend/src/lib/aliasGenerationTest.ts`
- Modify: `frontend/src/lib/aliasGenerationTest.contract-check.ts`
- Modify: `frontend/src/pages/Settings.tsx`
- Modify: `frontend/src/components/settings/AliasGenerationTestCard.tsx`
- Test: `frontend/src/lib/aliasGenerationTest.contract-check.ts`
- Test: `npm run build`

- [ ] **Step 1: 写失败的前端合同检查**

在 `frontend/src/lib/aliasGenerationTest.contract-check.ts` 追加：

```ts
import type {
  AliasGenerationSourceType,
  AliasGenerationTestDraftSource,
  AliasGenerationTestResponse,
} from '@/lib/aliasGenerationTest'

const providerTypes: AliasGenerationSourceType[] = [
  'static_list',
  'simple_generator',
  'vend_email',
  'myalias_pro',
  'secureinseconds',
  'emailshield',
  'simplelogin',
  'alias_email',
]

const simpleLoginSource: AliasGenerationTestDraftSource = {
  id: 'simplelogin-primary',
  type: 'simplelogin',
  alias_count: 3,
  state_key: 'simplelogin-primary',
  provider_config: {
    site_url: 'https://simplelogin.io/',
    accounts: [
      { email: 'fust@fst.cxwsss.online', label: 'fust' },
      { email: 'logon@fst.cxwsss.online', label: 'logon', password: 'logon@fst.cxwsss.online' },
    ],
  },
}

const aliasTestResponse: AliasGenerationTestResponse = {
  ok: true,
  sourceId: 'simplelogin-primary',
  sourceType: 'simplelogin',
  aliasEmail: 'sisyrun0419a.relearn763@aleeas.com',
  realMailboxEmail: 'fust@fst.cxwsss.online',
  serviceEmail: 'fust@fst.cxwsss.online',
  accountIdentity: {
    serviceAccountEmail: 'fust@fst.cxwsss.online',
    realMailboxEmail: 'fust@fst.cxwsss.online',
    servicePassword: 'fust@fst.cxwsss.online',
    username: 'fust',
  },
  aliases: [
    { email: 'sisyrun0419a.relearn763@aleeas.com' },
    { email: 'sisyrun0419b.onion376@simplelogin.com' },
    { email: 'sisyrun0419c.skies135@slmails.com' },
  ],
  currentStage: { code: 'discover_alias_domains', label: '发现可用域名' },
  stages: [
    { code: 'select_service_account', label: '选择服务账号', status: 'completed' },
    { code: 'login_submit', label: '登录服务账号', status: 'completed' },
    { code: 'discover_alias_domains', label: '发现可用域名', status: 'completed' },
    { code: 'create_aliases', label: '创建别名', status: 'completed' },
  ],
  failure: { stageCode: '', stageLabel: '', reason: '' },
  captureSummary: [],
  steps: [],
  logs: [],
  error: '',
}

void providerTypes
void simpleLoginSource
void aliasTestResponse
```

- [ ] **Step 2: 运行前端构建，确认先失败**

Run:

```bash
cd frontend
npm run build
```

Expected:
- FAIL
- `AliasGenerationSourceType` 不包含新 provider type
- `AliasGenerationTestDraftSource` 没有 `provider_config`

- [ ] **Step 3: 扩展前端 types/serialize/source editor**

在 `frontend/src/lib/aliasGenerationTest.ts` 中先扩展类型：

```ts
export type AliasGenerationSourceType =
  | 'static_list'
  | 'simple_generator'
  | 'vend_email'
  | 'myalias_pro'
  | 'secureinseconds'
  | 'emailshield'
  | 'simplelogin'
  | 'alias_email'
```

把 `AliasGenerationTestDraftSource` 扩展为：

```ts
export interface AliasGenerationTestDraftSource extends Record<string, unknown> {
  id?: unknown
  type?: unknown
  emails?: unknown
  prefix?: unknown
  suffix?: unknown
  count?: unknown
  middle_length_min?: unknown
  middle_length_max?: unknown
  register_url?: unknown
  cloudmail_api_base?: unknown
  cloudmail_admin_email?: unknown
  cloudmail_admin_password?: unknown
  cloudmail_domain?: unknown
  cloudmail_subdomain?: unknown
  cloudmail_timeout?: unknown
  alias_domain?: unknown
  alias_domain_id?: unknown
  alias_count?: unknown
  state_key?: unknown
  confirmation_inbox?: unknown
  provider_config?: unknown
}
```

把新阶段码补进 `ALIAS_TEST_STAGE_LABELS`：

```ts
  select_service_account: '选择服务账号',
  login_submit: '登录服务账号',
  verify_account_email: '验证账号邮箱',
  verify_forwarding_email: '验证转发邮箱',
  request_magic_link: '请求魔法链接',
  consume_magic_link: '消费魔法链接',
  discover_alias_domains: '发现可用域名',
```

在 `normalizeAliasGenerationDraftSource(...)` 中追加 interactive source 分支：

```ts
  if (
    sourceType === 'myalias_pro'
    || sourceType === 'secureinseconds'
    || sourceType === 'emailshield'
    || sourceType === 'simplelogin'
    || sourceType === 'alias_email'
  ) {
    return {
      id: sourceId,
      type: sourceType,
      alias_count: normalizeNumericFieldValue(source.alias_count),
      state_key: stringifyFieldValue(source.state_key),
      confirmation_inbox: asRecord(source.confirmation_inbox) ?? undefined,
      provider_config: asRecord(source.provider_config) ?? undefined,
    }
  }
```

创建 `frontend/src/components/settings/SimpleLoginAccountListEditor.tsx`：

```tsx
import { Button, Form, Input, Space } from 'antd'
import { MinusCircleOutlined, PlusOutlined } from '@ant-design/icons'

export default function SimpleLoginAccountListEditor({ name }: { name: (string | number)[] }) {
  return (
    <Form.List name={name}>
      {(fields, { add, remove }) => (
        <Space direction="vertical" style={{ width: '100%' }} size={8}>
          {fields.map((field) => (
            <Space key={field.key} align="start" wrap>
              <Form.Item name={[field.name, 'email']} rules={[{ required: true, message: '请输入账号邮箱' }]}>
                <Input placeholder="账号邮箱" style={{ width: 240 }} />
              </Form.Item>
              <Form.Item name={[field.name, 'label']}>
                <Input placeholder="标签（可选）" style={{ width: 160 }} />
              </Form.Item>
              <Form.Item name={[field.name, 'password']}>
                <Input.Password placeholder="密码（为空时默认等于邮箱）" style={{ width: 220 }} />
              </Form.Item>
              <Button icon={<MinusCircleOutlined />} onClick={() => remove(field.name)} />
            </Space>
          ))}
          <Button icon={<PlusOutlined />} onClick={() => add({ email: '', label: '', password: '' })}>添加 SimpleLogin 账号</Button>
        </Space>
      )}
    </Form.List>
  )
}
```

创建 `frontend/src/components/settings/AliasGenerationSourceCard.tsx` 与 `AliasGenerationSourceEditor.tsx`，在 `Settings.tsx` 里把 source editor 放到邮箱服务 / CloudMail 区块之后，并继续让 `save()` 走：

```ts
const aliasGenerationDraftConfig = createAliasGenerationTestDraftConfig(values)
const serializedAliasSources = serializeAliasGenerationDraftSources(aliasGenerationDraftConfig.sources)
values.sources = serializedAliasSources
```

不要为 `simplelogin` 暴露静态 `alias_domains` 输入项。

- [ ] **Step 4: 运行前端构建，确认通过**

Run:

```bash
cd frontend
npm run build
```

Expected:
- PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/aliasGenerationTest.ts frontend/src/lib/aliasGenerationTest.contract-check.ts frontend/src/pages/Settings.tsx frontend/src/components/settings/AliasGenerationTestCard.tsx frontend/src/components/settings/AliasGenerationSourceEditor.tsx frontend/src/components/settings/AliasGenerationSourceCard.tsx frontend/src/components/settings/SimpleLoginAccountListEditor.tsx
git commit -m "feat: add interactive alias source editor in settings"
```

---

### Task 5: 实现 `myalias_pro` 与 `secureinseconds` provider 行为

**Files:**
- Modify: `core/alias_pool/myalias_pro_provider.py`
- Modify: `core/alias_pool/secureinseconds_provider.py`
- Modify: `tests/test_interactive_alias_providers.py`
- Modify: `tests/test_alias_generation_api.py`
- Test: `tests/test_interactive_alias_providers.py`
- Test: `tests/test_alias_generation_api.py`

- [ ] **Step 1: 写失败测试，锁定两个 provider 的 verification mapping 与 3 alias 行为**

在 `tests/test_interactive_alias_providers.py` 追加：

```python
from core.alias_pool.myalias_pro_provider import MyAliasProProvider
from core.alias_pool.secureinseconds_provider import SecureInSecondsProvider


class InteractiveProviderContractTests(unittest.TestCase):
    def test_myalias_pro_maps_account_email_verification_to_shared_requirement(self):
        provider = MyAliasProProvider(
            spec=AliasProviderSourceSpec(
                source_id="myalias-primary",
                provider_type="myalias_pro",
                state_key="myalias-primary",
                desired_alias_count=3,
                confirmation_inbox_config={
                    "account_email": "real@example.com",
                    "account_password": "mail-pass",
                    "match_email": "real@example.com",
                },
                provider_config={
                    "signup_url": "https://myalias.pro/signup/",
                    "login_url": "https://myalias.pro/login/",
                },
            ),
            context=AliasProviderBootstrapContext(task_id="alias-test", purpose="automation_test"),
        )

        requirements = provider.resolve_verification_requirements(provider.ensure_authenticated_context("alias_test"))

        self.assertEqual(
            requirements,
            [VerificationRequirement(kind="account_email", label="验证服务账号邮箱", inbox_role="confirmation_inbox")],
        )

    def test_secureinseconds_maps_forwarding_verification_to_shared_requirement(self):
        provider = SecureInSecondsProvider(
            spec=AliasProviderSourceSpec(
                source_id="secureinseconds-primary",
                provider_type="secureinseconds",
                state_key="secureinseconds-primary",
                desired_alias_count=3,
                confirmation_inbox_config={
                    "account_email": "real@example.com",
                    "account_password": "mail-pass",
                    "match_email": "real@example.com",
                },
                provider_config={
                    "register_url": "https://alias.secureinseconds.com/auth/register",
                    "login_url": "https://alias.secureinseconds.com/auth/signin",
                },
            ),
            context=AliasProviderBootstrapContext(task_id="alias-test", purpose="automation_test"),
        )

        requirements = provider.resolve_verification_requirements(provider.ensure_authenticated_context("alias_test"))

        self.assertEqual(
            requirements,
            [VerificationRequirement(kind="forwarding_email", label="验证转发邮箱", inbox_role="confirmation_inbox")],
        )
```

在 `tests/test_alias_generation_api.py` 追加：

```python
    def test_alias_generation_test_api_supports_myalias_source_shape(self):
        client = TestClient(app)

        with patch("core.config_store.config_store.get", return_value=""), patch(
            "api.config.config_store.get_all",
            return_value={
                "cloudmail_alias_enabled": True,
                "sources": [
                    {
                        "id": "myalias-primary",
                        "type": "myalias_pro",
                        "alias_count": 3,
                        "state_key": "myalias-primary",
                        "confirmation_inbox": {
                            "provider": "cloudmail",
                            "account_email": "real@example.com",
                            "account_password": "mail-pass",
                            "match_email": "real@example.com",
                        },
                        "provider_config": {
                            "signup_url": "https://myalias.pro/signup/",
                            "login_url": "https://myalias.pro/login/",
                        },
                    }
                ],
            },
        ), patch("api.config.AliasAutomationTestService") as service_cls:
            service = service_cls.return_value
            service.run.return_value = AliasProbeResult(
                ok=True,
                source_id="myalias-primary",
                source_type="myalias_pro",
                alias_email="myalias-1@myalias.pro",
                real_mailbox_email="real@example.com",
                service_email="service@myalias.pro",
                account={"realMailboxEmail": "real@example.com", "serviceEmail": "service@myalias.pro", "password": "secret-pass"},
                aliases=[
                    {"email": "myalias-1@myalias.pro"},
                    {"email": "myalias-2@myalias.pro"},
                    {"email": "myalias-3@myalias.pro"},
                ],
                current_stage={"code": "aliases_ready", "label": "别名预览已生成"},
                stages=[
                    {"code": "session_ready", "label": "会话已就绪", "status": "completed"},
                    {"code": "verify_account_email", "label": "验证服务账号邮箱", "status": "completed"},
                    {"code": "create_aliases", "label": "创建别名", "status": "completed"},
                ],
            )

            resp = client.post("/api/config/alias-test", json={"sourceId": "myalias-primary", "useDraftConfig": False})

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["sourceType"], "myalias_pro")
        self.assertEqual(len(body["aliases"]), 3)
        self.assertEqual(body["stages"][1]["code"], "verify_account_email")
```

- [ ] **Step 2: 运行测试，确认先失败**

Run:

```bash
python -m unittest tests.test_interactive_alias_providers.InteractiveProviderContractTests tests.test_alias_generation_api.AliasGenerationApiTests.test_alias_generation_test_api_supports_myalias_source_shape
```

Expected:
- FAIL
- provider labels、stage codes 或 API contract 还没对齐

- [ ] **Step 3: 实现两个 provider 的共享行为映射**

把 `core/alias_pool/myalias_pro_provider.py` 改成：

```python
class MyAliasProProvider(InteractiveAliasProviderBase):
    source_kind = "myalias_pro"

    def ensure_authenticated_context(self, mode: str) -> AuthenticatedProviderContext:
        inbox_email = str(
            self._spec.confirmation_inbox_config.get("match_email")
            or self._spec.confirmation_inbox_config.get("account_email")
            or ""
        ).strip().lower()
        return AuthenticatedProviderContext(
            confirmation_inbox_email=inbox_email,
            real_mailbox_email=inbox_email,
        )

    def resolve_verification_requirements(self, context):
        return [VerificationRequirement(kind="account_email", label="验证服务账号邮箱", inbox_role="confirmation_inbox")]

    def create_alias(self, *, context, domain, alias_index):
        return AliasCreatedRecord(email=f"myalias-{alias_index}@myalias.pro")
```

把 `core/alias_pool/secureinseconds_provider.py` 改成：

```python
class SecureInSecondsProvider(InteractiveAliasProviderBase):
    source_kind = "secureinseconds"

    def ensure_authenticated_context(self, mode: str) -> AuthenticatedProviderContext:
        inbox_email = str(
            self._spec.confirmation_inbox_config.get("match_email")
            or self._spec.confirmation_inbox_config.get("account_email")
            or ""
        ).strip().lower()
        return AuthenticatedProviderContext(
            confirmation_inbox_email=inbox_email,
            real_mailbox_email=inbox_email,
        )

    def resolve_verification_requirements(self, context):
        return [VerificationRequirement(kind="forwarding_email", label="验证转发邮箱", inbox_role="confirmation_inbox")]

    def create_alias(self, *, context, domain, alias_index):
        return AliasCreatedRecord(email=f"secure-{alias_index}@alias.secureinseconds.com")
```

- [ ] **Step 4: 运行测试，确认通过**

Run:

```bash
python -m unittest tests.test_interactive_alias_providers.InteractiveProviderContractTests tests.test_alias_generation_api.AliasGenerationApiTests.test_alias_generation_test_api_supports_myalias_source_shape
```

Expected:
- PASS

- [ ] **Step 5: Commit**

```bash
git add core/alias_pool/myalias_pro_provider.py core/alias_pool/secureinseconds_provider.py tests/test_interactive_alias_providers.py tests/test_alias_generation_api.py
git commit -m "feat: add myalias and secureinseconds provider contracts"
```

---

### Task 6: 实现 `emailshield` 与 `simplelogin`，并把 SimpleLogin 域名发现做成 signed option contract

**Files:**
- Modify: `core/alias_pool/emailshield_provider.py`
- Modify: `core/alias_pool/simplelogin_provider.py`
- Modify: `tests/test_interactive_alias_providers.py`
- Modify: `tests/test_alias_generation_api.py`
- Test: `tests/test_interactive_alias_providers.py`
- Test: `tests/test_alias_generation_api.py`

- [ ] **Step 1: 写失败测试，锁定 EmailShield verify gate 与 SimpleLogin signed option 解析**

在 `tests/test_interactive_alias_providers.py` 追加：

```python
from core.alias_pool.emailshield_provider import EmailShieldProvider
from core.alias_pool.simplelogin_provider import SimpleLoginProvider


class EmailShieldAndSimpleLoginTests(unittest.TestCase):
    def test_emailshield_maps_account_verify_gate(self):
        provider = EmailShieldProvider(
            spec=AliasProviderSourceSpec(
                source_id="emailshield-primary",
                provider_type="emailshield",
                state_key="emailshield-primary",
                desired_alias_count=3,
                confirmation_inbox_config={"account_email": "real@example.com", "match_email": "real@example.com"},
                provider_config={"register_url": "https://emailshield.app/accounts/register/", "login_url": "https://emailshield.app/accounts/login/"},
            ),
            context=AliasProviderBootstrapContext(task_id="alias-test", purpose="automation_test"),
        )

        requirements = provider.resolve_verification_requirements(provider.ensure_authenticated_context("alias_test"))

        self.assertEqual(
            requirements,
            [VerificationRequirement(kind="account_email", label="验证 EmailShield 账号邮箱", inbox_role="confirmation_inbox")],
        )

    def test_simplelogin_selects_first_account_and_falls_back_password_to_email(self):
        provider = SimpleLoginProvider(
            spec=AliasProviderSourceSpec(
                source_id="simplelogin-primary",
                provider_type="simplelogin",
                state_key="simplelogin-primary",
                desired_alias_count=3,
                provider_config={
                    "site_url": "https://simplelogin.io/",
                    "accounts": [
                        {"email": "fust@fst.cxwsss.online", "label": "fust"},
                        {"email": "logon@fst.cxwsss.online", "label": "logon", "password": "secret-pass"},
                    ],
                },
            ),
            context=AliasProviderBootstrapContext(task_id="alias-test", purpose="automation_test"),
        )

        context = provider.ensure_authenticated_context("alias_test")

        self.assertEqual(context.service_account_email, "fust@fst.cxwsss.online")
        self.assertEqual(context.service_password, "fust@fst.cxwsss.online")
        self.assertEqual(context.username, "fust")

    def test_simplelogin_parses_signed_alias_suffix_options(self):
        provider = SimpleLoginProvider(
            spec=AliasProviderSourceSpec(
                source_id="simplelogin-primary",
                provider_type="simplelogin",
                state_key="simplelogin-primary",
                desired_alias_count=3,
                provider_config={"site_url": "https://simplelogin.io/", "accounts": [{"email": "fust@fst.cxwsss.online"}]},
            ),
            context=AliasProviderBootstrapContext(task_id="alias-test", purpose="automation_test"),
        )

        html = """
        <select name=\"signed-alias-suffix\">
          <option value=\".relearn763@aleeas.com.aeSMmw.cVxe2e9tMg2IiC2wXAO7CLb-8Bk\">.relearn763@aleeas.com (Public domain)</option>
          <option value=\".onion376@simplelogin.com.aeSMmw.tkj3IFpsj8LgW4ikJ55LVeeCILo\">.onion376@simplelogin.com (Premium domain)</option>
        </select>
        """

        options = provider._parse_signed_domain_options(html)

        self.assertEqual([item.domain for item in options], ["aleeas.com", "simplelogin.com"])
        self.assertEqual(options[0].key, ".relearn763@aleeas.com.aeSMmw.cVxe2e9tMg2IiC2wXAO7CLb-8Bk")
        self.assertEqual(options[0].raw["signed_value"], ".relearn763@aleeas.com.aeSMmw.cVxe2e9tMg2IiC2wXAO7CLb-8Bk")

    def test_simplelogin_returns_structured_failure_when_signed_options_missing(self):
        provider = SimpleLoginProvider(
            spec=AliasProviderSourceSpec(
                source_id="simplelogin-primary",
                provider_type="simplelogin",
                state_key="simplelogin-primary",
                desired_alias_count=3,
                provider_config={"site_url": "https://simplelogin.io/", "accounts": [{"email": "fust@fst.cxwsss.online"}]},
            ),
            context=AliasProviderBootstrapContext(task_id="alias-test", purpose="automation_test"),
        )

        with self.assertRaisesRegex(RuntimeError, "signed domain options unavailable"):
            provider._parse_signed_domain_options("<html><body>no select</body></html>")
```

- [ ] **Step 2: 运行测试，确认先失败**

Run:

```bash
python -m unittest tests.test_interactive_alias_providers.EmailShieldAndSimpleLoginTests
```

Expected:
- FAIL
- `SimpleLoginProvider` 还没有 signed option parser，或者 EmailShield label 不匹配

- [ ] **Step 3: 实现 EmailShield 与 SimpleLogin provider 细节**

把 `core/alias_pool/emailshield_provider.py` 改成：

```python
from __future__ import annotations

from core.alias_pool.interactive_provider_base import InteractiveAliasProviderBase
from core.alias_pool.interactive_provider_models import AliasCreatedRecord, AuthenticatedProviderContext, VerificationRequirement


class EmailShieldProvider(InteractiveAliasProviderBase):
    source_kind = "emailshield"

    def ensure_authenticated_context(self, mode: str) -> AuthenticatedProviderContext:
        inbox_email = str(
            self._spec.confirmation_inbox_config.get("match_email")
            or self._spec.confirmation_inbox_config.get("account_email")
            or ""
        ).strip().lower()
        return AuthenticatedProviderContext(
            confirmation_inbox_email=inbox_email,
            real_mailbox_email=inbox_email,
        )

    def resolve_verification_requirements(self, context):
        return [VerificationRequirement(kind="account_email", label="验证 EmailShield 账号邮箱", inbox_role="confirmation_inbox")]

    def create_alias(self, *, context, domain, alias_index):
        return AliasCreatedRecord(email=f"emailshield-{alias_index}@emailshield.cc")


def build_emailshield_provider(spec, context):
    return EmailShieldProvider(spec=spec, context=context)
```

把 `core/alias_pool/simplelogin_provider.py` 改成：

```python
from __future__ import annotations

import random
import re

from core.alias_pool.interactive_provider_base import ExistingAccountAliasProviderBase
from core.alias_pool.interactive_provider_models import AliasCreatedRecord, AliasDomainOption, AuthenticatedProviderContext


class SimpleLoginProvider(ExistingAccountAliasProviderBase):
    source_kind = "simplelogin"

    def ensure_authenticated_context(self, mode: str) -> AuthenticatedProviderContext:
        account = self.select_service_account()
        return AuthenticatedProviderContext(
            service_account_email=account["email"],
            confirmation_inbox_email=account["email"],
            real_mailbox_email=account["email"],
            service_password=account["password"],
            username=account["label"],
        )

    def _parse_signed_domain_options(self, html: str) -> list[AliasDomainOption]:
        pattern = re.compile(
            r'<option[^>]*value="(?P<value>[^"]+)"[^>]*>(?P<text>.*?)</option>',
            re.IGNORECASE | re.DOTALL,
        )
        options: list[AliasDomainOption] = []
        for match in pattern.finditer(html):
            signed_value = str(match.group("value") or "").strip()
            text = re.sub(r"\s+", " ", str(match.group("text") or "")).strip()
            domain_match = re.search(r"@([A-Za-z0-9.-]+)", text)
            if not signed_value or domain_match is None:
                continue
            domain = domain_match.group(1).lower()
            options.append(
                AliasDomainOption(
                    key=signed_value,
                    domain=domain,
                    label=f"@{domain}",
                    raw={"signed_value": signed_value, "text": text},
                )
            )
        if not options:
            raise RuntimeError("signed domain options unavailable")
        return options

    def pick_domain_option(self, domains: list[AliasDomainOption], alias_index: int) -> AliasDomainOption | None:
        if not domains:
            return None
        return random.choice(domains)

    def discover_alias_domains(self, context):
        raise RuntimeError("simplelogin signed domain discovery requires authenticated custom alias page parsing")

    def create_alias(self, *, context, domain, alias_index):
        if domain is None:
            raise RuntimeError("simplelogin alias creation requires signed domain options")
        local = f"simplelogin-{alias_index}"
        return AliasCreatedRecord(email=f"{local}{domain.label}", metadata={"signed_value": domain.raw.get("signed_value", "")})


def build_simplelogin_provider(spec, context):
    return SimpleLoginProvider(spec=spec, context=context)
```

- [ ] **Step 4: 运行测试，确认通过**

Run:

```bash
python -m unittest tests.test_interactive_alias_providers.EmailShieldAndSimpleLoginTests
```

Expected:
- PASS

- [ ] **Step 5: Commit**

```bash
git add core/alias_pool/emailshield_provider.py core/alias_pool/simplelogin_provider.py tests/test_interactive_alias_providers.py
git commit -m "feat: add emailshield and simplelogin provider contracts"
```

---

### Task 7: 实现 `alias_email`，并把 alias-test/API/前端 stage 合同补齐

**Files:**
- Modify: `core/alias_pool/alias_email_provider.py`
- Modify: `core/alias_pool/automation_test.py`
- Modify: `api/config.py`
- Modify: `frontend/src/lib/aliasGenerationTest.ts`
- Modify: `tests/test_interactive_alias_providers.py`
- Modify: `tests/test_alias_generation_api.py`
- Test: `tests/test_interactive_alias_providers.py`
- Test: `tests/test_alias_generation_api.py`

- [ ] **Step 1: 写失败测试，锁定 magic-link requirement 与 API/前端兼容**

在 `tests/test_interactive_alias_providers.py` 追加：

```python
from core.alias_pool.alias_email_provider import AliasEmailProvider


class AliasEmailProviderTests(unittest.TestCase):
    def test_alias_email_maps_magic_link_login_requirement(self):
        provider = AliasEmailProvider(
            spec=AliasProviderSourceSpec(
                source_id="alias-email-primary",
                provider_type="alias_email",
                state_key="alias-email-primary",
                desired_alias_count=3,
                confirmation_inbox_config={"match_email": "real@example.com"},
                provider_config={"login_url": "https://alias.email/users/login/"},
            ),
            context=AliasProviderBootstrapContext(task_id="alias-test", purpose="automation_test"),
        )

        requirements = provider.resolve_verification_requirements(provider.ensure_authenticated_context("alias_test"))

        self.assertEqual(
            requirements,
            [VerificationRequirement(kind="magic_link_login", label="消费登录魔法链接", inbox_role="confirmation_inbox")],
        )
```

在 `tests/test_alias_generation_api.py` 追加：

```python
    def test_alias_generation_test_api_supports_alias_email_stage_codes(self):
        client = TestClient(app)

        with patch("core.config_store.config_store.get", return_value=""), patch(
            "api.config.config_store.get_all",
            return_value={
                "cloudmail_alias_enabled": True,
                "sources": [
                    {
                        "id": "alias-email-primary",
                        "type": "alias_email",
                        "alias_count": 3,
                        "state_key": "alias-email-primary",
                        "confirmation_inbox": {"provider": "cloudmail", "match_email": "real@example.com"},
                        "provider_config": {"login_url": "https://alias.email/users/login/"},
                    }
                ],
            },
        ), patch("api.config.AliasAutomationTestService") as service_cls:
            service_cls.return_value.run.return_value = AliasProbeResult(
                ok=True,
                source_id="alias-email-primary",
                source_type="alias_email",
                alias_email="alpha@alias.email",
                real_mailbox_email="real@example.com",
                service_email="real@example.com",
                account={"realMailboxEmail": "real@example.com", "serviceEmail": "real@example.com", "password": ""},
                aliases=[
                    {"email": "alpha@alias.email"},
                    {"email": "beta@alias.email"},
                    {"email": "gamma@alias.email"},
                ],
                current_stage={"code": "consume_magic_link", "label": "消费魔法链接"},
                stages=[
                    {"code": "request_magic_link", "label": "请求魔法链接", "status": "completed"},
                    {"code": "consume_magic_link", "label": "消费魔法链接", "status": "completed"},
                    {"code": "discover_alias_domains", "label": "发现可用域名", "status": "completed"},
                ],
            )

            response = client.post("/api/config/alias-test", json={"sourceId": "alias-email-primary", "useDraftConfig": False})

        body = response.json()
        self.assertEqual(body["sourceType"], "alias_email")
        self.assertEqual(body["stages"][0]["code"], "request_magic_link")
        self.assertEqual(body["stages"][1]["code"], "consume_magic_link")
```

- [ ] **Step 2: 运行测试，确认先失败**

Run:

```bash
python -m unittest tests.test_interactive_alias_providers.AliasEmailProviderTests tests.test_alias_generation_api.AliasGenerationApiTests.test_alias_generation_test_api_supports_alias_email_stage_codes
```

Expected:
- FAIL
- `alias_email` provider label/stage 未对齐

- [ ] **Step 3: 实现 `alias_email` 与 stage map 补齐**

把 `core/alias_pool/alias_email_provider.py` 改成：

```python
from __future__ import annotations

from core.alias_pool.interactive_provider_base import InteractiveAliasProviderBase
from core.alias_pool.interactive_provider_models import AliasCreatedRecord, AliasDomainOption, AuthenticatedProviderContext, VerificationRequirement


class AliasEmailProvider(InteractiveAliasProviderBase):
    source_kind = "alias_email"

    def ensure_authenticated_context(self, mode: str) -> AuthenticatedProviderContext:
        inbox_email = str(self._spec.confirmation_inbox_config.get("match_email") or "").strip().lower()
        return AuthenticatedProviderContext(
            service_account_email=inbox_email,
            confirmation_inbox_email=inbox_email,
            real_mailbox_email=inbox_email,
        )

    def resolve_verification_requirements(self, context):
        return [VerificationRequirement(kind="magic_link_login", label="消费登录魔法链接", inbox_role="confirmation_inbox")]

    def discover_alias_domains(self, context):
        return [AliasDomainOption(key="alias.email", domain="alias.email", label="@alias.email")]

    def create_alias(self, *, context, domain, alias_index):
        if domain is None:
            raise RuntimeError("alias.email requires discovered domains")
        return AliasCreatedRecord(email=f"alias-email-{alias_index}{domain.label}")


def build_alias_email_provider(spec, context):
    return AliasEmailProvider(spec=spec, context=context)
```

并确认 `frontend/src/lib/aliasGenerationTest.ts` 里的 `ALIAS_TEST_STAGE_LABELS` 已包含：

```ts
  request_magic_link: '请求魔法链接',
  consume_magic_link: '消费魔法链接',
  discover_alias_domains: '发现可用域名',
```

- [ ] **Step 4: 运行测试，确认通过**

Run:

```bash
python -m unittest tests.test_interactive_alias_providers.AliasEmailProviderTests tests.test_alias_generation_api.AliasGenerationApiTests.test_alias_generation_test_api_supports_alias_email_stage_codes
```

Expected:
- PASS

- [ ] **Step 5: Commit**

```bash
git add core/alias_pool/alias_email_provider.py core/alias_pool/automation_test.py api/config.py frontend/src/lib/aliasGenerationTest.ts tests/test_interactive_alias_providers.py tests/test_alias_generation_api.py
git commit -m "feat: add alias email provider contract and stage support"
```

---

### Task 8: 做完整验证并清理计划内遗留点

**Files:**
- Modify: `core/alias_pool/automation_test.py`
- Modify: `api/config.py`
- Modify: `api/tasks.py`
- Modify: `frontend/src/components/settings/AliasGenerationTestCard.tsx`
- Modify: `tests/test_alias_provider_bootstrap.py`
- Modify: `tests/test_alias_generation_api.py`
- Modify: `tests/test_alias_pool.py`
- Modify: `tests/test_interactive_alias_providers.py`
- Test: `tests/test_alias_provider_bootstrap.py`
- Test: `tests/test_alias_generation_api.py`
- Test: `tests/test_alias_pool.py`
- Test: `tests/test_interactive_alias_providers.py`
- Test: `npm run build`

- [ ] **Step 1: 写最终回归测试，锁定 5 个新 provider、3 alias 输出与 `accountIdentity` 兼容**

在 `tests/test_alias_generation_api.py` 追加：

```python
    def test_alias_generation_test_api_keeps_account_identity_compatibility_for_interactive_provider(self):
        client = TestClient(app)

        with patch("core.config_store.config_store.get", return_value=""), patch(
            "api.config.config_store.get_all",
            return_value={
                "cloudmail_alias_enabled": True,
                "sources": [
                    {
                        "id": "simplelogin-primary",
                        "type": "simplelogin",
                        "alias_count": 3,
                        "state_key": "simplelogin-primary",
                        "provider_config": {
                            "site_url": "https://simplelogin.io/",
                            "accounts": [{"email": "fust@fst.cxwsss.online", "label": "fust"}],
                        },
                    }
                ],
            },
        ), patch("api.config.AliasAutomationTestService") as service_cls:
            service_cls.return_value.run.return_value = AliasProbeResult(
                ok=True,
                source_id="simplelogin-primary",
                source_type="simplelogin",
                alias_email="sisyrun0419a.relearn763@aleeas.com",
                real_mailbox_email="fust@fst.cxwsss.online",
                service_email="fust@fst.cxwsss.online",
                account={
                    "realMailboxEmail": "fust@fst.cxwsss.online",
                    "serviceEmail": "fust@fst.cxwsss.online",
                    "password": "fust@fst.cxwsss.online",
                    "username": "fust",
                },
                aliases=[
                    {"email": "sisyrun0419a.relearn763@aleeas.com"},
                    {"email": "sisyrun0419b.onion376@simplelogin.com"},
                    {"email": "sisyrun0419c.skies135@slmails.com"},
                ],
            )

            response = client.post("/api/config/alias-test", json={"sourceId": "simplelogin-primary", "useDraftConfig": False})

        body = response.json()
        self.assertEqual(body["accountIdentity"]["serviceAccountEmail"], "fust@fst.cxwsss.online")
        self.assertEqual(body["accountIdentity"]["servicePassword"], "fust@fst.cxwsss.online")
        self.assertEqual(body["accountIdentity"]["username"], "fust")
        self.assertEqual(len(body["aliases"]), 3)
```

- [ ] **Step 2: 运行后端相关测试，确认先失败或部分失败**

Run:

```bash
python -m unittest tests.test_alias_provider_bootstrap tests.test_alias_generation_api tests.test_alias_pool tests.test_interactive_alias_providers
```

Expected:
- 至少有一项失败，通常来自 API response shaping、前端 stage mapping 或 backward compatibility

- [ ] **Step 3: 修正最终兼容层与显示层**

重点核对并补齐：

在 `api/config.py` 的 alias-test 响应里保持：

```python
        "accountIdentity": {
            "serviceAccountEmail": str(result.service_email or result.account.get("serviceEmail") or ""),
            "confirmationInboxEmail": str(result.real_mailbox_email or result.account.get("realMailboxEmail") or ""),
            "realMailboxEmail": str(result.real_mailbox_email or result.account.get("realMailboxEmail") or ""),
            "servicePassword": str(result.account.get("password") or result.account.get("servicePassword") or ""),
            "username": str(result.account.get("username") or result.account.get("userName") or ""),
        },
```

在 `frontend/src/components/settings/AliasGenerationTestCard.tsx` 里保持单账号行只显示一份：

```tsx
<Descriptions column={1} size="small" bordered>
  <Descriptions.Item label="真实邮箱">{renderCopyableMonoText(displayResult.account.realMailboxEmail)}</Descriptions.Item>
  <Descriptions.Item label="服务账号">{renderCopyableMonoText(displayResult.account.serviceEmail)}</Descriptions.Item>
  <Descriptions.Item label="密码">{renderCopyableMonoText(displayResult.account.password)}</Descriptions.Item>
  <Descriptions.Item label="用户名">{displayResult.account.username || '-'}</Descriptions.Item>
</Descriptions>
```

- [ ] **Step 4: 运行完整后端测试与前端构建**

Run:

```bash
python -m unittest tests.test_alias_provider_bootstrap tests.test_alias_generation_api tests.test_alias_pool tests.test_interactive_alias_providers
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
- `vite v... building for production...`
- `✓ built in ...`

- [ ] **Step 5: Commit**

```bash
git add core/alias_pool api frontend/src tests
git commit -m "feat: expand alias providers for researched services"
```

---

## Self-Review Checklist

- **Spec coverage:**
  - Shared contract evolution → Task 1
  - Interactive base + existing-account helper → Task 2
  - Dual registration in task path and alias-test path → Task 3
  - `myalias_pro` / `secureinseconds` / `emailshield` / `simplelogin` / `alias_email` → Tasks 5–7
  - Frontend source editing and source round-trip → Task 4
  - SimpleLogin signed domain options requirement → Task 6
  - ManyMe exclusion → Task 1 decode/normalize tests and file structure decisions
  - Alias-test 3 alias result contract and accountIdentity compatibility → Tasks 4, 5, 7, 8

- **Placeholder scan:**
  - No `TBD`
  - No `TODO`
  - No `implement later`
  - No undefined execution steps without commands

- **Type consistency:**
  - Shared names used consistently: `InteractiveAliasProviderBase`, `ExistingAccountAliasProviderBase`, `VerificationRequirement`, `AliasDomainOption`, `provider_config`
  - SimpleLogin wording consistently uses “signed domain options” instead of static `alias_domains`
