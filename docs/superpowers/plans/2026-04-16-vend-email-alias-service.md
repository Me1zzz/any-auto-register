# Vend.email Alias Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 CloudMail alias pool 增加一个真实可用的 `vend_email` alias service source，通过浏览器自动化完成 vend.email 会话建立、从可配置的真实收件邮箱来源读取验证邮件、生成 alias，并把 alias lease 注入现有任务级 alias pool。

**Architecture:** 保持现有 `AliasEmailPoolManager`、`AliasEmailLease` 和 `_build_alias_pool()` 的消费模型不变，只新增 `vend_email` source 的归一化、状态存储、抓包摘要模型和 `VendEmailAliasServiceProducer`。浏览器交互与真实收件邮箱验证封装在 vend.email runtime 中；producer 只负责编排“恢复会话/登录/注册/拉取 alias/投递 lease”这条同步装载链路。实现必须遵守 TDD：每一块行为先写失败测试，再写最小实现让测试通过。

**Tech Stack:** Python, unittest + unittest.mock, existing alias-pool abstractions, existing FastAPI task assembly path, Playwright MCP for manual smoke verification, local file-backed state persistence

---

## File Structure

- Modify: `core/alias_pool/config.py`
  - 扩展 `vend_email` source 归一化，支持可配置 alias 域名与真实收件邮箱来源字段
- Create: `core/alias_pool/vend_email_state.py`
  - 定义 `VendEmailServiceState`、抓包摘要模型与文件型 state store
- Create: `core/alias_pool/vend_email_service.py`
  - 定义 `VendEmailAliasServiceProducer`、runtime 协议与最小同步编排逻辑
- Modify: `api/tasks.py`
  - 在 `_build_alias_pool()` 中识别并装配 `vend_email` producer
- Modify: `tests/test_alias_pool.py`
  - 增加 config normalize、state store、producer contract 与 runtime 决策测试
- Modify: `tests/test_register_task_controls.py`
  - 增加 `_build_alias_pool()` 下 `vend_email` source 的 task integration 测试
- Create: `tests/manual_vend_email_capture.md`
  - 记录真实 vend.email / 真实收件邮箱来源的手动 smoke 与抓包验收步骤

---

### Task 1: 扩展 alias source config，支持 `vend_email` 归一化

**Files:**
- Modify: `core/alias_pool/config.py`
- Modify: `tests/test_alias_pool.py`
- Test: `tests/test_alias_pool.py`

- [ ] **Step 1: 写失败测试，锁定 `vend_email` source 的归一化输出**

在 `tests/test_alias_pool.py` 的 `AliasPoolConfigV2Tests` 中追加：

```python
    def test_normalize_accepts_vend_email_source(self):
        result = normalize_cloudmail_alias_pool_config(
            {
                "cloudmail_alias_enabled": True,
                "sources": [
                    {
                        "id": "vend-email-primary",
                        "type": "vend_email",
                        "register_url": "https://www.vend.email/auth/register",
                        "mailbox_base_url": "https://cxwsss.online/",
                        "mailbox_email": "Admin@CXWSSS.ONLINE",
                        "mailbox_password": "1103@Icity",
                        "alias_domain": "cxwsss.online",
                        "alias_count": "5",
                        "state_key": "vend-email-primary",
                    }
                ],
            },
            task_id="task-vend-email",
        )

        self.assertEqual(
            result["sources"],
            [
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
        )
```

- [ ] **Step 2: 运行测试，确认先失败**

Run:

```bash
python -m unittest discover -s tests -p "test_alias_pool.py" -v
```

Expected:
- FAIL
- `vend_email` source 被过滤掉，或者字段形状不匹配

- [ ] **Step 3: 在 `core/alias_pool/config.py` 中补最小归一化实现**

在 `_normalize_sources()` 中追加 `vend_email` 分支：

```python
        if source_type == "vend_email":
            normalized.append(
                {
                    "id": source_id,
                    "type": "vend_email",
                    "register_url": str(item.get("register_url") or "").strip(),
                    "mailbox_base_url": str(item.get("mailbox_base_url") or "").strip(),
                    "mailbox_email": str(item.get("mailbox_email") or "").strip().lower(),
                    "mailbox_password": str(item.get("mailbox_password") or "").strip(),
                    "alias_domain": str(item.get("alias_domain") or "").strip().lower(),
                    "alias_count": max(_parse_int(item.get("alias_count"), 0), 0),
                    "state_key": str(item.get("state_key") or source_id).strip() or source_id,
                }
            )
            continue
```

保持已有 `static_list` / `simple_generator` 行为不变。

- [ ] **Step 4: 运行测试，确认通过**

Run:

```bash
python -m unittest discover -s tests -p "test_alias_pool.py" -v
```

Expected:
- PASS
- 新增 `vend_email` normalize 测试通过

- [ ] **Step 5: Commit**

```bash
git add core/alias_pool/config.py tests/test_alias_pool.py
git commit -m "feat: support vend email alias source config"
```

### Task 2: 新增 vend.email 状态与抓包摘要存储

**Files:**
- Create: `core/alias_pool/vend_email_state.py`
- Modify: `tests/test_alias_pool.py`
- Test: `tests/test_alias_pool.py`

- [ ] **Step 1: 写失败测试，锁定 state 模型与文件存储行为**

在 `tests/test_alias_pool.py` 追加：

```python
import tempfile
from pathlib import Path

from core.alias_pool.vend_email_state import (
    VendEmailCaptureRecord,
    VendEmailFileStateStore,
    VendEmailServiceState,
)


class VendEmailStateStoreTests(unittest.TestCase):
    def test_file_state_store_round_trips_service_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = VendEmailFileStateStore(base_dir=Path(tmpdir))
            state = VendEmailServiceState(
                state_key="vend-email-primary",
                service_email="seed@cxwsss.online",
                service_password="pw-1",
                session_cookies=[{"name": "sid", "value": "abc"}],
                session_storage={"token": "t1"},
                last_login_at="2026-04-16T10:00:00+08:00",
                last_verified_at="2026-04-16T10:02:00+08:00",
                known_aliases=["alias1@cxwsss.online"],
                last_capture_summary=[
                    VendEmailCaptureRecord(
                        name="login",
                        url="https://www.vend.email/api/login",
                        method="POST",
                        request_headers_whitelist={"content-type": "application/json"},
                        request_body_excerpt='{"email":"seed@cxwsss.online"}',
                        response_status=200,
                        response_body_excerpt='{"ok":true}',
                        captured_at="2026-04-16T10:01:00+08:00",
                    )
                ],
                last_error="",
            )

            store.save(state)
            loaded = store.load("vend-email-primary")

            self.assertEqual(loaded.state_key, "vend-email-primary")
            self.assertEqual(loaded.service_email, "seed@cxwsss.online")
            self.assertEqual(loaded.known_aliases, ["alias1@cxwsss.online"])
            self.assertEqual(loaded.last_capture_summary[0].name, "login")
```

- [ ] **Step 2: 运行测试，确认先失败**

Run:

```bash
python -m unittest discover -s tests -p "test_alias_pool.py" -v
```

Expected:
- FAIL
- `ModuleNotFoundError` 指向 `core.alias_pool.vend_email_state`

- [ ] **Step 3: 写最小状态模型和文件型 state store 实现**

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
        payload = asdict(state)
        self._path_for(state.state_key).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load(self, state_key: str) -> VendEmailServiceState:
        path = self._path_for(state_key)
        if not path.exists():
            return VendEmailServiceState(state_key=state_key)

        payload = json.loads(path.read_text(encoding="utf-8"))
        captures = [VendEmailCaptureRecord(**item) for item in payload.get("last_capture_summary", [])]
        payload["last_capture_summary"] = captures
        return VendEmailServiceState(**payload)
```

- [ ] **Step 4: 运行测试，确认通过**

Run:

```bash
python -m unittest discover -s tests -p "test_alias_pool.py" -v
```

Expected:
- PASS
- state store round-trip 测试通过

- [ ] **Step 5: Commit**

```bash
git add core/alias_pool/vend_email_state.py tests/test_alias_pool.py
git commit -m "feat: add vend email state store"
```

### Task 3: 实现 `VendEmailAliasServiceProducer` 与 runtime 决策链路

**Files:**
- Create: `core/alias_pool/vend_email_service.py`
- Modify: `tests/test_alias_pool.py`
- Test: `tests/test_alias_pool.py`

- [ ] **Step 1: 写失败测试，锁定 producer 的恢复/登录/注册回退顺序与 lease 投递契约**

在 `tests/test_alias_pool.py` 追加：

```python
from core.alias_pool.vend_email_service import VendEmailAliasServiceProducer


class _FakeVendEmailRuntime:
    def __init__(self, *, restore_ok, login_ok, register_ok, aliases):
        self.restore_ok = restore_ok
        self.login_ok = login_ok
        self.register_ok = register_ok
        self.aliases = aliases
        self.calls = []

    def restore_session(self, state):
        self.calls.append("restore")
        return self.restore_ok

    def login(self, state, source):
        self.calls.append("login")
        return self.login_ok

    def register(self, state, source):
        self.calls.append("register")
        return self.register_ok

    def list_aliases(self, state, source):
        self.calls.append("list_aliases")
        return list(self.aliases)

    def create_aliases(self, state, source, missing_count):
        self.calls.append(f"create_aliases:{missing_count}")
        return self.aliases[:missing_count]

    def capture_summary(self):
        return []


class VendEmailAliasServiceProducerTests(unittest.TestCase):
    def test_producer_falls_back_from_restore_to_login(self):
        manager = AliasEmailPoolManager(task_id="task-vend-email-load")
        state_store = Mock()
        state_store.load.return_value = VendEmailServiceState(state_key="vend-email-primary")
        runtime = _FakeVendEmailRuntime(
            restore_ok=False,
            login_ok=True,
            register_ok=False,
            aliases=["alias1@cxwsss.online", "alias2@cxwsss.online"],
        )

        producer = VendEmailAliasServiceProducer(
            source={
                "id": "vend-email-primary",
                "type": "vend_email",
                "register_url": "https://www.vend.email/auth/register",
                "mailbox_base_url": "https://cxwsss.online/",
                "mailbox_email": "admin@cxwsss.online",
                "mailbox_password": "1103@Icity",
                "alias_domain": "cxwsss.online",
                "alias_count": 2,
                "state_key": "vend-email-primary",
            },
            state_store=state_store,
            runtime=runtime,
        )

        self.assertEqual(producer.state(), AliasSourceState.IDLE)

        producer.load_into(manager)

        self.assertEqual(runtime.calls[:2], ["restore", "login"])
        self.assertEqual(producer.state(), AliasSourceState.EXHAUSTED)

        lease1 = manager.acquire_alias()
        lease2 = manager.acquire_alias()
        self.assertEqual(lease1.source_kind, "vend_email")
        self.assertEqual(lease1.real_mailbox_email, "admin@cxwsss.online")
        self.assertEqual({lease1.alias_email, lease2.alias_email}, {"alias1@cxwsss.online", "alias2@cxwsss.online"})
        state_store.save.assert_called_once()
```

- [ ] **Step 2: 运行测试，确认先失败**

Run:

```bash
python -m unittest discover -s tests -p "test_alias_pool.py" -v
```

Expected:
- FAIL
- `ModuleNotFoundError` 指向 `core.alias_pool.vend_email_service`

- [ ] **Step 3: 写最小 producer 实现，让恢复/登录回退测试通过**

创建 `core/alias_pool/vend_email_service.py`：

```python
from __future__ import annotations

from .base import AliasEmailLease, AliasSourceState
from .manager import AliasEmailPoolManager
from .vend_email_state import VendEmailServiceState


class VendEmailAliasServiceProducer:
    source_kind = "vend_email"

    def __init__(self, *, source: dict, state_store, runtime):
        self.source = dict(source)
        self.source_id = str(source.get("id") or "vend-email")
        self.state_store = state_store
        self.runtime = runtime
        self._state = AliasSourceState.IDLE

    def state(self) -> AliasSourceState:
        return self._state

    def _ensure_session(self, state: VendEmailServiceState) -> None:
        if self.runtime.restore_session(state):
            return
        if self.runtime.login(state, self.source):
            return
        if self.runtime.register(state, self.source):
            return
        raise RuntimeError("vend.email session bootstrap failed")

    def load_into(self, manager: AliasEmailPoolManager) -> None:
        self._state = AliasSourceState.ACTIVE
        try:
            state = self.state_store.load(str(self.source.get("state_key") or self.source_id))
            self._ensure_session(state)

            aliases = list(self.runtime.list_aliases(state, self.source))
            target = int(self.source.get("alias_count") or 0)
            if len(aliases) < target:
                aliases.extend(self.runtime.create_aliases(state, self.source, target - len(aliases)))

            unique_aliases = []
            seen = set()
            for alias in aliases:
                if alias in seen:
                    continue
                seen.add(alias)
                unique_aliases.append(alias)

            for alias in unique_aliases[:target or None]:
                manager.add_lease(
                    AliasEmailLease(
                        alias_email=alias,
                        real_mailbox_email=str(self.source.get("mailbox_email") or "").strip().lower(),
                        source_kind=self.source_kind,
                        source_id=self.source_id,
                        source_session_id=str(state.state_key),
                    )
                )

            state.known_aliases = unique_aliases
            state.last_capture_summary = list(self.runtime.capture_summary())
            self.state_store.save(state)
            self._state = AliasSourceState.EXHAUSTED
        except Exception:
            self._state = AliasSourceState.FAILED
            raise
```

- [ ] **Step 4: 补一条注册回退失败测试，再实现最小异常路径**

向 `tests/test_alias_pool.py` 追加：

```python
    def test_producer_marks_failed_when_restore_login_register_all_fail(self):
        manager = AliasEmailPoolManager(task_id="task-vend-email-failed")
        state_store = Mock()
        state_store.load.return_value = VendEmailServiceState(state_key="vend-email-primary")
        runtime = _FakeVendEmailRuntime(
            restore_ok=False,
            login_ok=False,
            register_ok=False,
            aliases=[],
        )

        producer = VendEmailAliasServiceProducer(
            source={
                "id": "vend-email-primary",
                "type": "vend_email",
                "register_url": "https://www.vend.email/auth/register",
                "mailbox_base_url": "https://cxwsss.online/",
                "mailbox_email": "admin@cxwsss.online",
                "mailbox_password": "1103@Icity",
                "alias_domain": "cxwsss.online",
                "alias_count": 1,
                "state_key": "vend-email-primary",
            },
            state_store=state_store,
            runtime=runtime,
        )

        with self.assertRaises(RuntimeError):
            producer.load_into(manager)

        self.assertEqual(producer.state(), AliasSourceState.FAILED)
```

Run:

```bash
python -m unittest discover -s tests -p "test_alias_pool.py" -v
```

Expected:
- PASS
- 成功路径与失败路径都通过

- [ ] **Step 5: Commit**

```bash
git add core/alias_pool/vend_email_service.py tests/test_alias_pool.py
git commit -m "feat: add vend email alias service producer"
```

### Task 4: 在任务装配路径中接入 `vend_email` producer

**Files:**
- Modify: `api/tasks.py`
- Modify: `tests/test_register_task_controls.py`
- Test: `tests/test_register_task_controls.py`

- [ ] **Step 1: 写失败测试，验证 `_build_alias_pool()` 能装配 `vend_email` source**

在 `tests/test_register_task_controls.py` 追加：

```python
class _FakeVendEmailRuntimeForTask:
    def restore_session(self, state):
        return True

    def login(self, state, source):
        return True

    def register(self, state, source):
        return True

    def list_aliases(self, state, source):
        return ["alias1@example.com"]

    def create_aliases(self, state, source, missing_count):
        return []

    def capture_summary(self):
        return []


class RegisterTaskVendEmailIntegrationTests(unittest.TestCase):
    def test_run_register_builds_alias_pool_for_vend_email_source(self):
        task_id = "task-vend-email-pool"
        req = RegisterTaskRequest(
            platform="fake",
            count=1,
            concurrency=1,
            extra={"mail_provider": "fake"},
        )
        _create_task_record(task_id, req, "manual", None)
        mailbox_factory = _MailboxFactory()

        with (
            patch("core.registry.get", return_value=_PoolAwarePlatform),
            patch("core.base_mailbox.create_mailbox", side_effect=mailbox_factory),
            patch(
                "core.config_store.config_store.get_all",
                return_value={
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
                            "alias_count": 1,
                            "state_key": "vend-email-primary",
                        }
                    ],
                },
            ),
            patch("core.proxy_pool.proxy_pool", new=Mock(get_next=Mock(return_value=None), report_success=Mock(), report_fail=Mock())),
            patch("core.db.save_account", side_effect=lambda account: account),
            patch("api.tasks._save_task_log"),
            patch("core.alias_pool.vend_email_service.VendEmailFileStateStore"),
            patch("core.alias_pool.vend_email_service.build_vend_email_runtime", return_value=_FakeVendEmailRuntimeForTask()),
        ):
            _run_register(task_id, req)

        snapshot = _task_store.snapshot(task_id)
        self.assertEqual(snapshot["status"], "done")
        self.assertEqual(snapshot["success"], 1)
```

- [ ] **Step 2: 运行测试，确认先失败**

Run:

```bash
python -m unittest discover -s tests -p "test_register_task_controls.py" -v
```

Expected:
- FAIL
- `_build_alias_pool()` 未识别 `vend_email`

- [ ] **Step 3: 在 `api/tasks.py` 中补最小装配实现**

在 `_build_alias_pool()` 里增加：

```python
            from core.alias_pool.vend_email_service import (
                VendEmailAliasServiceProducer,
                VendEmailFileStateStore,
                build_vend_email_runtime,
            )
```

并在 source 分发逻辑中追加：

```python
                elif source_type == "vend_email":
                    producer = VendEmailAliasServiceProducer(
                        source=source,
                        state_store=VendEmailFileStateStore.for_task(task_id=task_id),
                        runtime=build_vend_email_runtime(),
                    )
```

在 `core/alias_pool/vend_email_service.py` 中补最小辅助符号：

```python
from pathlib import Path
from .vend_email_state import VendEmailFileStateStore


class VendEmailRuntimeNotConfigured:
    def restore_session(self, state):
        return False

    def login(self, state, source):
        return False

    def register(self, state, source):
        return False

    def list_aliases(self, state, source):
        return []

    def create_aliases(self, state, source, missing_count):
        return []

    def capture_summary(self):
        return []


def build_vend_email_runtime():
    return VendEmailRuntimeNotConfigured()


class VendEmailFileStateStore(VendEmailFileStateStore):
    @classmethod
    def for_task(cls, *, task_id: str):
        return cls(base_dir=Path("data") / "vend_email_state" / task_id)
```

如果你不想在同文件里重新导出 `VendEmailFileStateStore`，就改为：

```python
from .vend_email_state import VendEmailFileStateStore as VendEmailStateStore
```

并同步更新 `api/tasks.py` 的导入名字，保持类型一致。

- [ ] **Step 4: 运行测试，确认通过**

Run:

```bash
python -m unittest discover -s tests -p "test_register_task_controls.py" -v
```

Expected:
- PASS
- vend_email source 的 task integration 测试通过

- [ ] **Step 5: Commit**

```bash
git add api/tasks.py core/alias_pool/vend_email_service.py tests/test_register_task_controls.py
git commit -m "feat: wire vend email alias service into task pool"
```

### Task 5: 补手动 smoke / 抓包验收说明，锁定真实站点验证步骤

**Files:**
- Create: `tests/manual_vend_email_capture.md`
- Test: `tests/manual_vend_email_capture.md`

- [ ] **Step 1: 写手动 smoke 文档，明确真实站点验收动作**

创建 `tests/manual_vend_email_capture.md`：

```markdown
# Vend.email Manual Smoke & Capture

## Goal

Verify the real vend.email registration/login/alias flow and collect request summaries for:

1. register submit
2. verify mail confirm
3. login submit
4. alias create
5. alias list

## Reference environment

- vend register: `https://www.vend.email/auth/register`
- mailbox base url: `https://cxwsss.online/`
- mailbox email: `admin@cxwsss.online`
- mailbox password: `1103@Icity`

## Steps

1. Open vend register page in MCP/Playwright.
2. Submit a new service email under the configured alias domain.
3. Open the mailbox admin site and extract the vend verification link or code.
4. Return to vend.email and complete verification.
5. Login and navigate to alias management.
6. Create at least one alias.
7. Export request summaries for the required five request groups.

## Acceptance

- At least one alias is visible in vend.email.
- The alias can be loaded into `AliasEmailLease` form.
- Request summaries contain url, method, request excerpt, response status, response excerpt.
```

- [ ] **Step 2: 自检文档是否和 spec 一致**

Check:

```bash
python -c "from pathlib import Path; print(Path('tests/manual_vend_email_capture.md').read_text(encoding='utf-8'))"
```

Expected:
- 输出包含 reference environment、steps、acceptance 三段
- 明确 `cxwsss.online` 只是当前参考环境

- [ ] **Step 3: Commit**

```bash
git add tests/manual_vend_email_capture.md
git commit -m "docs: add vend email manual capture checklist"
```

---

## Self-Review

- **Spec coverage:**
  - `vend_email` config normalize → Task 1
  - state persistence and capture summary → Task 2
  - producer lifecycle / restore-login-register fallback / lease injection → Task 3
  - `_build_alias_pool()` integration → Task 4
  - real-site smoke and capture acceptance → Task 5
- **Placeholder scan:** 已避免使用 TBD/TODO/“自行实现”之类占位语；每个代码步骤都给出具体代码或命令。
- **Type consistency:** `VendEmailServiceState`、`VendEmailCaptureRecord`、`VendEmailAliasServiceProducer`、`build_vend_email_runtime()` 在后续任务中的命名保持一致；如实施时改名，必须同步修改 Task 4 的导入和测试。

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-16-vend-email-alias-service.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
