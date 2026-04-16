# CloudMail Alias Source Pool Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在已完成的 phase-1 基础上，为 CloudMail alias pool 引入可扩展的 source producer 抽象、基础 source 状态/容量控制，以及面向未来 alias service producer 的接口骨架，但不实现真实站点自动化。

**Architecture:** 保持 phase-1 已落地的 task-scoped pool、static list source、mailbox lease consume、task injection 不变。phase-2 只在 `core/alias_pool/` 内补齐“多 source producer”最小抽象与状态追踪能力，让 pool manager 能识别 producer 状态、按 source 统计 available 数量、并为未来 alias service producer 预留 dry-run 级基类/协议；本阶段不接浏览器、验证码验证、cookie/token 登录，也不改前端。

**Tech Stack:** Python, dataclasses, enum, unittest + unittest.mock, existing FastAPI task runner integration from phase-1

---

## File Structure

- Modify: `core/alias_pool/base.py`
  - 扩展 producer 状态枚举、producer 协议/基类、source 级配置与异常类型
- Modify: `core/alias_pool/manager.py`
  - 增加 producer 注册、source available 统计、按状态判断池是否仍有活跃来源
- Modify: `core/alias_pool/static_list.py`
  - 让 `StaticAliasListProducer` 实现统一 producer 接口，并暴露 source state
- Create: `core/alias_pool/service_base.py`
  - 定义未来 alias service producer/session 的最小抽象骨架，但只做不可直接运行的接口/空实现
- Modify: `core/alias_pool/config.py`
  - 扩展新配置结构的归一化入口，支持读取 `sources` 列表，同时继续兼容旧 static list 字段
- Modify: `api/tasks.py`
  - 将当前“直接遍历 static_list 配置装池”改为通过 producer 抽象装配，但仍只实例化 static list producer
- Modify: `tests/test_alias_pool.py`
  - 新增 producer state、source available 统计、new-config normalize、service-base 抽象行为的测试
- Modify: `tests/test_register_task_controls.py`
  - 保证任务注入路径在切到 producer 抽象后仍保持 phase-1 行为

---

### Task 1: 为 alias pool 定义 producer 状态与统一协议

**Files:**
- Modify: `core/alias_pool/base.py`
- Modify: `tests/test_alias_pool.py`
- Test: `tests/test_alias_pool.py`

- [ ] **Step 1: 先写失败测试，锁定 producer 状态枚举和统一接口的最小契约**

在 `tests/test_alias_pool.py` 末尾追加以下内容：

```python
from core.alias_pool.base import AliasSourceState


class AliasProducerContractTests(unittest.TestCase):
    def test_alias_source_state_exposes_expected_lifecycle_values(self):
        self.assertEqual(AliasSourceState.IDLE.value, "idle")
        self.assertEqual(AliasSourceState.ACTIVE.value, "active")
        self.assertEqual(AliasSourceState.EXHAUSTED.value, "exhausted")
        self.assertEqual(AliasSourceState.FAILED.value, "failed")
```

- [ ] **Step 2: 运行测试确认先失败**

Run:

```bash
python -m unittest discover -s tests -p "test_alias_pool.py" -v
```

Expected:
- FAIL
- `ImportError` 或 `AttributeError` 指向 `AliasSourceState` 尚不存在

- [ ] **Step 3: 写最小实现，只补 phase-2 需要的 producer 状态与基础协议**

在 `core/alias_pool/base.py` 中增加：

```python
from typing import Any, Protocol


class AliasSourceState(str, Enum):
    IDLE = "idle"
    ACTIVE = "active"
    EXHAUSTED = "exhausted"
    FAILED = "failed"


class AliasSourceProducer(Protocol):
    source_id: str
    source_kind: str

    def load_into(self, manager: Any) -> None:
        ...

    def state(self) -> AliasSourceState:
        ...
```
```

保持现有 `AliasEmailLease` / `AliasLeaseStatus` / `AliasPoolExhaustedError` 不变。

- [ ] **Step 4: 运行测试确认通过**

Run:

```bash
python -m unittest discover -s tests -p "test_alias_pool.py" -v
```

Expected:
- PASS
- 新的 producer 状态测试通过

- [ ] **Step 5: Commit**

```bash
git add core/alias_pool/base.py tests/test_alias_pool.py
git commit -m "feat: add alias source producer contract"
```

### Task 2: 让 pool manager 跟踪 source available 数量与活跃 producer 状态

**Files:**
- Modify: `core/alias_pool/manager.py`
- Modify: `tests/test_alias_pool.py`
- Test: `tests/test_alias_pool.py`

- [ ] **Step 1: 写失败测试，覆盖 source available 统计与活跃来源判断**

向 `tests/test_alias_pool.py` 追加：

```python
class AliasPoolManagerSourceStateTests(unittest.TestCase):
    def test_manager_counts_available_aliases_per_source(self):
        manager = AliasEmailPoolManager(task_id="task-source-count")
        manager.add_lease(
            AliasEmailLease(
                alias_email="a1@example.com",
                real_mailbox_email="real@example.com",
                source_kind="static_list",
                source_id="source-a",
                source_session_id="static",
            )
        )
        manager.add_lease(
            AliasEmailLease(
                alias_email="a2@example.com",
                real_mailbox_email="real@example.com",
                source_kind="static_list",
                source_id="source-a",
                source_session_id="static",
            )
        )

        self.assertEqual(manager.available_count_for_source("source-a"), 2)

    def test_manager_reports_no_live_sources_when_all_registered_sources_are_failed(self):
        manager = AliasEmailPoolManager(task_id="task-source-state")
        producer = mock.Mock()
        producer.source_id = "source-a"
        producer.state.return_value = AliasSourceState.FAILED
        manager.register_source(producer)

        self.assertFalse(manager.has_live_sources())
```

- [ ] **Step 2: 运行测试确认先失败**

Run:

```bash
python -m unittest discover -s tests -p "test_alias_pool.py" -v
```

Expected:
- FAIL
- `available_count_for_source` / `register_source` / `has_live_sources` 尚不存在

- [ ] **Step 3: 在 manager 中实现最小状态追踪能力**

在 `core/alias_pool/manager.py` 中增加：

```python
class AliasEmailPoolManager:
    def __init__(self, *, task_id: str):
        self.task_id = task_id
        self._available = deque()
        self._sources = {}

    def register_source(self, producer) -> None:
        self._sources[producer.source_id] = producer

    def available_count_for_source(self, source_id: str) -> int:
        return sum(1 for lease in self._available if lease.source_id == source_id)

    def has_live_sources(self) -> bool:
        if not self._sources:
            return False
        return any(
            producer.state() in {AliasSourceState.IDLE, AliasSourceState.ACTIVE}
            for producer in self._sources.values()
        )
```

保留现有 `add_lease()` / `acquire_alias()` / `cleanup()` 行为。

- [ ] **Step 4: 运行测试确认通过**

Run:

```bash
python -m unittest discover -s tests -p "test_alias_pool.py" -v
```

Expected:
- PASS

- [ ] **Step 5: Commit**

```bash
git add core/alias_pool/manager.py tests/test_alias_pool.py
git commit -m "feat: track alias source state in pool manager"
```

### Task 3: 将 StaticAliasListProducer 升级为统一 producer，并暴露状态

**Files:**
- Modify: `core/alias_pool/static_list.py`
- Modify: `tests/test_alias_pool.py`
- Test: `tests/test_alias_pool.py`

- [ ] **Step 1: 写失败测试，要求 static list producer 暴露 source_kind 和 exhausted 状态**

向 `tests/test_alias_pool.py` 追加：

```python
class StaticAliasListProducerStateTests(unittest.TestCase):
    def test_static_list_producer_reports_exhausted_after_loading_all_aliases(self):
        manager = AliasEmailPoolManager(task_id="task-static-state")
        producer = StaticAliasListProducer(
            source_id="legacy-static",
            emails=["alias1@example.com"],
            mailbox_email="real@example.com",
        )

        self.assertEqual(producer.source_kind, "static_list")
        self.assertEqual(producer.state(), AliasSourceState.IDLE)

        producer.load_into(manager)

        self.assertEqual(producer.state(), AliasSourceState.EXHAUSTED)
```

- [ ] **Step 2: 运行测试确认先失败**

Run:

```bash
python -m unittest discover -s tests -p "test_alias_pool.py" -v
```

Expected:
- FAIL
- `source_kind` / `state()` / exhausted 状态行为尚不存在

- [ ] **Step 3: 最小实现 producer 状态，不加入 async 行为**

在 `core/alias_pool/static_list.py` 中：

```python
from .base import AliasEmailLease, AliasSourceState


class StaticAliasListProducer:
    source_kind = "static_list"

    def __init__(self, *, source_id: str, emails: list[str], mailbox_email: str):
        self.source_id = source_id
        self.emails = list(emails or [])
        self.mailbox_email = mailbox_email
        self._state = AliasSourceState.IDLE

    def state(self) -> AliasSourceState:
        return self._state

    def load_into(self, manager: AliasEmailPoolManager) -> None:
        self._state = AliasSourceState.ACTIVE
        for email in self.emails:
            manager.add_lease(...)
        self._state = AliasSourceState.EXHAUSTED
```

不要加入线程、重试或延迟补货。

- [ ] **Step 4: 运行测试确认通过**

Run:

```bash
python -m unittest discover -s tests -p "test_alias_pool.py" -v
```

Expected:
- PASS

- [ ] **Step 5: Commit**

```bash
git add core/alias_pool/static_list.py tests/test_alias_pool.py
git commit -m "feat: expose static alias producer state"
```

### Task 4: 为 future alias service producer 定义不可执行骨架

**Files:**
- Create: `core/alias_pool/service_base.py`
- Modify: `tests/test_alias_pool.py`
- Test: `tests/test_alias_pool.py`

- [ ] **Step 1: 写失败测试，要求 service base 只定义接口骨架、不允许直接使用**

向 `tests/test_alias_pool.py` 追加：

```python
from core.alias_pool.service_base import AliasServiceProducerBase


class AliasServiceProducerBaseTests(unittest.TestCase):
    def test_service_base_defaults_to_idle_and_requires_subclass_load(self):
        producer = AliasServiceProducerBase(source_id="service-a")

        self.assertEqual(producer.source_kind, "alias_service")
        self.assertEqual(producer.state(), AliasSourceState.IDLE)
        with self.assertRaises(NotImplementedError):
            producer.load_into(AliasEmailPoolManager(task_id="task-service-base"))
```

- [ ] **Step 2: 运行测试确认先失败**

Run:

```bash
python -m unittest discover -s tests -p "test_alias_pool.py" -v
```

Expected:
- FAIL
- `core.alias_pool.service_base` 尚不存在

- [ ] **Step 3: 创建最小 service base 骨架，不接站点自动化**

创建 `core/alias_pool/service_base.py`：

```python
from .base import AliasSourceState
from .manager import AliasEmailPoolManager


class AliasServiceProducerBase:
    source_kind = "alias_service"

    def __init__(self, *, source_id: str):
        self.source_id = source_id
        self._state = AliasSourceState.IDLE

    def state(self) -> AliasSourceState:
        return self._state

    def load_into(self, manager: AliasEmailPoolManager) -> None:
        raise NotImplementedError("Alias service producer must implement load_into")
```

不要加入浏览器、session、token、cookie、验证邮件处理。

- [ ] **Step 4: 运行测试确认通过**

Run:

```bash
python -m unittest discover -s tests -p "test_alias_pool.py" -v
```

Expected:
- PASS

- [ ] **Step 5: Commit**

```bash
git add core/alias_pool/service_base.py tests/test_alias_pool.py
git commit -m "feat: add alias service producer base"
```

### Task 5: 扩展 config normalize 和 task injection，使其走统一 producer 装配路径

**Files:**
- Modify: `core/alias_pool/config.py`
- Modify: `api/tasks.py`
- Modify: `tests/test_alias_pool.py`
- Modify: `tests/test_register_task_controls.py`
- Test: `tests/test_alias_pool.py`
- Test: `tests/test_register_task_controls.py`

- [ ] **Step 1: 写失败测试，锁定新 config 结构和 producer 装配路径**

在 `tests/test_alias_pool.py` 中追加：

```python
class AliasPoolConfigV2Tests(unittest.TestCase):
    def test_normalize_accepts_explicit_sources_structure(self):
        result = normalize_cloudmail_alias_pool_config(
            {
                "cloudmail_alias_enabled": True,
                "sources": [
                    {
                        "id": "legacy-static",
                        "type": "static_list",
                        "emails": ["alias1@example.com"],
                        "mailbox_email": "real@example.com",
                    }
                ],
            },
            task_id="task-v2",
        )

        self.assertEqual(result["sources"][0]["type"], "static_list")
        self.assertEqual(result["sources"][0]["emails"], ["alias1@example.com"])
```

在 `tests/test_register_task_controls.py` 中追加：

```python
    def test_run_register_builds_task_pool_via_registered_static_producer_path(self):
        task_id = "task-static-producer-path"
        req = self._build_request(
            extra={
                "mail_provider": "cloudmail",
                "cloudmail_alias_enabled": True,
                "sources": [
                    {
                        "id": "legacy-static",
                        "type": "static_list",
                        "emails": ["alias1@example.com", "alias2@example.com"],
                        "mailbox_email": "real@example.com",
                    }
                ],
            },
            count=2,
            concurrency=1,
        )
        _create_task_record(task_id, req, "manual", None)
        mailbox_factory = _MailboxFactory()
        saved_accounts = []

        with (
            patch("core.registry.get", return_value=_PoolAwarePlatform),
            patch("core.base_mailbox.create_mailbox", side_effect=mailbox_factory),
            patch("core.config_store.config_store.get_all", return_value={}),
            patch("core.proxy_pool.proxy_pool", new=self._proxy_pool_stub()),
            patch("core.db.save_account", side_effect=lambda account: saved_accounts.append(account) or account),
            patch("api.tasks._save_task_log"),
        ):
            _run_register(task_id, req)

        self.assertEqual([account.email for account in saved_accounts], ["alias1@example.com", "alias2@example.com"])
```

- [ ] **Step 2: 运行测试确认先失败**

Run:

```bash
python -m unittest discover -s tests -p "test_alias_pool.py" -v
python -m unittest discover -s tests -p "test_register_task_controls.py" -v
```

Expected:
- FAIL
- config 还不能消费 `sources` 结构，task injection 还没切到统一 producer 装配路径

- [ ] **Step 3: 最小实现“新 config + producer 装配”，但仍只实例化 static list producer**

在 `core/alias_pool/config.py` 中扩展 `normalize_cloudmail_alias_pool_config(...)`：

- 如果 `payload` 中有 `sources` 列表，则直接标准化其中的 `static_list` 条目
- 否则继续保留旧字段映射逻辑

在 `api/tasks.py` 的 `_build_alias_pool()` 中改为：

```python
            manager = AliasEmailPoolManager(task_id=task_id)
            for source in pool_config.get("sources", []):
                if source.get("type") != "static_list":
                    continue
                producer = StaticAliasListProducer(...)
                manager.register_source(producer)
                producer.load_into(manager)
            return manager
```

注意：
- 本阶段仍然只识别 `static_list`
- 其他 source type 直接忽略，不抛复杂错误

- [ ] **Step 4: 运行测试确认通过**

Run:

```bash
python -m unittest discover -s tests -p "test_alias_pool.py" -v
python -m unittest discover -s tests -p "test_register_task_controls.py" -v
```

Expected:
- PASS

- [ ] **Step 5: Commit**

```bash
git add core/alias_pool/config.py api/tasks.py tests/test_alias_pool.py tests/test_register_task_controls.py
git commit -m "feat: route alias pool setup through source producers"
```

### Task 6: 统一回归并确认 phase-2 仍未越过真实 provider 边界

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

- [ ] **Step 4: 对照 spec 检查 phase-2 范围没有越过真实 provider / browser 自动化边界**

确认以下几点全部满足：

- 只增加了 producer 抽象、source 状态、service base 骨架
- 没有真实 alias service 站点自动化实现
- 没有浏览器、cookie、token、验证邮件点击流程代码
- `api/tasks.py` 仍然只实例化 `StaticAliasListProducer`
- `core/alias_pool/service_base.py` 只是不允许直接运行的接口骨架

Expected: phase-2 为未来多 source / alias service 扩展搭好抽象，但没有提前落地真实 provider 行为。

- [ ] **Step 5: Commit**

```bash
git add core/alias_pool api/tasks.py tests/test_alias_pool.py tests/test_cloudmail_mailbox.py tests/test_register_task_controls.py
git commit -m "feat: add phase two alias source producer abstractions"
```
