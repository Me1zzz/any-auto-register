import { useEffect, useMemo, useState } from 'react'
import { Alert, Button, Card, Checkbox, Descriptions, Empty, Select, Space, Typography } from 'antd'

import {
  resolveAliasGenerationModeSourceOptions,
  runAliasGenerationTest,
  type AliasGenerationSourceOption,
  type AliasGenerationTestDraftConfig,
  type AliasGenerationTestResponse,
} from '@/lib/aliasGenerationTest'

function readCaptureText(value: unknown): string {
  if (typeof value === 'string') {
    return value.trim()
  }
  if (typeof value === 'number' || typeof value === 'boolean') {
    return String(value)
  }
  return ''
}

function formatCaptureItem(capture: Record<string, unknown>): string[] {
  const lines: string[] = []
  const title = readCaptureText(capture.name)
  const method = readCaptureText(capture.method)
  const url = readCaptureText(capture.url)
  const requestSummary = readCaptureText(
    capture.request_summary ?? capture.requestSummary,
  )
  const responseSummary = readCaptureText(
    capture.response_summary ?? capture.responseSummary,
  )
  const capturedAt = readCaptureText(
    capture.captured_at ?? capture.capturedAt,
  )

  if (title) {
    lines.push(title)
  }
  if (method || url) {
    lines.push([method, url].filter(Boolean).join(' '))
  }
  if (requestSummary) {
    lines.push(`请求: ${requestSummary}`)
  }
  if (responseSummary) {
    lines.push(`响应: ${responseSummary}`)
  }
  if (capturedAt) {
    lines.push(`时间: ${capturedAt}`)
  }

  if (lines.length > 0) {
    return lines
  }

  return [JSON.stringify(capture, null, 2)]
}

type Props = {
  draftConfig: AliasGenerationTestDraftConfig
  draftSourceOptions: AliasGenerationSourceOption[]
  savedSourceOptions: AliasGenerationSourceOption[]
}

export default function AliasGenerationTestCard({
  draftConfig,
  draftSourceOptions,
  savedSourceOptions,
}: Props) {
  const [useDraftConfig, setUseDraftConfig] = useState(true)
  const modeDetails = useMemo(
    () =>
      resolveAliasGenerationModeSourceOptions({
        useDraftConfig,
        draftSourceOptions,
        savedSourceOptions,
      }),
    [draftSourceOptions, savedSourceOptions, useDraftConfig],
  )
  const [sourceId, setSourceId] = useState(modeDetails.sourceOptions[0]?.id || '')
  const [loading, setLoading] = useState(false)
  const [requestError, setRequestError] = useState('')
  const [result, setResult] = useState<AliasGenerationTestResponse | null>(null)

  const selectOptions = useMemo(
    () =>
      modeDetails.sourceOptions.map((source) => ({
        label: `${source.id} (${source.type})`,
        value: source.id,
      })),
    [modeDetails.sourceOptions],
  )

  useEffect(() => {
    if (modeDetails.sourceOptions.length === 0) {
      setSourceId('')
      return
    }

    if (!modeDetails.sourceOptions.some((source) => source.id === sourceId)) {
      setSourceId(modeDetails.sourceOptions[0]?.id || '')
    }
  }, [modeDetails.sourceOptions, sourceId])

  const handleRun = async () => {
    if (!sourceId) return

    setLoading(true)
    setRequestError('')
    setResult(null)

    try {
      const response = await runAliasGenerationTest({
        sourceId,
        useDraftConfig,
        config: useDraftConfig ? draftConfig : undefined,
      })
      setResult(response)
    } catch (error) {
      setRequestError(error instanceof Error ? error.message : '请求失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <Card
      title="别名邮件生成测试"
      extra={<span style={{ fontSize: 12, color: '#7a8ba3' }}>用于单独验证当前 alias source 是否可生成邮箱</span>}
      style={{ marginBottom: 16 }}
    >
      <Space direction="vertical" style={{ width: '100%' }} size={12}>
        <Alert
          type="info"
          showIcon
          message={`当前模式：${modeDetails.configLabel}`}
          description={modeDetails.description}
        />

        {modeDetails.sourceOptions.length === 0 ? (
          <Alert
            type="info"
            showIcon
            message="当前没有可测试的 alias source"
            description={modeDetails.emptyDescription}
          />
        ) : null}

        <Select
          value={sourceId || undefined}
          onChange={setSourceId}
          options={selectOptions}
          placeholder="选择要测试的 source"
          disabled={modeDetails.sourceOptions.length === 0}
        />

        <Checkbox
          checked={useDraftConfig}
          onChange={(event) => setUseDraftConfig(event.target.checked)}
        >
          使用当前未保存表单值测试
        </Checkbox>

        <Button
          type="primary"
          onClick={() => {
            void handleRun()
          }}
          loading={loading}
          disabled={!sourceId}
        >
          测试生成别名邮箱
        </Button>

        {requestError ? (
          <Alert type="error" showIcon message="请求失败" description={requestError} />
        ) : null}

        {!result && !requestError ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚未执行测试" />
        ) : null}

        {result?.ok ? (
          <Descriptions column={1} bordered size="small">
            <Descriptions.Item label="Alias">
              {result.aliasEmail || '-'}
            </Descriptions.Item>
            <Descriptions.Item label="真实邮箱">
              {result.realMailboxEmail || '-'}
            </Descriptions.Item>
            <Descriptions.Item label="Source ID">
              {result.sourceId || '-'}
            </Descriptions.Item>
            <Descriptions.Item label="Source Type">
              {result.sourceType || '-'}
            </Descriptions.Item>
            <Descriptions.Item label="Service Email">
              {result.serviceEmail || '-'}
            </Descriptions.Item>
          </Descriptions>
        ) : null}

        {result?.steps?.length ? (
          <div>
            <Typography.Text strong>步骤</Typography.Text>
            <pre
              style={{
                margin: '8px 0 0',
                padding: 12,
                borderRadius: 8,
                background: 'rgba(127,127,127,0.08)',
                fontSize: 12,
                lineHeight: 1.5,
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
              }}
            >
              {result.steps.join('\n')}
            </pre>
          </div>
        ) : null}

        {result?.captureSummary?.length ? (
          <div>
            <Typography.Text strong>Capture</Typography.Text>
            <Space direction="vertical" style={{ width: '100%', marginTop: 8 }} size={8}>
              {result.captureSummary.map((capture, index) => (
                <pre
                  key={`${index}-${readCaptureText(capture.name) || 'capture'}`}
                  style={{
                    margin: 0,
                    padding: 12,
                    borderRadius: 8,
                    background: 'rgba(127,127,127,0.08)',
                    fontSize: 12,
                    lineHeight: 1.5,
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-word',
                  }}
                >
                  {formatCaptureItem(capture).join('\n')}
                </pre>
              ))}
            </Space>
          </div>
        ) : null}

        {result && !result.ok ? (
          <Alert
            type="error"
            showIcon
            message="测试失败"
            description={result.error || '未知错误'}
          />
        ) : null}

        {result?.logs?.length ? (
          <div>
            <Typography.Text strong>日志</Typography.Text>
            <pre
              style={{
                margin: '8px 0 0',
                padding: 12,
                borderRadius: 8,
                background: 'rgba(127,127,127,0.08)',
                fontSize: 12,
                lineHeight: 1.5,
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
              }}
            >
              {result.logs.join('\n')}
            </pre>
          </div>
        ) : null}
      </Space>
    </Card>
  )
}
