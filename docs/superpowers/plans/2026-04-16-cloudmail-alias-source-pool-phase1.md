# CloudMail Alias Source Pool Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 CloudMail 注册链路落地第一阶段的别名邮箱池化架构：引入任务级 alias pool、兼容 static list source、让 `CloudMailMailbox` 消费 `AliasEmailLease`，并在任务启动时完成 pool 初始化与 mailbox 注入。

**Architecture:** 保持平台注册主流程和 CloudMail 收码逻辑不变，只把“别名邮箱来源”从 `CloudMailMailbox._pick_alias_email()` 的 list-only 逻辑，迁移为 task-scoped `AliasEmailPoolManager` + `StaticAliasListProducer`。第一阶段不实现真实站点型 provider，只实现可测试的总池主干、配置归一化、mailbox lease 消费以及任务生命周期接入。

**Tech Stack:** Python, dataclasses, threading, existing FastAPI task runner, unittest + unittest.mock

---

## File Structure

- Create: `core/alias_pool/base.py`
  - 定义 `AliasEmailLease`、producer 协议、状态枚举、pool 相关异常
- Create: `core/alias_pool/config.py`
  - 将旧 CloudMail alias 配置归一化为 phase-1 pool config + static list source config
- Create: `core/alias_pool/manager.py`
  - 实现 `AliasEmailPoolManager`，负责 source 注册、lease 入池、`acquire_alias()`、状态回写、cleanup
- Create: `core/alias_pool/static_list.py`
  - 实现 `StaticAliasListProducer`，把静态 alias 列表装入池中
- Modify: `core/base_mailbox.py`
  - 让 `CloudMailMailbox` 支持从 alias pool 获取 lease，并保留现有 `wait_for_code()`/`get_current_ids()` 行为
- Modify: `api/tasks.py`
  - 在任务启动时初始化 alias pool，并将 pool 上下文注入 mailbox
- Modify: `tests/test_cloudmail_mailbox.py`
  - 把现有 alias list 行为迁移为 pool-aware 断言，并补 lease 消费覆盖
- Modify: `tests/test_register_task_controls.py`
  - 验证任务链路会初始化/清理 alias pool，并保留 mailbox alias metadata 透传
- Create: `tests/test_alias_pool.py`
  - 覆盖 config normalize、static list producer、pool acquire/exhausted/cleanup 等独立单测

---

### Task 1: 建立 Alias Pool 基础类型与 static list 配置归一化

**Files:**
- Create: `core/alias_pool/base.py`
- Create: `core/alias_pool/config.py`
- Test: `tests/test_alias_pool.py`
- Verify against: `core/base_mailbox.py:1097-1123`, `core/base_mailbox.py:1203-1237`

- [ ] **Step 1: 写失败测试，锁定 phase-1 的配置归一化与 lease 结构**

将 `tests/test_alias_pool.py` 创建为以下内容：

```python
import unittest

from core.alias_pool.base import AliasEmailLease, AliasLeaseStatus
from core.alias_pool.config import normalize_cloudmail_alias_pool_config


class AliasPoolConfigTests(unittest.TestCase):
    def test_normalize_legacy_cloudmail_alias_config_builds_static_source(self):
        result = normalize_cloudmail_alias_pool_config(
            {
                "cloudmail_alias_enabled": True,
                "cloudmail_alias_emails": "alias1@example.com\nalias2@example.com",
                "cloudmail_alias_mailbox_email": "real@example.com",
            },
            task_id="task-1",
        )

        self.assertTrue(result["enabled"])
        self.assertEqual(result["task_id"], "task-1")
        self.assertEqual(result["sources"][0]["type"], "static_list")
        self.assertEqual(
            result["sources"][0]["emails"],
            ["alias1@example.com", "alias2@example.com"],
        )
        self.assertEqual(result["sources"][0]["mailbox_email"], "real@example.com")

    def test_normalize_returns_disabled_pool_when_alias_not_enabled(self):
        result = normalize_cloudmail_alias_pool_config({}, task_id="task-2")

        self.assertFalse(result["enabled"])
        self.assertEqual(result["sources"], [])


class AliasEmailLeaseTests(unittest.TestCase):
    def test_alias_email_lease_defaults_to_available_status(self):
        lease = AliasEmailLease(
            alias_email="alias@example.com",
            real_mailbox_email="real@example.com",
            source_kind="static_list",
            source_id="legacy-static",
            source_session_id="static",
        )

        self.assertEqual(lease.status, AliasLeaseStatus.AVAILABLE)
        self.assertEqual(lease.alias_email, "alias@example.com")
        self.assertEqual(lease.real_mailbox_email, "real@example.com")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行新测试，确认它先失败**

Run:

```bash
python -m unittest discover -s tests -p "test_alias_pool.py" -v
```

Expected:
- FAIL
- 失败原因应包含以下一种或多种：
  - `ModuleNotFoundError: No module named 'core.alias_pool.base'`
  - `ModuleNotFoundError: No module named 'core.alias_pool.config'`
  - `AliasEmailLease` 或 `normalize_cloudmail_alias_pool_config` 尚不存在

- [ ] **Step 3: 写最小实现，定义 lease 状态与旧配置归一化函数**

创建 `core/alias_pool/base.py`：

```python
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AliasLeaseStatus(str, Enum):
    AVAILABLE = "available"
    LEASED = "leased"
    CONSUMED = "consumed"
    INVALID = "invalid"


@dataclass
class AliasEmailLease:
    alias_email: str
    real_mailbox_email: str
    source_kind: str
    source_id: str
    source_session_id: str
    status: AliasLeaseStatus = AliasLeaseStatus.AVAILABLE
    metadata: dict[str, Any] = field(default_factory=dict)


class AliasPoolExhaustedError(RuntimeError):
    pass
```

创建 `core/alias_pool/config.py`：

```python
from typing import Any


def _parse_alias_emails(value: Any) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        items = value
    else:
        raw = str(value or "").strip()
        items = raw.splitlines() if raw else []

    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        email = str(item or "").strip().lower()
        if not email or email in seen:
            continue
        seen.add(email)
        result.append(email)
    return result


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def normalize_cloudmail_alias_pool_config(extra: dict[str, Any], *, task_id: str) -> dict[str, Any]:
    payload = dict(extra or {})
    enabled = _parse_bool(payload.get("cloudmail_alias_enabled"))
    emails = _parse_alias_emails(payload.get("cloudmail_alias_emails"))
    mailbox_email = str(payload.get("cloudmail_alias_mailbox_email") or "").strip().lower()

    if not enabled:
        return {
            "enabled": False,
            "task_id": task_id,
            "sources": [],
        }

    return {
        "enabled": True,
        "task_id": task_id,
        "sources": [
            {
                "id": "legacy-static",
                "type": "static_list",
                "emails": emails,
                "mailbox_email": mailbox_email,
            }
        ],
    }
```

- [ ] **Step 4: 运行测试，确认新模块通过**

Run:

```bash
python -m unittest discover -s tests -p "test_alias_pool.py" -v
```

Expected:
- PASS
- 2 tests passed

- [ ] **Step 5: Commit**

```bash
git add core/alias_pool/base.py core/alias_pool/config.py tests/test_alias_pool.py
git commit -m "feat: add alias pool config foundation"
```

### Task 2: 实现 AliasEmailPoolManager 与 StaticAliasListProducer

**Files:**
- Create: `core/alias_pool/manager.py`
- Create: `core/alias_pool/static_list.py`
- Modify: `tests/test_alias_pool.py`
- Test: `tests/test_alias_pool.py`

- [ ] **Step 1: 追加失败测试，覆盖静态来源入池、获取、耗尽与 cleanup**

将以下测试追加到 `tests/test_alias_pool.py`：

```python
from core.alias_pool.base import AliasPoolExhaustedError
from core.alias_pool.manager import AliasEmailPoolManager
from core.alias_pool.static_list import StaticAliasListProducer


class AliasPoolManagerTests(unittest.TestCase):
    def test_static_list_producer_loads_aliases_into_pool_and_acquire_marks_lease(self):
        manager = AliasEmailPoolManager(task_id="task-1")
        producer = StaticAliasListProducer(
            source_id="legacy-static",
            emails=["alias1@example.com", "alias2@example.com"],
            mailbox_email="real@example.com",
        )

        producer.load_into(manager)

        lease = manager.acquire_alias()

        self.assertEqual(lease.alias_email, "alias1@example.com")
        self.assertEqual(lease.real_mailbox_email, "real@example.com")
        self.assertEqual(str(lease.status), "AliasLeaseStatus.LEASED")

    def test_acquire_alias_raises_when_pool_empty(self):
        manager = AliasEmailPoolManager(task_id="task-2")

        with self.assertRaises(AliasPoolExhaustedError):
            manager.acquire_alias()

    def test_cleanup_clears_task_pool(self):
        manager = AliasEmailPoolManager(task_id="task-3")
        producer = StaticAliasListProducer(
            source_id="legacy-static",
            emails=["alias1@example.com"],
            mailbox_email="real@example.com",
        )
        producer.load_into(manager)
        manager.cleanup()

        with self.assertRaises(AliasPoolExhaustedError):
            manager.acquire_alias()
```

- [ ] **Step 2: 运行测试，确认它先失败**

Run:

```bash
python -m unittest discover -s tests -p "test_alias_pool.py" -v
```

Expected:
- FAIL
- 原因应为 `core.alias_pool.manager` / `core.alias_pool.static_list` 尚不存在

- [ ] **Step 3: 写最小实现，保证 static list source 可以作为 pool producer 工作**

创建 `core/alias_pool/manager.py`：

```python
from collections import deque

from .base import AliasEmailLease, AliasLeaseStatus, AliasPoolExhaustedError


class AliasEmailPoolManager:
    def __init__(self, *, task_id: str):
        self.task_id = task_id
        self._available = deque()

    def add_lease(self, lease: AliasEmailLease) -> None:
        self._available.append(lease)

    def acquire_alias(self) -> AliasEmailLease:
        if not self._available:
            raise AliasPoolExhaustedError("CloudMail 别名邮箱池已耗尽")
        lease = self._available.popleft()
        lease.status = AliasLeaseStatus.LEASED
        return lease

    def cleanup(self) -> None:
        self._available.clear()
```

创建 `core/alias_pool/static_list.py`：

```python
from .base import AliasEmailLease


class StaticAliasListProducer:
    def __init__(self, *, source_id: str, emails: list[str], mailbox_email: str):
        self.source_id = source_id
        self.emails = list(emails or [])
        self.mailbox_email = mailbox_email

    def load_into(self, manager) -> None:
        for email in self.emails:
            manager.add_lease(
                AliasEmailLease(
                    alias_email=email,
                    real_mailbox_email=self.mailbox_email,
                    source_kind="static_list",
                    source_id=self.source_id,
                    source_session_id="static",
                )
            )
```

- [ ] **Step 4: 修正测试中的状态断言，使其校验枚举值而不是 repr**

将 `tests/test_alias_pool.py` 中的这行：

```python
self.assertEqual(str(lease.status), "AliasLeaseStatus.LEASED")
```

改为：

```python
self.assertEqual(lease.status, AliasLeaseStatus.LEASED)
```

- [ ] **Step 5: 运行测试，确认 pool 基础行为通过**

Run:

```bash
python -m unittest discover -s tests -p "test_alias_pool.py" -v
```

Expected:
- PASS
- 5 tests passed

- [ ] **Step 6: Commit**

```bash
git add core/alias_pool/manager.py core/alias_pool/static_list.py tests/test_alias_pool.py
git commit -m "feat: add static alias pool manager"
```

### Task 3: 让 CloudMailMailbox 从 AliasEmailLease 消费邮箱

**Files:**
- Modify: `core/base_mailbox.py:1097-1241`
- Modify: `tests/test_cloudmail_mailbox.py`
- Test: `tests/test_cloudmail_mailbox.py`

- [ ] **Step 1: 追加失败测试，要求 mailbox 优先消费 task alias pool 的 lease**

将以下测试追加到 `tests/test_cloudmail_mailbox.py`：

```python
from core.alias_pool.base import AliasEmailLease, AliasLeaseStatus
from core.alias_pool.manager import AliasEmailPoolManager


    def test_get_email_prefers_task_alias_pool_lease_when_present(self):
        mailbox = create_mailbox(
            "cloudmail",
            extra={
                "cloudmail_api_base": "https://cloudmail.example.com",
                "cloudmail_admin_password": "secret",
                "cloudmail_domain": "mail.example.com",
                "cloudmail_alias_enabled": "1",
                "cloudmail_alias_emails": "legacy@example.com",
                "cloudmail_alias_mailbox_email": "legacy-real@example.com",
            },
        )
        assert isinstance(mailbox, CloudMailMailbox)
        mailbox._task_alias_pool = AliasEmailPoolManager(task_id="task-1")
        mailbox._task_alias_pool.add_lease(
            AliasEmailLease(
                alias_email="pooled@example.com",
                real_mailbox_email="real@example.com",
                source_kind="static_list",
                source_id="legacy-static",
                source_session_id="static",
            )
        )

        account = mailbox.get_email()

        self.assertEqual(account.email, "pooled@example.com")
        self.assertEqual(account.account_id, "real@example.com")
        self.assertEqual(mailbox._last_alias_lease.status, AliasLeaseStatus.LEASED)
```

- [ ] **Step 2: 运行 cloudmail mailbox 测试，确认新测试先失败**

Run:

```bash
python -m unittest discover -s tests -p "test_cloudmail_mailbox.py" -v
```

Expected:
- FAIL
- 当前 `CloudMailMailbox.get_email()` 仍然只走 `_pick_alias_email()`，不会读取 `_task_alias_pool`

- [ ] **Step 3: 在 CloudMailMailbox 中实现 lease 优先消费，但保留旧逻辑回退**

在 `core/base_mailbox.py` 中做以下最小修改：

1. 在 `__init__()` 中新增两行：

```python
self._task_alias_pool = None
self._last_alias_lease = None
```

2. 在 `CloudMailMailbox` 类中新增方法：

```python
    def _consume_alias_lease(self):
        pool = getattr(self, "_task_alias_pool", None)
        if pool is None:
            return None
        lease = pool.acquire_alias()
        self._last_alias_lease = lease
        return lease
```

3. 将当前 `get_email()`：

```python
        alias_email = self._pick_alias_email()
        mailbox_email = self._resolve_mailbox_email(alias_email)
```

改为：

```python
        lease = self._consume_alias_lease()
        if lease is not None:
            alias_email = str(lease.alias_email or "").strip()
            mailbox_email = str(lease.real_mailbox_email or "").strip()
        else:
            alias_email = self._pick_alias_email()
            mailbox_email = self._resolve_mailbox_email(alias_email)
```

保持 `MailboxAccount` 构建和现有日志逻辑不变。

- [ ] **Step 4: 运行 mailbox 测试，确认 lease 路径与旧路径都通过**

Run:

```bash
python -m unittest discover -s tests -p "test_cloudmail_mailbox.py" -v
```

Expected:
- PASS
- 现有 alias list 测试继续通过
- 新 lease 优先测试通过

- [ ] **Step 5: Commit**

```bash
git add core/base_mailbox.py tests/test_cloudmail_mailbox.py
git commit -m "feat: let cloudmail mailbox consume alias leases"
```

### Task 4: 在任务启动时接入 alias pool 生命周期

**Files:**
- Modify: `api/tasks.py:160-203`
- Modify: `api/tasks.py:397-402`
- Modify: `tests/test_register_task_controls.py`
- Test: `tests/test_register_task_controls.py`

- [ ] **Step 1: 追加失败测试，要求 _run_register 初始化并注入 task alias pool**

将以下测试追加到 `tests/test_register_task_controls.py`：

```python
from core.alias_pool.manager import AliasEmailPoolManager


class _FakePoolAwareMailbox(_FakeAliasMailbox):
    def __init__(self):
        super().__init__()
        self._task_alias_pool = None


    def get_email(self) -> MailboxAccount:
        assert isinstance(self._task_alias_pool, AliasEmailPoolManager)
        return super().get_email()


class RegisterTaskControlFlowTests(unittest.TestCase):
    def test_run_register_injects_task_alias_pool_into_mailbox(self):
        task_id = "task-pool-aware-mailbox"
        req = self._build_request(
            extra={
                "mail_provider": "cloudmail",
                "cloudmail_alias_enabled": True,
                "cloudmail_alias_emails": "alias@example.com",
                "cloudmail_alias_mailbox_email": "real@example.com",
            }
        )
        _create_task_record(task_id, req, "manual", None)

        with (
            patch("core.registry.get", return_value=_FakePlatform),
            patch("core.base_mailbox.create_mailbox", return_value=_FakePoolAwareMailbox()),
            patch("core.db.save_account", side_effect=lambda account: account),
            patch("api.tasks._save_task_log"),
        ):
            _run_register(task_id, req)

        snapshot = _task_store.snapshot(task_id)
        self.assertEqual(snapshot["status"], "done")
```

- [ ] **Step 2: 运行任务控制测试，确认新测试先失败**

Run:

```bash
python -m unittest discover -s tests -p "test_register_task_controls.py" -v
```

Expected:
- FAIL
- `_FakePoolAwareMailbox.get_email()` 中的 `assert isinstance(self._task_alias_pool, AliasEmailPoolManager)` 失败

- [ ] **Step 3: 在 _run_register 中初始化 pool，并注入 mailbox**

在 `api/tasks.py` 中新增导入并最小接线：

1. 在 `_run_register()` 里、`_build_mailbox()` 之前，新增 helper：

```python
        def _build_alias_pool(extra: dict):
            from core.alias_pool.config import normalize_cloudmail_alias_pool_config
            from core.alias_pool.manager import AliasEmailPoolManager
            from core.alias_pool.static_list import StaticAliasListProducer

            pool_config = normalize_cloudmail_alias_pool_config(extra, task_id=task_id)
            if not pool_config.get("enabled"):
                return None

            manager = AliasEmailPoolManager(task_id=task_id)
            for source in pool_config.get("sources") or []:
                if source.get("type") != "static_list":
                    continue
                StaticAliasListProducer(
                    source_id=source["id"],
                    emails=source.get("emails") or [],
                    mailbox_email=source.get("mailbox_email") or "",
                ).load_into(manager)
            return manager
```

2. 在 `_do_one()` 中 `merged_extra` 计算后、`_config = RegisterConfig(...)` 之前新增：

```python
                alias_pool = _build_alias_pool(merged_extra)
```

3. 在 `_mailbox = _build_mailbox(_proxy)` 后新增：

```python
                if hasattr(_mailbox, "_task_alias_pool"):
                    _mailbox._task_alias_pool = alias_pool
```

4. 在结尾 cleanup 处，把：

```python
        from core.base_mailbox import CloudMailMailbox

        CloudMailMailbox.release_alias_pool(task_id)
```

替换为：

```python
        from core.base_mailbox import CloudMailMailbox

        CloudMailMailbox.release_alias_pool(task_id)
```

本阶段保留这段不动；pool manager 为 task-scoped 对象，无需额外全局 cleanup。这里的目标是先保证注入，而不是引入跨 attempt 的共享注册中心。

- [ ] **Step 4: 运行任务控制测试，确认 pool 注入不破坏原有链路**

Run:

```bash
python -m unittest discover -s tests -p "test_register_task_controls.py" -v
```

Expected:
- PASS
- 原有 alias metadata 测试继续通过
- 新的 pool-aware mailbox 测试通过

- [ ] **Step 5: Commit**

```bash
git add api/tasks.py tests/test_register_task_controls.py
git commit -m "feat: initialize alias pool for register tasks"
```

### Task 5: 统一回归并补 phase-1 文档一致性检查

**Files:**
- Verify: `tests/test_alias_pool.py`
- Verify: `tests/test_cloudmail_mailbox.py`
- Verify: `tests/test_register_task_controls.py`
- Review: `docs/superpowers/specs/2026-04-16-cloudmail-alias-source-pool-design.md`

- [ ] **Step 1: 运行 alias pool 独立测试**

Run:

```bash
python -m unittest discover -s tests -p "test_alias_pool.py" -v
```

Expected:
- PASS

- [ ] **Step 2: 运行 cloudmail mailbox 回归测试**

Run:

```bash
python -m unittest discover -s tests -p "test_cloudmail_mailbox.py" -v
```

Expected:
- PASS

- [ ] **Step 3: 运行 register task control 回归测试**

Run:

```bash
python -m unittest discover -s tests -p "test_register_task_controls.py" -v
```

Expected:
- PASS

- [ ] **Step 4: 对照 spec 检查 phase-1 范围没有超出**

确认以下几点全部满足：

- 只实现 `StaticAliasListProducer`
- 没有引入真实站点 provider 自动化
- `CloudMailMailbox.wait_for_code()` 逻辑未被重写
- `api/tasks.py` 只做最小注入，不引入复杂全局池共享
- 新测试覆盖了 config normalize / pool consume / mailbox lease / task injection

Expected: 满足 spec 的第一阶段闭环，不提前实现 phase-2 的异步 producer 细节。

- [ ] **Step 5: Commit**

```bash
git add core/alias_pool api/tasks.py core/base_mailbox.py tests/test_alias_pool.py tests/test_cloudmail_mailbox.py tests/test_register_task_controls.py
git commit -m "feat: add phase one cloudmail alias pool support"
```
