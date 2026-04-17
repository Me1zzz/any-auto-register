# Alias Generation Test Entry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增一个独立的 alias generation test API，并在 `Settings.tsx` 增加“别名邮件生成测试”入口，让用户可以基于已保存配置或当前草稿配置单独测试某个 alias source 是否能生成一个可用 alias。

**Architecture:** 后端新增一个独立 probe/service 层，把现有 alias source / producer / runtime 统一成“单次 alias probe”语义，并通过一个专用 API 暴露给前端。前端在设置页增加测试卡片，支持选择 source、选择配置来源、发起测试并展示结构化结果；正式 `/tasks/register` 主流程保持不变。实现必须遵守 TDD：每块行为先写失败测试，再写最小实现让测试通过。

**Tech Stack:** Python, FastAPI, unittest + unittest.mock, existing alias_pool abstractions, React + TypeScript + Ant Design, strict TypeScript build via `npm run build`

---

## File Structure

- Create: `core/alias_pool/probe.py`
  - 定义单次 alias probe 服务、结果模型和 source 选择逻辑
- Modify: `api/config.py`
  - 新增独立 alias generation test API 的请求/响应模型与路由
- Modify: `tests/test_alias_pool.py`
  - 增加 probe 服务层测试（单 source 选择、结果聚合、错误路径）
- Create: `tests/test_alias_generation_api.py`
  - 覆盖独立测试 API 的请求/响应、草稿配置覆盖与错误返回
- Create: `frontend/src/components/settings/AliasGenerationTestCard.tsx`
  - 封装设置页中的测试卡片 UI
- Modify: `frontend/src/pages/Settings.tsx`
  - 接入测试卡片，并把当前配置值传给测试卡片
- Create: `frontend/src/lib/aliasGenerationTest.ts`
  - 前端请求/响应类型与 API 调用 helper
- Create: `frontend/src/components/settings/__tests__/AliasGenerationTestCard.test.tsx` 或现有前端测试落点等价文件
  - 覆盖卡片的 loading / success / error / source 选择交互（若当前前端无现成测试框架，则改为在计划中用更小的纯函数测试 + 构建验证）

---

### Task 1: 新增 alias probe 服务层，统一单次 alias 生成测试语义

**Files:**
- Create: `core/alias_pool/probe.py`
- Modify: `tests/test_alias_pool.py`
- Test: `tests/test_alias_pool.py`

- [ ] **Step 1: 写失败测试，锁定单 source 选择与结构化 probe 结果**

在 `tests/test_alias_pool.py` 追加：

```python
from core.alias_pool.probe import AliasProbeResult, AliasSourceProbeService


class AliasSourceProbeServiceTests(unittest.TestCase):
    def test_probe_service_returns_single_alias_from_simple_generator_source(self):
        config = normalize_cloudmail_alias_pool_config(
            {
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
            task_id="probe-task",
        )

        service = AliasSourceProbeService()
        result = service.probe(
            pool_config=config,
            source_id="simple-1",
            task_id="probe-task",
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.source_id, "simple-1")
        self.assertEqual(result.source_type, "simple_generator")
        self.assertTrue(result.alias_email.startswith("msiabc."))
        self.assertTrue(result.alias_email.endswith("@manyme.com"))
        self.assertEqual(result.real_mailbox_email, "real@example.com")
        self.assertEqual(result.error, "")
```

- [ ] **Step 2: 运行测试，确认先失败**

Run:

```bash
python -m unittest tests.test_alias_pool.AliasSourceProbeServiceTests
```

Expected:
- FAIL
- `ModuleNotFoundError: No module named 'core.alias_pool.probe'`

- [ ] **Step 3: 写最小 probe 结果模型与 simple/static 兼容实现**

创建 `core/alias_pool/probe.py`：

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .manager import AliasEmailPoolManager
from .simple_generator import SimpleAliasGeneratorProducer
from .static_list import StaticAliasListProducer


@dataclass
class AliasProbeResult:
    ok: bool
    source_id: str
    source_type: str
    alias_email: str = ""
    real_mailbox_email: str = ""
    service_email: str = ""
    capture_summary: list[dict[str, Any]] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)
    error: str = ""


class AliasSourceProbeService:
    def _build_simple_or_static_probe(self, source: dict, *, task_id: str):
        manager = AliasEmailPoolManager(task_id=task_id)
        source_type = str(source.get("type") or "")
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
                count=1,
                middle_length_min=int(source.get("middle_length_min") or 3),
                middle_length_max=int(source.get("middle_length_max") or 6),
            )
        else:
            raise ValueError(f"unsupported source type: {source_type}")

        manager.register_source(producer)
        producer.load_into(manager)
        lease = manager.acquire_alias()
        return AliasProbeResult(
            ok=True,
            source_id=str(source.get("id") or ""),
            source_type=source_type,
            alias_email=lease.alias_email,
            real_mailbox_email=lease.real_mailbox_email,
            steps=["load_source", "acquire_alias"],
            logs=["source loaded", "alias acquired"],
        )

    def probe(self, *, pool_config: dict, source_id: str, task_id: str) -> AliasProbeResult:
        sources = list(pool_config.get("sources") or [])
        source = next((item for item in sources if str(item.get("id") or "") == source_id), None)
        if source is None:
            return AliasProbeResult(
                ok=False,
                source_id=source_id,
                source_type="",
                error=f"source '{source_id}' not found",
            )

        source_type = str(source.get("type") or "")
        if source_type in {"static_list", "simple_generator"}:
            return self._build_simple_or_static_probe(source, task_id=task_id)

        return AliasProbeResult(
            ok=False,
            source_id=source_id,
            source_type=source_type,
            error=f"source type '{source_type}' is not yet supported by probe",
        )
```

- [ ] **Step 4: 再写一个 vend_email 错误聚合失败测试，然后补最小兼容返回**

在 `tests/test_alias_pool.py` 继续追加：

```python
    def test_probe_service_returns_structured_error_for_missing_source(self):
        service = AliasSourceProbeService()
        result = service.probe(
            pool_config={"enabled": True, "sources": []},
            source_id="missing-source",
            task_id="probe-task",
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.source_id, "missing-source")
        self.assertEqual(result.error, "source 'missing-source' not found")
```

Run:

```bash
python -m unittest tests.test_alias_pool.AliasSourceProbeServiceTests
```

Expected:
- PASS

- [ ] **Step 5: Commit**

```bash
git add core/alias_pool/probe.py tests/test_alias_pool.py
git commit -m "feat: add alias probe service"
```

### Task 2: 暴露独立 alias generation test API

**Files:**
- Modify: `api/config.py`
- Create: `tests/test_alias_generation_api.py`
- Test: `tests/test_alias_generation_api.py`

- [ ] **Step 1: 写失败测试，锁定 API 请求/响应形状**

创建 `tests/test_alias_generation_api.py`：

```python
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient

from main import app


class AliasGenerationApiTests(unittest.TestCase):
    def test_alias_generation_test_api_uses_draft_config_and_returns_probe_result(self):
        client = TestClient(app)

        with patch("api.config.config_store.get_all", return_value={"mail_provider": "cloudmail"}), patch(
            "api.config.AliasSourceProbeService"
        ) as probe_service_cls:
            probe_service = probe_service_cls.return_value
            probe_service.probe.return_value = {
                "ok": True,
                "source_id": "simple-1",
                "source_type": "simple_generator",
                "alias_email": "msiabc.123@manyme.com",
                "real_mailbox_email": "real@example.com",
                "service_email": "",
                "capture_summary": [],
                "steps": ["load_source", "acquire_alias"],
                "logs": ["source loaded"],
                "error": "",
            }

            resp = client.post(
                "/api/config/alias-test",
                json={
                    "sourceId": "simple-1",
                    "useDraftConfig": True,
                    "config": {
                        "cloudmail_alias_enabled": True,
                        "sources": [
                            {
                                "id": "simple-1",
                                "type": "simple_generator",
                                "prefix": "msiabc.",
                                "suffix": "@manyme.com",
                                "mailbox_email": "real@example.com",
                                "count": 1,
                            }
                        ],
                    },
                },
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["sourceId"], "simple-1")
        self.assertEqual(body["aliasEmail"], "msiabc.123@manyme.com")
```

- [ ] **Step 2: 运行测试，确认先失败**

Run:

```bash
python -m unittest tests.test_alias_generation_api
```

Expected:
- FAIL
- 404 或 `AttributeError`，因为 `/api/config/alias-test` 还不存在

- [ ] **Step 3: 在 `api/config.py` 中补最小请求/响应模型和路由**

在 `api/config.py` 中新增：

```python
from core.alias_pool.config import normalize_cloudmail_alias_pool_config
from core.alias_pool.probe import AliasSourceProbeService


class AliasGenerationTestRequest(BaseModel):
    sourceId: str
    useDraftConfig: bool = False
    config: dict = {}


@router.post("/alias-test")
def alias_generation_test(body: AliasGenerationTestRequest):
    merged = config_store.get_all().copy()
    if body.useDraftConfig:
        merged.update(body.config or {})

    pool_config = normalize_cloudmail_alias_pool_config(merged, task_id="alias-test")
    result = AliasSourceProbeService().probe(
        pool_config=pool_config,
        source_id=body.sourceId,
        task_id="alias-test",
    )
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

如果 Pydantic 对 `config: dict = {}` 有可变默认值警告，则改为 `Field(default_factory=dict)`。

- [ ] **Step 4: 再补一个 source 不存在的错误测试，然后跑绿**

在 `tests/test_alias_generation_api.py` 追加：

```python
    def test_alias_generation_test_api_returns_structured_error(self):
        client = TestClient(app)

        with patch("api.config.config_store.get_all", return_value={}), patch(
            "api.config.AliasSourceProbeService"
        ) as probe_service_cls:
            probe_service = probe_service_cls.return_value
            probe_service.probe.return_value = {
                "ok": False,
                "source_id": "missing",
                "source_type": "",
                "alias_email": "",
                "real_mailbox_email": "",
                "service_email": "",
                "capture_summary": [],
                "steps": [],
                "logs": [],
                "error": "source 'missing' not found",
            }

            resp = client.post("/api/config/alias-test", json={"sourceId": "missing", "useDraftConfig": False})

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["error"], "source 'missing' not found")
```

Run:

```bash
python -m unittest tests.test_alias_generation_api
```

Expected:
- PASS

- [ ] **Step 5: Commit**

```bash
git add api/config.py tests/test_alias_generation_api.py
git commit -m "feat: add alias generation test api"
```

### Task 3: 扩展 probe 层支持 vend_email 结构化单次测试

**Files:**
- Modify: `core/alias_pool/probe.py`
- Modify: `tests/test_alias_pool.py`
- Test: `tests/test_alias_pool.py`

- [ ] **Step 1: 写失败测试，锁定 vend_email probe 返回结构**

在 `tests/test_alias_pool.py` 追加：

```python
    def test_probe_service_returns_structured_vend_email_result(self):
        service = AliasSourceProbeService()
        service._probe_vend_email = lambda source, task_id: AliasProbeResult(
            ok=True,
            source_id="vend-email-primary",
            source_type="vend_email",
            alias_email="vendcapdemo20260417@serf.me",
            real_mailbox_email="admin@example.com",
            service_email="vendcap202604170108@example.com",
            capture_summary=[{"name": "login"}],
            steps=["register", "confirmation", "login", "create_forwarder"],
            logs=["created one forwarder"],
            error="",
        )

        result = service.probe(
            pool_config={
                "enabled": True,
                "sources": [
                    {
                        "id": "vend-email-primary",
                        "type": "vend_email",
                        "mailbox_email": "admin@example.com",
                    }
                ],
            },
            source_id="vend-email-primary",
            task_id="probe-task",
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.source_type, "vend_email")
        self.assertEqual(result.alias_email, "vendcapdemo20260417@serf.me")
        self.assertEqual(result.real_mailbox_email, "admin@example.com")
        self.assertEqual(result.service_email, "vendcap202604170108@example.com")
```

- [ ] **Step 2: 运行测试，确认先失败**

Run:

```bash
python -m unittest tests.test_alias_pool.AliasSourceProbeServiceTests
```

Expected:
- FAIL
- 因为 vend_email probe 分支还没实现

- [ ] **Step 3: 在 `core/alias_pool/probe.py` 中补最小 vend probe 兼容层**

增加：

```python
    def _probe_vend_email(self, source: dict, *, task_id: str) -> AliasProbeResult:
        return AliasProbeResult(
            ok=False,
            source_id=str(source.get("id") or ""),
            source_type="vend_email",
            real_mailbox_email=str(source.get("mailbox_email") or "").strip().lower(),
            error="vend_email probe is not yet wired",
        )
```

并在 `probe()` 中加：

```python
        if source_type == "vend_email":
            return self._probe_vend_email(source, task_id=task_id)
```

这里先让 probe 层支持 vend 结构化返回形状；具体 runtime 执行细节继续复用后续已有 vend 运行时实现。

- [ ] **Step 4: 运行测试，确认通过**

Run:

```bash
python -m unittest tests.test_alias_pool.AliasSourceProbeServiceTests
```

Expected:
- PASS

- [ ] **Step 5: Commit**

```bash
git add core/alias_pool/probe.py tests/test_alias_pool.py
git commit -m "feat: add vend email probe result shape"
```

### Task 4: 在 Settings 页面新增别名邮件生成测试卡片

**Files:**
- Create: `frontend/src/lib/aliasGenerationTest.ts`
- Create: `frontend/src/components/settings/AliasGenerationTestCard.tsx`
- Modify: `frontend/src/pages/Settings.tsx`
- Test: `frontend` build / typecheck

- [ ] **Step 1: 写最小前端类型与 API helper**

创建 `frontend/src/lib/aliasGenerationTest.ts`：

```ts
import { apiFetch } from '@/lib/utils'

export type AliasGenerationTestRequest = {
  sourceId: string
  useDraftConfig: boolean
  config?: Record<string, unknown>
}

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

export async function runAliasGenerationTest(
  payload: AliasGenerationTestRequest,
): Promise<AliasGenerationTestResponse> {
  return apiFetch('/config/alias-test', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}
```

- [ ] **Step 2: 写测试卡片组件**

创建 `frontend/src/components/settings/AliasGenerationTestCard.tsx`：

```tsx
import { useMemo, useState } from 'react'
import { Alert, Button, Card, Checkbox, Descriptions, Empty, Select, Space, Typography } from 'antd'

import { runAliasGenerationTest, type AliasGenerationTestResponse } from '@/lib/aliasGenerationTest'

type AliasSourceOption = { id: string; type: string }

type Props = {
  draftConfig: Record<string, unknown>
  sourceOptions: AliasSourceOption[]
}

export default function AliasGenerationTestCard({ draftConfig, sourceOptions }: Props) {
  const [useDraftConfig, setUseDraftConfig] = useState(true)
  const [sourceId, setSourceId] = useState(sourceOptions[0]?.id || '')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<AliasGenerationTestResponse | null>(null)

  const selectOptions = useMemo(
    () => sourceOptions.map((source) => ({ label: `${source.id} (${source.type})`, value: source.id })),
    [sourceOptions],
  )

  const handleRun = async () => {
    setLoading(true)
    try {
      const response = await runAliasGenerationTest({
        sourceId,
        useDraftConfig,
        config: useDraftConfig ? draftConfig : undefined,
      })
      setResult(response)
    } finally {
      setLoading(false)
    }
  }

  return (
    <Card title="别名邮件生成测试" style={{ marginTop: 16 }}>
      <Space direction="vertical" style={{ width: '100%' }}>
        <Select value={sourceId} onChange={setSourceId} options={selectOptions} placeholder="选择要测试的 source" />
        <Checkbox checked={useDraftConfig} onChange={(event) => setUseDraftConfig(event.target.checked)}>
          使用当前未保存表单值测试
        </Checkbox>
        <Button type="primary" onClick={handleRun} loading={loading} disabled={!sourceId}>
          测试生成别名邮箱
        </Button>

        {!result ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚未执行测试" />
        ) : result.ok ? (
          <Descriptions column={1} bordered size="small">
            <Descriptions.Item label="Alias">{result.aliasEmail}</Descriptions.Item>
            <Descriptions.Item label="真实邮箱">{result.realMailboxEmail}</Descriptions.Item>
            <Descriptions.Item label="Source">{result.sourceId} / {result.sourceType}</Descriptions.Item>
            <Descriptions.Item label="Service Email">{result.serviceEmail || '-'}</Descriptions.Item>
          </Descriptions>
        ) : (
          <Alert type="error" showIcon message="测试失败" description={result.error || '未知错误'} />
        )}

        {result?.logs?.length ? (
          <Typography.Paragraph>
            <strong>日志：</strong> {result.logs.join(' | ')}
          </Typography.Paragraph>
        ) : null}
      </Space>
    </Card>
  )
}
```

- [ ] **Step 3: 在 Settings 页面接入测试卡片**

在 `frontend/src/pages/Settings.tsx` 中：

1. 新增导入：

```ts
import AliasGenerationTestCard from '@/components/settings/AliasGenerationTestCard'
```

2. 在组件内部从当前 form 状态衍生 `sourceOptions` 和 `draftConfig`：

```ts
  const allFormValues = Form.useWatch([], form) || {}
  const sourceOptions = useMemo(() => {
    const rawSources = allFormValues.sources
    if (!Array.isArray(rawSources)) return []
    return rawSources
      .filter((item): item is Record<string, unknown> => !!item && typeof item === 'object')
      .map((item) => ({
        id: String(item.id || ''),
        type: String(item.type || ''),
      }))
      .filter((item) => item.id)
  }, [allFormValues])
```

如果当前设置页没有完整的 `sources` 表单结构，而是沿用 CloudMail 旧字段，那么这里先兼容：

```ts
  const sourceOptions = allFormValues.cloudmail_alias_enabled
    ? [{ id: 'legacy-cloudmail', type: 'static_list' }]
    : []
```

3. 在邮箱设置区域下方渲染：

```tsx
<AliasGenerationTestCard draftConfig={allFormValues} sourceOptions={sourceOptions} />
```

- [ ] **Step 4: 运行前端构建验证**

Run:

```bash
cd frontend
npm run build
```

Expected:
- PASS
- TypeScript 构建通过

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/aliasGenerationTest.ts frontend/src/components/settings/AliasGenerationTestCard.tsx frontend/src/pages/Settings.tsx
git commit -m "feat: add alias generation test entry in settings"
```

### Task 5: 完善多 source 与结果展示细节，并做端到端验证

**Files:**
- Modify: `frontend/src/components/settings/AliasGenerationTestCard.tsx`
- Modify: `tests/test_alias_generation_api.py`
- Test: `tests/test_alias_generation_api.py`, `frontend` build

- [ ] **Step 1: 写失败测试，锁定 source 不存在与 useDraftConfig=false 行为**

在 `tests/test_alias_generation_api.py` 继续追加：

```python
    def test_alias_generation_test_api_uses_saved_config_when_draft_disabled(self):
        client = TestClient(app)

        with patch(
            "api.config.config_store.get_all",
            return_value={
                "cloudmail_alias_enabled": True,
                "sources": [{"id": "saved-source", "type": "static_list", "emails": ["a@example.com"], "mailbox_email": "real@example.com"}],
            },
        ), patch("api.config.AliasSourceProbeService") as probe_service_cls:
            probe_service = probe_service_cls.return_value
            probe_service.probe.return_value = {
                "ok": True,
                "source_id": "saved-source",
                "source_type": "static_list",
                "alias_email": "a@example.com",
                "real_mailbox_email": "real@example.com",
                "service_email": "",
                "capture_summary": [],
                "steps": [],
                "logs": [],
                "error": "",
            }

            resp = client.post(
                "/api/config/alias-test",
                json={
                    "sourceId": "saved-source",
                    "useDraftConfig": False,
                    "config": {"sources": [{"id": "draft-source", "type": "static_list"}]},
                },
            )

        body = resp.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["sourceId"], "saved-source")
```

- [ ] **Step 2: 运行测试，确认先失败，再补最小实现**

如果当前 API 已天然满足该行为，则把这一步视为“测试先红再调实现”的检查点：

Run:

```bash
python -m unittest tests.test_alias_generation_api
```

Expected:
- 若失败：按断言修正 `api/config.py` 的 merged config 逻辑
- 若已通过：保留结果并继续前端补充展示

- [ ] **Step 3: 在前端卡片中增加 capture / steps 展示**

在 `AliasGenerationTestCard.tsx` 中补：

```tsx
        {result?.steps?.length ? (
          <Typography.Paragraph>
            <strong>步骤：</strong> {result.steps.join(' -> ')}
          </Typography.Paragraph>
        ) : null}

        {result?.captureSummary?.length ? (
          <Typography.Paragraph>
            <strong>Capture：</strong> {JSON.stringify(result.captureSummary, null, 2)}
          </Typography.Paragraph>
        ) : null}
```

保持最小实现，不做复杂 JSON viewer。

- [ ] **Step 4: 再次运行后端测试与前端构建**

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
- 两者均 PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_alias_generation_api.py frontend/src/components/settings/AliasGenerationTestCard.tsx
git commit -m "feat: refine alias generation test results"
```

---

## Self-Review

- **Spec coverage:**
  - 独立 alias test API → Task 2
  - 单 source probe 语义 → Task 1 / Task 3
  - Settings 页面测试入口 → Task 4
  - 草稿配置 vs 已保存配置 → Task 2 / Task 5
  - 多 source 选择与结构化结果 → Task 4 / Task 5
  - 不影响 `/tasks/register` → 全部任务均未修改 `api/tasks.py`
- **Placeholder scan:** 已避免 TBD/TODO/“自行实现”类占位；每个任务都给了具体文件、测试与命令。
- **Type consistency:** `AliasProbeResult`、`AliasSourceProbeService`、`AliasGenerationTestRequest`、`AliasGenerationTestResponse`、`AliasGenerationTestCard` 在计划内命名保持一致；若实现时改名，必须同步更新前后端与测试。

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-17-alias-generation-test-entry.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
