# CloudMail Simple Generator Producer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 CloudMail alias pool 增加一个最小可用的 `simple_generator` source type，按固定前缀/后缀与随机字母数字中段生成 alias，并通过现有 producer 装配链路注入任务级 alias pool。

**Architecture:** 保持当前 phase-2 已有的 `AliasEmailPoolManager`、`AliasEmailLease`、`StaticAliasListProducer`、`AliasServiceProducerBase` 与 `CloudMailMailbox` 消费流程不变。本次只新增一个轻量 `SimpleAliasGeneratorProducer`，扩展 config normalize 识别 `simple_generator`，再让 `api/tasks.py::_build_alias_pool()` 能实例化它。实现必须遵守 TDD：先写失败测试，再写最小代码让测试通过。

**Tech Stack:** Python, random, string, dataclasses-based alias lease model, unittest + unittest.mock, FastAPI task assembly path already in repo

---

## File Structure

- Create: `core/alias_pool/simple_generator.py`
  - 定义 `SimpleAliasGeneratorProducer`，负责根据配置批量生成 alias lease 并装入 pool
- Modify: `core/alias_pool/config.py`
  - 扩展 `_normalize_sources()`，支持 `simple_generator` 配置项归一化
- Modify: `api/tasks.py`
  - 在 `_build_alias_pool()` 中识别 `simple_generator` 并实例化对应 producer
- Modify: `tests/test_alias_pool.py`
  - 增加 config normalize、producer 生成行为、去重与 lease 字段契约测试
- Modify: `tests/test_register_task_controls.py`
  - 仅在现有覆盖不足时，补 task injection 路径测试，验证 `_build_alias_pool()` 能实际装载 `simple_generator`

---

### Task 1: 扩展 alias pool config，支持 `simple_generator` source 归一化

**Files:**
- Modify: `core/alias_pool/config.py`
- Modify: `tests/test_alias_pool.py`
- Test: `tests/test_alias_pool.py`

- [ ] **Step 1: 写失败测试，锁定 `simple_generator` 配置归一化输出**

在 `tests/test_alias_pool.py` 的 `AliasPoolConfigV2Tests` 中追加：

```python
    def test_normalize_accepts_simple_generator_source(self):
        result = normalize_cloudmail_alias_pool_config(
            {
                "cloudmail_alias_enabled": True,
                "sources": [
                    {
                        "id": "simple-1",
                        "type": "simple_generator",
                        "prefix": "msiabc.",
                        "suffix": "@manyme.com",
                        "mailbox_email": "real@example.com",
                        "count": 5,
                        "middle_length_min": 3,
                        "middle_length_max": 6,
                    }
                ],
            },
            task_id="task-simple-generator",
        )

        self.assertEqual(
            result["sources"],
            [
                {
                    "id": "simple-1",
                    "type": "simple_generator",
                    "prefix": "msiabc.",
                    "suffix": "@manyme.com",
                    "mailbox_email": "real@example.com",
                    "count": 5,
                    "middle_length_min": 3,
                    "middle_length_max": 6,
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
- `result["sources"]` 仍为空或过滤掉 `simple_generator`

- [ ] **Step 3: 在 `core/alias_pool/config.py` 中补最小归一化实现**

将 `_normalize_sources()` 从“只接受 `static_list`”改成同时支持 `simple_generator`。最小实现形状应类似：

```python
def _parse_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_sources(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []

    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            continue

        source_type = str(item.get("type") or "").strip()
        source_id = str(item.get("id") or f"source-{index + 1}").strip() or f"source-{index + 1}"

        if source_type == "static_list":
            normalized.append(
                {
                    "id": source_id,
                    "type": "static_list",
                    "emails": _parse_alias_emails(item.get("emails")),
                    "mailbox_email": str(item.get("mailbox_email") or "").strip().lower(),
                }
            )
            continue

        if source_type == "simple_generator":
            min_length = _parse_int(item.get("middle_length_min"), 3)
            max_length = _parse_int(item.get("middle_length_max"), 6)
            if min_length <= 0:
                min_length = 3
            if max_length < min_length:
                max_length = min_length

            normalized.append(
                {
                    "id": source_id,
                    "type": "simple_generator",
                    "prefix": str(item.get("prefix") or "").strip(),
                    "suffix": str(item.get("suffix") or "").strip().lower(),
                    "mailbox_email": str(item.get("mailbox_email") or "").strip().lower(),
                    "count": max(_parse_int(item.get("count"), 0), 0),
                    "middle_length_min": min_length,
                    "middle_length_max": max_length,
                }
            )
```

保持 `normalize_cloudmail_alias_pool_config()` 的旧字段兼容逻辑不变。

- [ ] **Step 4: 运行测试，确认通过**

Run:

```bash
python -m unittest discover -s tests -p "test_alias_pool.py" -v
```

Expected:
- PASS
- 新的 `simple_generator` normalize 测试通过

- [ ] **Step 5: Commit**

```bash
git add core/alias_pool/config.py tests/test_alias_pool.py
git commit -m "feat: support simple generator alias source config"
```

### Task 2: 新增 `SimpleAliasGeneratorProducer`，按规则生成 alias lease

**Files:**
- Create: `core/alias_pool/simple_generator.py`
- Modify: `tests/test_alias_pool.py`
- Test: `tests/test_alias_pool.py`

- [ ] **Step 1: 写失败测试，锁定 producer 状态与 alias 生成契约**

在 `tests/test_alias_pool.py` 追加：

```python
from core.alias_pool.simple_generator import SimpleAliasGeneratorProducer


class SimpleAliasGeneratorProducerTests(unittest.TestCase):
    def test_simple_generator_loads_generated_aliases_into_pool(self):
        manager = AliasEmailPoolManager(task_id="task-simple-generator-load")
        producer = SimpleAliasGeneratorProducer(
            source_id="simple-1",
            prefix="msiabc.",
            suffix="@manyme.com",
            mailbox_email="real@example.com",
            count=3,
            middle_length_min=3,
            middle_length_max=3,
        )

        self.assertEqual(producer.source_kind, "simple_generator")
        self.assertEqual(producer.state(), AliasSourceState.IDLE)

        producer.load_into(manager)

        self.assertEqual(producer.state(), AliasSourceState.EXHAUSTED)

        leases = [manager.acquire_alias(), manager.acquire_alias(), manager.acquire_alias()]
        self.assertEqual(len(leases), 3)
        self.assertEqual([lease.source_kind for lease in leases], ["simple_generator"] * 3)
        self.assertEqual([lease.source_id for lease in leases], ["simple-1"] * 3)
        self.assertEqual([lease.real_mailbox_email for lease in leases], ["real@example.com"] * 3)

        for lease in leases:
            self.assertTrue(lease.alias_email.startswith("msiabc."))
            self.assertTrue(lease.alias_email.endswith("@manyme.com"))
            middle = lease.alias_email[len("msiabc.") : -len("@manyme.com")]
            self.assertEqual(len(middle), 3)
            self.assertRegex(middle, r"^[a-z0-9]+$")
```

- [ ] **Step 2: 运行测试，确认先失败**

Run:

```bash
python -m unittest discover -s tests -p "test_alias_pool.py" -v
```

Expected:
- FAIL
- `ModuleNotFoundError` 指向 `core.alias_pool.simple_generator`

- [ ] **Step 3: 写最小 producer 实现，让契约测试通过**

创建 `core/alias_pool/simple_generator.py`：

```python
import random
import string

from .base import AliasEmailLease, AliasSourceState
from .manager import AliasEmailPoolManager


class SimpleAliasGeneratorProducer:
    source_kind = "simple_generator"
    _ALPHABET = string.ascii_lowercase + string.digits

    def __init__(
        self,
        *,
        source_id: str,
        prefix: str,
        suffix: str,
        mailbox_email: str,
        count: int,
        middle_length_min: int,
        middle_length_max: int,
    ):
        self.source_id = source_id
        self.prefix = prefix
        self.suffix = suffix
        self.mailbox_email = mailbox_email
        self.count = count
        self.middle_length_min = middle_length_min
        self.middle_length_max = middle_length_max
        self._state = AliasSourceState.IDLE

    def state(self) -> AliasSourceState:
        return self._state

    def _generate_alias_email(self) -> str:
        middle_length = random.randint(self.middle_length_min, self.middle_length_max)
        middle = "".join(random.choices(self._ALPHABET, k=middle_length))
        return f"{self.prefix}{middle}{self.suffix}"

    def load_into(self, manager: AliasEmailPoolManager) -> None:
        self._state = AliasSourceState.ACTIVE
        try:
            seen: set[str] = set()
            while len(seen) < self.count:
                alias_email = self._generate_alias_email()
                if alias_email in seen:
                    continue
                seen.add(alias_email)
                manager.add_lease(
                    AliasEmailLease(
                        alias_email=alias_email,
                        real_mailbox_email=self.mailbox_email,
                        source_kind=self.source_kind,
                        source_id=self.source_id,
                        source_session_id="simple-generator",
                    )
                )
            self._state = AliasSourceState.EXHAUSTED
        except Exception:
            self._state = AliasSourceState.FAILED
            raise
```

- [ ] **Step 4: 运行测试，确认通过**

Run:

```bash
python -m unittest discover -s tests -p "test_alias_pool.py" -v
```

Expected:
- PASS
- 新 producer 契约测试通过

- [ ] **Step 5: Commit**

```bash
git add core/alias_pool/simple_generator.py tests/test_alias_pool.py
git commit -m "feat: add simple generator alias producer"
```

### Task 3: 补充去重测试，固定单次装载内不产生重复 alias

**Files:**
- Modify: `tests/test_alias_pool.py`
- Modify: `core/alias_pool/simple_generator.py`
- Test: `tests/test_alias_pool.py`

- [ ] **Step 1: 写失败测试，锁定单次 `load_into()` 内的去重行为**

向 `tests/test_alias_pool.py` 中 `SimpleAliasGeneratorProducerTests` 追加：

```python
    def test_simple_generator_deduplicates_aliases_within_one_load(self):
        manager = AliasEmailPoolManager(task_id="task-simple-generator-dedup")
        producer = SimpleAliasGeneratorProducer(
            source_id="simple-1",
            prefix="prefix.",
            suffix="@manyme.com",
            mailbox_email="real@example.com",
            count=5,
            middle_length_min=1,
            middle_length_max=1,
        )

        generated = iter(["a", "a", "b", "b", "c", "d", "e"])
        with mock.patch.object(
            producer,
            "_generate_alias_email",
            side_effect=lambda: f"prefix.{next(generated)}@manyme.com",
        ):
            producer.load_into(manager)

        leases = [manager.acquire_alias() for _ in range(5)]
        self.assertEqual(
            [lease.alias_email for lease in leases],
            [
                "prefix.a@manyme.com",
                "prefix.b@manyme.com",
                "prefix.c@manyme.com",
                "prefix.d@manyme.com",
                "prefix.e@manyme.com",
            ],
        )
```

- [ ] **Step 2: 运行测试，确认先失败**

Run:

```bash
python -m unittest discover -s tests -p "test_alias_pool.py" -v
```

Expected:
- 如果当前去重未生效则 FAIL
- 若已通过，说明 Task 2 的实现已自然满足该契约，可直接进入下一步并保留测试

- [ ] **Step 3: 只在需要时做最小实现修正**

如果测试已经通过，不修改生产代码。若失败，仅修正 `load_into()` 内的去重循环，确保：

```python
seen: set[str] = set()
while len(seen) < self.count:
    alias_email = self._generate_alias_email()
    if alias_email in seen:
        continue
    seen.add(alias_email)
    manager.add_lease(...)
```

不要引入跨 source 或跨任务去重。

- [ ] **Step 4: 运行测试，确认通过**

Run:

```bash
python -m unittest discover -s tests -p "test_alias_pool.py" -v
```

Expected:
- PASS

- [ ] **Step 5: Commit**

```bash
git add core/alias_pool/simple_generator.py tests/test_alias_pool.py
git commit -m "test: cover simple generator alias deduplication"
```

### Task 4: 在 task alias pool 装配链路中接入 `simple_generator`

**Files:**
- Modify: `api/tasks.py`
- Modify: `tests/test_register_task_controls.py`
- Test: `tests/test_register_task_controls.py`

- [ ] **Step 1: 写失败测试，锁定 `_run_register()` 的 alias pool 装配会实例化 `simple_generator`**

参考现有 `tests/test_register_task_controls.py` 的 mock/stub 风格，新增一个最小测试。测试核心目标不是完整注册，而是验证：当 `req.extra["sources"]` 包含 `simple_generator` 时，任务运行路径会把它装入 mailbox 的 `_task_alias_pool`。

可按如下结构编写：

```python
    def test_run_register_builds_task_alias_pool_with_simple_generator_source(self):
        req = tasks.RegisterTaskRequest(
            platform="dummy",
            count=1,
            concurrency=1,
            extra={
                "mail_provider": "cloudmail",
                "cloudmail_alias_enabled": True,
                "sources": [
                    {
                        "id": "simple-1",
                        "type": "simple_generator",
                        "prefix": "msiabc.",
                        "suffix": "@manyme.com",
                        "mailbox_email": "real@example.com",
                        "count": 1,
                        "middle_length_min": 3,
                        "middle_length_max": 3,
                    }
                ],
            },
        )

        # 复用当前文件已有的 dummy platform / mailbox stub 风格
        # 断言 mailbox._task_alias_pool.acquire_alias().source_kind == "simple_generator"
```

如果当前测试文件已经有等价 coverage，可只追加更小的 source-kind 断言，不要重写整套流程。

- [ ] **Step 2: 运行测试，确认先失败**

Run:

```bash
python -m unittest discover -s tests -p "test_register_task_controls.py" -v
```

Expected:
- FAIL
- `simple_generator` source 尚未被 `_build_alias_pool()` 识别

- [ ] **Step 3: 在 `api/tasks.py` 中接入 producer 装配**

在 `_build_alias_pool()` 中增加：

```python
from core.alias_pool.simple_generator import SimpleAliasGeneratorProducer
```

并将 source dispatch 改为：

```python
for source in pool_config.get("sources", []):
    source_type = source.get("type")
    if source_type == "static_list":
        producer = StaticAliasListProducer(
            source_id=str(source.get("id") or "legacy-static"),
            emails=list(source.get("emails") or []),
            mailbox_email=str(source.get("mailbox_email") or "").strip().lower(),
        )
    elif source_type == "simple_generator":
        producer = SimpleAliasGeneratorProducer(
            source_id=str(source.get("id") or "simple-generator"),
            prefix=str(source.get("prefix") or ""),
            suffix=str(source.get("suffix") or "").strip().lower(),
            mailbox_email=str(source.get("mailbox_email") or "").strip().lower(),
            count=int(source.get("count") or 0),
            middle_length_min=int(source.get("middle_length_min") or 3),
            middle_length_max=int(source.get("middle_length_max") or 6),
        )
    else:
        continue

    manager.register_source(producer)
    producer.load_into(manager)
```

不要改 mailbox 消费协议，也不要额外引入异步逻辑。

- [ ] **Step 4: 运行测试，确认通过**

Run:

```bash
python -m unittest discover -s tests -p "test_register_task_controls.py" -v
```

Expected:
- PASS
- 新增 task injection 测试通过

- [ ] **Step 5: Commit**

```bash
git add api/tasks.py tests/test_register_task_controls.py
git commit -m "feat: wire simple generator alias source into task pool"
```

### Task 5: 完整验证本次变更的 alias pool 路径

**Files:**
- Test: `tests/test_alias_pool.py`
- Test: `tests/test_register_task_controls.py`

- [ ] **Step 1: 运行 alias pool 单测**

Run:

```bash
python -m unittest discover -s tests -p "test_alias_pool.py" -v
```

Expected:
- PASS
- 所有 alias pool 相关测试通过

- [ ] **Step 2: 运行 task controls 单测**

Run:

```bash
python -m unittest discover -s tests -p "test_register_task_controls.py" -v
```

Expected:
- PASS

- [ ] **Step 3: 运行 changed-files diagnostics**

Run LSP diagnostics for:

```text
core/alias_pool/config.py
core/alias_pool/simple_generator.py
api/tasks.py
tests/test_alias_pool.py
tests/test_register_task_controls.py
```

Expected:
- zero errors

- [ ] **Step 4: Commit verification state (only if user asked for commit)**

```bash
git status
```

Expected:
- working tree reflects only intended changes

- [ ] **Step 5: Record completion notes**

Document in final handoff:

```text
- simple_generator config normalization added
- SimpleAliasGeneratorProducer added
- task alias pool wiring added
- alias pool + task control tests passed
```
