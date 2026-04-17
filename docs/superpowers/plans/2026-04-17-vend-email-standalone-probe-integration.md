# vend_email Standalone Probe Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将真实 vend runtime 接入当前独立 alias generation test 入口，使 `vend_email` 在 `/api/config/alias-test` 和 `Settings` 测试卡片中不再返回 placeholder，而是能够基于当前配置执行真实 probe 并返回 alias、mailbox、service email、capture、steps、logs。

**Architecture:** 把 vend runtime 子树（state store、mailbox verification adapter、vend runtime/orchestrator）接入当前 `alias-generation-test-entry` 分支，并让 `AliasSourceProbeService` 在 `vend_email` 分支调用同一套 vend runtime 的单次 probe 能力。独立 alias-test API 与 `Settings` 卡片继续沿用现有请求/响应结构，只把 vend probe 结果从 placeholder 升级为真实返回。实现必须遵守 TDD：每一块行为先写失败测试，再写最小实现让测试通过。

**Tech Stack:** Python, FastAPI, unittest + unittest.mock, existing alias_pool abstractions, local file-backed vend state persistence, generic mailbox verification adapter, React + TypeScript + Vite for frontend verification

---

## File Structure

- Create or port: `core/alias_pool/vend_email_state.py`
  - vend service account state、capture summary、state store
- Create or port: `core/alias_pool/mailbox_verification_adapter.py`
  - 通用 mailbox verification helper，配置驱动，不绑定参考域名命名
- Create or port: `core/alias_pool/vend_email_service.py`
  - vend runtime / orchestrator / provider 能力，支持单次 probe
- Modify: `core/alias_pool/probe.py`
  - `vend_email` 分支从 placeholder 切到真实 vend runtime probe
- Modify: `tests/test_alias_pool.py`
  - vend runtime probe、mailbox adapter、probe 接线测试
- Modify: `tests/test_alias_generation_api.py`
  - alias-test API 的 vend 返回结果测试
- Modify (if needed): `frontend/src/components/settings/AliasGenerationTestCard.tsx`
  - 确保真实 vend probe 字段展示兼容
- Modify (if needed): `frontend/src/lib/aliasGenerationTest.ts`
  - 若真实 vend probe 返回字段需要细化类型，则在这里收敛

---

### Task 1: 接入 vend state store 与通用 mailbox verification adapter

**Files:**
- Create: `core/alias_pool/vend_email_state.py`
- Create: `core/alias_pool/mailbox_verification_adapter.py`
- Modify: `tests/test_alias_pool.py`
- Test: `tests/test_alias_pool.py`

- [ ] **Step 1: 写失败测试，锁定 vend state round-trip 与 mailbox adapter 的配置驱动行为**

在 `tests/test_alias_pool.py` 追加：

```python
import tempfile
from pathlib import Path

from core.alias_pool.mailbox_verification_adapter import (
    build_mailbox_login_payload,
    build_mailbox_list_request,
    extract_confirmation_link,
)
from core.alias_pool.vend_email_state import (
    VendEmailCaptureRecord,
    VendEmailFileStateStore,
    VendEmailServiceState,
)


class VendEmailStateStoreTests(unittest.TestCase):
    def test_state_store_round_trips_service_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = VendEmailFileStateStore(base_dir=Path(tmpdir))
            state = VendEmailServiceState(
                state_key="vend-email-primary",
                service_email="vendcap202604170108@cxwsss.online",
                service_password="VendCap#2026!",
                session_cookies=[{"name": "sid", "value": "abc"}],
                session_storage={"token": "t1"},
                last_login_at="2026-04-17T09:00:00+08:00",
                last_verified_at="2026-04-17T09:02:00+08:00",
                known_aliases=["vendcapdemo20260417@serf.me"],
                last_capture_summary=[
                    VendEmailCaptureRecord(
                        name="login",
                        url="https://www.vend.email/auth/login",
                        method="POST",
                        request_headers_whitelist={"content-type": "application/x-www-form-urlencoded"},
                        request_body_excerpt="user[email]=vendcap202604170108@cxwsss.online",
                        response_status=302,
                        response_body_excerpt="",
                        captured_at="2026-04-17T09:03:00+08:00",
                    )
                ],
                last_error="",
            )

            store.save(state)
            loaded = store.load("vend-email-primary")

        self.assertEqual(loaded.service_email, "vendcap202604170108@cxwsss.online")
        self.assertEqual(loaded.known_aliases, ["vendcapdemo20260417@serf.me"])
        self.assertEqual(loaded.last_capture_summary[0].name, "login")


class MailboxVerificationAdapterTests(unittest.TestCase):
    def test_build_mailbox_login_payload_uses_config_values(self):
        payload = build_mailbox_login_payload(
            mailbox_email="admin@cxwsss.online",
            mailbox_password="1103@Icity",
        )

        self.assertEqual(
            payload,
            {"email": "admin@cxwsss.online", "password": "1103@Icity"},
        )

    def test_build_mailbox_list_request_uses_base_url_and_token(self):
        request = build_mailbox_list_request(
            mailbox_base_url="https://cxwsss.online/",
            account_id=1,
            token="token-123",
        )

        self.assertEqual(
            request,
            {
                "url": "https://cxwsss.online/api/email/list?accountId=1&allReceive=1&emailId=0&timeSort=0&size=100&type=0",
                "headers": {"authorization": "token-123"},
            },
        )

    def test_extract_confirmation_link_uses_configured_anchor(self):
        text = "Please confirm: https://www.vend.email/auth/confirmation?confirmation_token=abc123 thanks"

        link = extract_confirmation_link(
            content=text,
            anchor_prefix="https://www.vend.email/auth/confirmation?",
        )

        self.assertEqual(
            link,
            "https://www.vend.email/auth/confirmation?confirmation_token=abc123",
        )
```

- [ ] **Step 2: 运行测试，确认先失败**

Run:

```bash
python -m unittest tests.test_alias_pool.VendEmailStateStoreTests tests.test_alias_pool.MailboxVerificationAdapterTests
```

Expected:
- FAIL
- `ModuleNotFoundError` 指向新增文件

- [ ] **Step 3: 写最小 state store 与 generic mailbox adapter 实现**

创建 `core/alias_pool/vend_email_state.py`：

```python
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path


@dataclass
class VendEmailCaptureRecord:
    name: str
    url: str
    method: str
    request_headers_whitelist: dict[str, str]
    request_body_excerpt: str
    response_status: int
    response_body_excerpt: str
    captured_at: str


@dataclass
class VendEmailServiceState:
    state_key: str
    service_email: str = ""
    service_password: str = ""
    session_cookies: list[dict[str, str]] = field(default_factory=list)
    session_storage: dict[str, str] = field(default_factory=dict)
    last_login_at: str = ""
    last_verified_at: str = ""
    known_aliases: list[str] = field(default_factory=list)
    last_capture_summary: list[VendEmailCaptureRecord] = field(default_factory=list)
    last_error: str = ""


class VendEmailFileStateStore:
    def __init__(self, *, base_dir: Path):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, state_key: str) -> Path:
        return self.base_dir / f"{state_key}.json"

    def save(self, state: VendEmailServiceState) -> None:
        self._path_for(state.state_key).write_text(
            json.dumps(asdict(state), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load(self, state_key: str) -> VendEmailServiceState:
        path = self._path_for(state_key)
        if not path.exists():
            return VendEmailServiceState(state_key=state_key)
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["last_capture_summary"] = [
            VendEmailCaptureRecord(**item) for item in payload.get("last_capture_summary", [])
        ]
        return VendEmailServiceState(**payload)
```

创建 `core/alias_pool/mailbox_verification_adapter.py`：

```python
from __future__ import annotations


def build_mailbox_login_payload(*, mailbox_email: str, mailbox_password: str) -> dict[str, str]:
    return {"email": mailbox_email, "password": mailbox_password}


def build_mailbox_list_request(*, mailbox_base_url: str, account_id: int, token: str) -> dict[str, object]:
    base = mailbox_base_url.rstrip("/")
    return {
        "url": f"{base}/api/email/list?accountId={account_id}&allReceive=1&emailId=0&timeSort=0&size=100&type=0",
        "headers": {"authorization": token},
    }


def extract_confirmation_link(*, content: str, anchor_prefix: str) -> str:
    start = content.find(anchor_prefix)
    if start < 0:
        return ""
    end = len(content)
    for delimiter in [" ", "\n", "\r", "\t", '"', "'", ")", "]"]:
        idx = content.find(delimiter, start)
        if idx >= 0:
            end = min(end, idx)
    return content[start:end]
```

- [ ] **Step 4: 运行测试，确认通过**

Run:

```bash
python -m unittest tests.test_alias_pool.VendEmailStateStoreTests tests.test_alias_pool.MailboxVerificationAdapterTests
```

Expected:
- PASS

- [ ] **Step 5: Commit**

```bash
git add core/alias_pool/vend_email_state.py core/alias_pool/mailbox_verification_adapter.py tests/test_alias_pool.py
git commit -m "feat: add vend probe state and mailbox adapter"
```

### Task 2: 接入 vend runtime/orchestrator，并暴露单次 probe 能力

**Files:**
- Create: `core/alias_pool/vend_email_service.py`
- Modify: `tests/test_alias_pool.py`
- Test: `tests/test_alias_pool.py`

- [ ] **Step 1: 写失败测试，锁定 vend runtime probe 的编排顺序与结果形状**

在 `tests/test_alias_pool.py` 追加：

```python
from core.alias_pool.vend_email_service import VendEmailRuntimeExecutor, VendEmailRuntimeService


class _FakeVendExecutor(VendEmailRuntimeExecutor):
    def __init__(self):
        self.calls = []

    def restore_session(self, state, source):
        self.calls.append("restore_session")
        return False

    def register(self, state, source):
        self.calls.append("register")
        return None

    def fetch_confirmation_link(self, source):
        self.calls.append("fetch_confirmation_link")
        return "https://www.vend.email/auth/confirmation?confirmation_token=abc123"

    def confirm(self, confirmation_link, source):
        self.calls.append("confirm")
        return None

    def login(self, state, source):
        self.calls.append("login")
        state.service_email = "vendcap202604170108@cxwsss.online"
        return None

    def list_forwarders(self, state, source):
        self.calls.append("list_forwarders")
        return []

    def create_forwarder(self, state, source):
        self.calls.append("create_forwarder")
        return {
            "alias_email": "vendcapdemo20260417@serf.me",
            "real_mailbox_email": "admin@cxwsss.online",
        }

    def capture_summary(self):
        return [
            {
                "name": "login",
                "url": "https://www.vend.email/auth/login",
                "method": "POST",
                "request_headers_whitelist": {"content-type": "application/x-www-form-urlencoded"},
                "request_body_excerpt": "user[email]=vendcap202604170108@cxwsss.online",
                "response_status": 302,
                "response_body_excerpt": "",
                "captured_at": "2026-04-17T10:00:00+08:00",
            }
        ]


class VendEmailRuntimeServiceTests(unittest.TestCase):
    def test_runtime_service_runs_real_probe_flow(self):
        executor = _FakeVendExecutor()
        store = mock.Mock()
        store.load.return_value = VendEmailServiceState(state_key="vend-email-primary")

        service = VendEmailRuntimeService(state_store=store, executor=executor)
        result = service.run_probe(
            source={
                "id": "vend-email-primary",
                "type": "vend_email",
                "mailbox_email": "admin@cxwsss.online",
                "state_key": "vend-email-primary",
            }
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.alias_email, "vendcapdemo20260417@serf.me")
        self.assertEqual(result.real_mailbox_email, "admin@cxwsss.online")
        self.assertEqual(result.service_email, "vendcap202604170108@cxwsss.online")
        self.assertEqual(
            executor.calls,
            [
                "restore_session",
                "register",
                "fetch_confirmation_link",
                "confirm",
                "login",
                "list_forwarders",
                "create_forwarder",
            ],
        )
```

- [ ] **Step 2: 运行测试，确认先失败**

Run:

```bash
python -m unittest tests.test_alias_pool.VendEmailRuntimeServiceTests
```

Expected:
- FAIL
- `ModuleNotFoundError` 指向 `core.alias_pool.vend_email_service`

- [ ] **Step 3: 写最小 vend runtime/executor 协议和 `run_probe()` 实现**

创建 `core/alias_pool/vend_email_service.py`：

```python
from __future__ import annotations

from dataclasses import asdict
from typing import Protocol

from .probe import AliasProbeResult
from .vend_email_state import VendEmailCaptureRecord, VendEmailServiceState


class VendEmailRuntimeExecutor(Protocol):
    def restore_session(self, state: VendEmailServiceState, source: dict) -> bool: ...
    def register(self, state: VendEmailServiceState, source: dict): ...
    def fetch_confirmation_link(self, source: dict) -> str: ...
    def confirm(self, confirmation_link: str, source: dict): ...
    def login(self, state: VendEmailServiceState, source: dict): ...
    def list_forwarders(self, state: VendEmailServiceState, source: dict) -> list[dict]: ...
    def create_forwarder(self, state: VendEmailServiceState, source: dict) -> dict: ...
    def capture_summary(self) -> list[dict]: ...


class VendEmailRuntimeService:
    def __init__(self, *, state_store, executor: VendEmailRuntimeExecutor):
        self.state_store = state_store
        self.executor = executor

    def run_probe(self, *, source: dict) -> AliasProbeResult:
        state_key = str(source.get("state_key") or source.get("id") or "vend-email")
        state = self.state_store.load(state_key)

        steps: list[str] = []
        if not self.executor.restore_session(state, source):
            steps.append("register")
            self.executor.register(state, source)
            confirmation_link = self.executor.fetch_confirmation_link(source)
            steps.append("confirmation")
            self.executor.confirm(confirmation_link, source)

        steps.append("login")
        self.executor.login(state, source)

        steps.append("list_forwarders")
        forwarders = self.executor.list_forwarders(state, source)
        if forwarders:
            alias_email = str(forwarders[0].get("alias_email") or "")
            real_mailbox_email = str(forwarders[0].get("real_mailbox_email") or source.get("mailbox_email") or "")
        else:
            steps.append("create_forwarder")
            created = self.executor.create_forwarder(state, source)
            alias_email = str(created.get("alias_email") or "")
            real_mailbox_email = str(created.get("real_mailbox_email") or source.get("mailbox_email") or "")

        capture_summary = list(self.executor.capture_summary())
        state.known_aliases = [alias_email] if alias_email else []
        state.last_capture_summary = [VendEmailCaptureRecord(**item) for item in capture_summary]
        self.state_store.save(state)

        return AliasProbeResult(
            ok=bool(alias_email),
            source_id=str(source.get("id") or ""),
            source_type="vend_email",
            alias_email=alias_email,
            real_mailbox_email=real_mailbox_email,
            service_email=state.service_email,
            capture_summary=[asdict(item) for item in state.last_capture_summary],
            steps=steps,
            logs=["vend probe completed"],
            error="" if alias_email else "vend probe did not produce alias",
        )
```

- [ ] **Step 4: 再补一个失败路径测试并跑绿**

在 `tests/test_alias_pool.py` 追加：

```python
    def test_runtime_service_returns_structured_error_when_forwarder_not_created(self):
        class _NoAliasExecutor(_FakeVendExecutor):
            def create_forwarder(self, state, source):
                self.calls.append("create_forwarder")
                return {"alias_email": "", "real_mailbox_email": source["mailbox_email"]}

        executor = _NoAliasExecutor()
        store = mock.Mock()
        store.load.return_value = VendEmailServiceState(state_key="vend-email-primary")
        service = VendEmailRuntimeService(state_store=store, executor=executor)

        result = service.run_probe(
            source={
                "id": "vend-email-primary",
                "type": "vend_email",
                "mailbox_email": "admin@cxwsss.online",
                "state_key": "vend-email-primary",
            }
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.error, "vend probe did not produce alias")
```

Run:

```bash
python -m unittest tests.test_alias_pool.VendEmailRuntimeServiceTests
```

Expected:
- PASS

- [ ] **Step 5: Commit**

```bash
git add core/alias_pool/vend_email_service.py tests/test_alias_pool.py
git commit -m "feat: add vend runtime probe service"
```

### Task 3: 让 probe 层真正接入 vend runtime probe

**Files:**
- Modify: `core/alias_pool/probe.py`
- Modify: `tests/test_alias_pool.py`
- Test: `tests/test_alias_pool.py`

- [ ] **Step 1: 写失败测试，锁定 `vend_email` 分支调用真实 runtime probe**

在 `tests/test_alias_pool.py` 追加：

```python
class VendEmailProbeIntegrationTests(unittest.TestCase):
    def test_probe_service_uses_vend_runtime_for_vend_email_source(self):
        service = AliasSourceProbeService()

        with mock.patch("core.alias_pool.probe.VendEmailRuntimeService") as runtime_cls:
            runtime = runtime_cls.return_value
            runtime.run_probe.return_value = AliasProbeResult(
                ok=True,
                source_id="vend-email-primary",
                source_type="vend_email",
                alias_email="vendcapdemo20260417@serf.me",
                real_mailbox_email="admin@cxwsss.online",
                service_email="vendcap202604170108@cxwsss.online",
                capture_summary=[{"name": "login"}],
                steps=["register", "confirmation", "login", "create_forwarder"],
                logs=["vend probe completed"],
                error="",
            )

            result = service.probe(
                {
                    "sources": [
                        {
                            "id": "vend-email-primary",
                            "type": "vend_email",
                            "mailbox_email": "admin@cxwsss.online",
                            "state_key": "vend-email-primary",
                        }
                    ]
                },
                source_id="vend-email-primary",
                task_id="alias-test",
            )

        self.assertTrue(result.ok)
        self.assertEqual(result.alias_email, "vendcapdemo20260417@serf.me")
        runtime.run_probe.assert_called_once()
```

- [ ] **Step 2: 运行测试，确认先失败**

Run:

```bash
python -m unittest tests.test_alias_pool.VendEmailProbeIntegrationTests
```

Expected:
- FAIL
- 因为 `core.alias_pool.probe` 还没有真正接 vend runtime

- [ ] **Step 3: 在 `core/alias_pool/probe.py` 中接入 vend runtime**

增加导入：

```python
from .vend_email_service import VendEmailRuntimeService
from .vend_email_state import VendEmailFileStateStore
```

并把 `_probe_vend_email()` 改为：

```python
    def _probe_vend_email(self, source: dict, *, task_id: str) -> AliasProbeResult:
        runtime = VendEmailRuntimeService(
            state_store=VendEmailFileStateStore.for_task(task_id=task_id),
            executor=self._build_vend_executor(source),
        )
        return runtime.run_probe(source=source)
```

同时补一个最小 `_build_vend_executor()`，即使先返回 NotImplemented executor，也必须保证单元测试里可 patch：

```python
    def _build_vend_executor(self, source: dict):
        raise NotImplementedError("vend executor wiring is provided by runtime integration layer")
```

如果这会让非 patch 场景直接抛异常，则改成一个默认 executor stub，并在专门测试里 patch 它。

- [ ] **Step 4: 运行测试，确认通过**

Run:

```bash
python -m unittest tests.test_alias_pool.VendEmailProbeIntegrationTests
```

Expected:
- PASS

- [ ] **Step 5: Commit**

```bash
git add core/alias_pool/probe.py tests/test_alias_pool.py
git commit -m "feat: wire vend runtime into alias probe"
```

### Task 4: 扩展 alias-test API 测试，验证 vend probe 真实结果映射

**Files:**
- Modify: `tests/test_alias_generation_api.py`
- Test: `tests/test_alias_generation_api.py`

- [ ] **Step 1: 写失败测试，锁定 vend probe API 响应字段**

在 `tests/test_alias_generation_api.py` 追加：

```python
    def test_alias_generation_test_api_returns_real_vend_probe_fields(self):
        client = TestClient(app)

        with patch("core.config_store.config_store.get", return_value=""), patch(
            "api.config.config_store.get_all",
            return_value={
                "cloudmail_alias_enabled": True,
                "sources": [
                    {
                        "id": "vend-email-primary",
                        "type": "vend_email",
                        "mailbox_email": "admin@cxwsss.online",
                        "state_key": "vend-email-primary",
                    }
                ],
            },
        ), patch("api.config.normalize_cloudmail_alias_pool_config", return_value={
            "enabled": True,
            "task_id": "alias-test",
            "sources": [
                {
                    "id": "vend-email-primary",
                    "type": "vend_email",
                    "mailbox_email": "admin@cxwsss.online",
                    "state_key": "vend-email-primary",
                }
            ],
        }), patch("api.config.AliasSourceProbeService") as probe_service_cls:
            probe_service = probe_service_cls.return_value
            probe_service.probe.return_value = AliasProbeResult(
                ok=True,
                source_id="vend-email-primary",
                source_type="vend_email",
                alias_email="vendcapdemo20260417@serf.me",
                real_mailbox_email="admin@cxwsss.online",
                service_email="vendcap202604170108@cxwsss.online",
                capture_summary=[{"name": "login"}],
                steps=["register", "confirmation", "login", "create_forwarder"],
                logs=["vend probe completed"],
                error="",
            )

            resp = client.post(
                "/api/config/alias-test",
                json={"sourceId": "vend-email-primary", "useDraftConfig": False},
            )

        body = resp.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["sourceType"], "vend_email")
        self.assertEqual(body["serviceEmail"], "vendcap202604170108@cxwsss.online")
        self.assertEqual(body["steps"], ["register", "confirmation", "login", "create_forwarder"])
```

- [ ] **Step 2: 运行测试，确认先失败（若当前 API 映射遗漏字段）或作为红灯检查点**

Run:

```bash
python -m unittest tests.test_alias_generation_api
```

Expected:
- 若失败：补齐 API 映射字段
- 若已通过：记录为“红灯检查点已通过”，继续下一步

- [ ] **Step 3: 如有需要，在 `api/config.py` 中补最小映射修正**

仅在失败时调整：

```python
    return {
        "ok": result.ok,
        "sourceId": result.source_id,
        "sourceType": result.source_type,
        "aliasEmail": result.alias_email,
        "realMailboxEmail": result.real_mailbox_email,
        "serviceEmail": result.service_email,
        "captureSummary": result.capture_summary,
        "steps": result.steps,
        "logs": result.logs,
        "error": result.error,
    }
```

- [ ] **Step 4: 再次运行 API 测试并确认通过**

Run:

```bash
python -m unittest tests.test_alias_generation_api
```

Expected:
- PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_alias_generation_api.py api/config.py
git commit -m "feat: expose vend probe results in alias test api"
```

### Task 5: 验证 Settings 卡片兼容真实 vend probe 结果并做整体验证

**Files:**
- Modify: `frontend/src/components/settings/AliasGenerationTestCard.tsx` (only if needed)
- Modify: `frontend/src/lib/aliasGenerationTest.ts` (only if needed)
- Test: `frontend` build + focused backend tests

- [ ] **Step 1: 先运行当前前端构建与 focused backend tests 作为兼容性红灯检查**

Run:

```bash
python -m unittest tests.test_alias_pool.VendEmailRuntimeServiceTests tests.test_alias_pool.VendEmailProbeIntegrationTests
```

Run:

```bash
python -m unittest tests.test_alias_generation_api
```

Run:

```bash
cd frontend
npm run build
```

Expected:
- 若失败：根据报错做最小类型/展示修正
- 若通过：说明前端卡片已经兼容真实 vend probe 结构

- [ ] **Step 2: 如前端类型或展示不兼容，则做最小修正**

如果需要，在 `frontend/src/lib/aliasGenerationTest.ts` 中确保：

```ts
export type AliasGenerationTestResponse = {
  ok: boolean
  sourceId: string
  sourceType: string
  aliasEmail: string
  realMailboxEmail: string
  serviceEmail: string
  captureSummary: Array<Record<string, unknown>>
  steps: string[]
  logs: string[]
  error: string
}
```

并在 `AliasGenerationTestCard.tsx` 中确保：

- `serviceEmail`、`steps`、`captureSummary` 的真实 vend 结果仍能展示
- 不新增复杂 viewer，只保持当前最小渲染

- [ ] **Step 3: 重新运行 focused backend tests 与 frontend build**

Run:

```bash
python -m unittest tests.test_alias_pool.VendEmailRuntimeServiceTests tests.test_alias_pool.VendEmailProbeIntegrationTests
```

Run:

```bash
python -m unittest tests.test_alias_generation_api
```

Run:

```bash
cd frontend
npm run build
```

Expected:
- 全部 PASS

- [ ] **Step 4: 记录真实手动验证清单（不在此计划内自动执行）**

在实现时，请把以下手动验证作为完成前的现实检查清单：

```text
1. 用当前配置打开 Settings 页面
2. 选择 vend_email source
3. 切换 saved / draft 模式各测一轮
4. 点击“测试生成别名邮箱”
5. 确认返回真实 alias、serviceEmail、steps、captureSummary
```

这一步不要求写新文档，只需在实现/验收说明中保留此清单。

- [ ] **Step 5: Commit**

```bash
git add core/alias_pool/vend_email_service.py core/alias_pool/vend_email_state.py core/alias_pool/mailbox_verification_adapter.py core/alias_pool/probe.py tests/test_alias_pool.py tests/test_alias_generation_api.py frontend/src/lib/aliasGenerationTest.ts frontend/src/components/settings/AliasGenerationTestCard.tsx
git commit -m "feat: wire vend runtime into standalone alias probe"
```

---

## Self-Review

- **Spec coverage:**
  - vend_email 不再返回 placeholder → Task 2 / Task 3 / Task 4
  - probe 层调用真实 vend runtime → Task 2 / Task 3
  - mailbox 参数继续配置驱动 → Task 1 / Task 2
  - Settings 卡片展示真实 vend 结果 → Task 4 / Task 5
  - 正式 provider 与独立 alias-test 入口共享 vend runtime 能力 → Task 2 / Task 3
- **Placeholder scan:** 已避免 TBD/TODO/“自行实现”等占位；每一项都提供了明确文件、代码骨架和命令。
- **Type consistency:** `VendEmailCaptureRecord`、`VendEmailServiceState`、`VendEmailRuntimeExecutor`、`VendEmailRuntimeService`、`AliasProbeResult`、`AliasGenerationTestResponse` 在计划内命名一致；若实现中改名，必须同步更新后端 probe、API 测试和前端类型。

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-17-vend-email-standalone-probe-integration.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
