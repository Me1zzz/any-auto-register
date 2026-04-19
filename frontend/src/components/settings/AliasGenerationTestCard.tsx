import { useEffect, useMemo, useState } from 'react'
import { Alert, Button, Card, Checkbox, Descriptions, Empty, Select, Space, Table, Tag, Typography, theme } from 'antd'

import {
  buildAliasGenerationTestDisplay,
  getAliasGenerationSourceTypeLabel,
  resolveAliasGenerationModeSourceOptions,
  runAliasGenerationTest,
  type AliasGenerationSourceOption,
  type AliasGenerationTestDraftConfig,
  type AliasGenerationTestDisplayStage,
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

function resolveStageStatusMeta(status: string) {
  const normalizedStatus = status.trim().toLowerCase()

  if (
    normalizedStatus === 'ok'
    || normalizedStatus === 'completed'
    || normalizedStatus === 'done'
    || normalizedStatus === 'success'
  ) {
    return { color: 'success' as const, label: '完成' }
  }

  if (
    normalizedStatus === 'running'
    || normalizedStatus === 'processing'
    || normalizedStatus === 'in_progress'
    || normalizedStatus === 'current'
  ) {
    return { color: 'processing' as const, label: '进行中' }
  }

  if (
    normalizedStatus === 'error'
    || normalizedStatus === 'failed'
    || normalizedStatus === 'fail'
  ) {
    return { color: 'error' as const, label: '失败' }
  }

  if (
    normalizedStatus === 'pending'
    || normalizedStatus === 'idle'
    || normalizedStatus === 'waiting'
  ) {
    return { color: 'default' as const, label: '待执行' }
  }

  return {
    color: normalizedStatus ? 'default' as const : 'default' as const,
    label: normalizedStatus || '未知',
  }
}

function renderCopyableMonoText(value: string) {
  if (!value) {
    return '-'
  }

  return (
    <Typography.Text
      copyable={{ text: value }}
      style={{
        fontFamily: 'SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace',
        fontSize: 12,
        wordBreak: 'break-all',
      }}
    >
      {value}
    </Typography.Text>
  )
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
  const { token } = theme.useToken()
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
  const displayResult = useMemo(
    () => (result ? buildAliasGenerationTestDisplay(result) : null),
    [result],
  )

  const selectOptions = useMemo(
    () =>
      modeDetails.sourceOptions.map((source) => ({
        label: `${source.id} (${getAliasGenerationSourceTypeLabel(source.type)})`,
        value: source.id,
      })),
    [modeDetails.sourceOptions],
  )

  const aliasColumns = useMemo(
    () => [
      {
        title: '#',
        width: 56,
        render: (_value: unknown, _record: { key: string; email: string }, index: number) => index + 1,
      },
      {
        title: '别名邮箱',
        dataIndex: 'email',
        render: (value: string) => renderCopyableMonoText(value),
      },
    ],
    [],
  )

  const stageColumns = useMemo(
    () => [
      {
        title: '阶段',
        key: 'stage',
        render: (_value: unknown, stage: AliasGenerationTestDisplayStage) => (
          <Space wrap size={[6, 4]}>
            <Typography.Text strong={stage.isCurrent}>{stage.label || stage.code || '-'}</Typography.Text>
            {stage.isCurrent ? <Tag color="processing">当前</Tag> : null}
            {stage.code ? <Typography.Text type="secondary" style={{ fontSize: 12 }}>{stage.code}</Typography.Text> : null}
          </Space>
        ),
      },
      {
        title: '状态',
        dataIndex: 'status',
        width: 110,
        render: (value: string) => {
          const meta = resolveStageStatusMeta(value)
          return <Tag color={meta.color}>{meta.label}</Tag>
        },
      },
      {
        title: '说明',
        dataIndex: 'detail',
        render: (value: string) => (
          <Typography.Text type="secondary">{value || '-'}</Typography.Text>
        ),
      },
    ],
    [],
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

  const hasFailure = Boolean(
    displayResult
    && (
      !displayResult.ok
      || displayResult.failure.reason
      || displayResult.failure.stageCode
      || displayResult.failure.stageLabel
    ),
  )
  const aliasCount = displayResult?.aliases.length || (displayResult?.summaryAliasEmail ? 1 : 0)
  const failureStageText = displayResult?.failure.stageLabel
    || displayResult?.failure.stageCode
    || displayResult?.currentStage.label
    || displayResult?.currentStage.code
    || '未返回阶段'
  const failureReasonText = displayResult?.failure.reason || displayResult?.error || '未知错误'
  const summaryAlertType = !displayResult
    ? 'info'
    : hasFailure
      ? 'error'
      : 'success'

  return (
    <Card
      title="别名邮件生成测试"
      extra={<Typography.Text type="secondary" style={{ fontSize: 12 }}>用于单独验证当前 alias source 是否可生成邮箱</Typography.Text>}
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

        {displayResult ? (
          <div>
            <Space direction="vertical" style={{ width: '100%' }} size={12}>
              <Alert
                type={summaryAlertType}
                showIcon
                message={hasFailure ? `测试失败：${failureStageText}` : `测试完成：账号 1 个 / 别名 ${aliasCount} 个`}
                description={(
                  <Space direction="vertical" size={8} style={{ width: '100%' }}>
                    <Space wrap size={[8, 6]}>
                      <Tag color="blue">{displayResult.sourceId || '未返回 Source ID'}</Tag>
                      <Tag>{getAliasGenerationSourceTypeLabel(displayResult.sourceType)}</Tag>
                      {displayResult.currentStage.label ? (
                        <Tag color={hasFailure ? 'error' : 'processing'}>{displayResult.currentStage.label}</Tag>
                      ) : null}
                      {displayResult.failure.retryable ? <Tag color="warning">可重试</Tag> : null}
                    </Space>
                    {displayResult.summaryAliasEmail ? (
                      <div>
                        <Typography.Text type="secondary">主别名：</Typography.Text>
                        {renderCopyableMonoText(displayResult.summaryAliasEmail)}
                      </div>
                    ) : null}
                    {hasFailure ? (
                      <Typography.Text type="danger">原因：{failureReasonText}</Typography.Text>
                    ) : (
                      <Typography.Text type="secondary">同步请求已完成，以下为本次返回的账号、别名与阶段信息。</Typography.Text>
                    )}
                  </Space>
                )}
              />

              <div>
                <Typography.Text strong>账号信息</Typography.Text>
                <Descriptions column={1} bordered size="small" style={{ marginTop: 8 }}>
                  <Descriptions.Item label="真实邮箱">
                    {renderCopyableMonoText(displayResult.account.realMailboxEmail)}
                  </Descriptions.Item>
                  <Descriptions.Item label="服务邮箱">
                    {renderCopyableMonoText(displayResult.account.serviceEmail)}
                  </Descriptions.Item>
                  <Descriptions.Item label="密码">
                    {renderCopyableMonoText(displayResult.account.password)}
                  </Descriptions.Item>
                  {displayResult.account.username ? (
                    <Descriptions.Item label="用户名">
                      {renderCopyableMonoText(displayResult.account.username)}
                    </Descriptions.Item>
                  ) : null}
                </Descriptions>
              </div>

              <div>
                <Space align="center" size={8}>
                  <Typography.Text strong>别名列表</Typography.Text>
                  <Tag color={displayResult.aliases.length >= 3 ? 'success' : 'default'}>{displayResult.aliases.length} 个</Tag>
                </Space>
                {displayResult.aliases.length > 0 ? (
                  <Table
                    size="small"
                    pagination={false}
                    columns={aliasColumns}
                    dataSource={displayResult.aliases}
                    style={{ marginTop: 8 }}
                  />
                ) : (
                  <Typography.Text type="secondary" style={{ display: 'block', marginTop: 8 }}>
                    当前响应未返回结构化别名列表。
                  </Typography.Text>
                )}
              </div>

              <div>
                <Space align="center" size={8}>
                  <Typography.Text strong>阶段进度</Typography.Text>
                  {displayResult.currentStage.label ? <Tag color={hasFailure ? 'error' : 'processing'}>{displayResult.currentStage.label}</Tag> : null}
                </Space>
                {displayResult.stages.length > 0 ? (
                  <Table
                    size="small"
                    pagination={false}
                    columns={stageColumns}
                    dataSource={displayResult.stages}
                    style={{ marginTop: 8 }}
                  />
                ) : (
                  <Typography.Text type="secondary" style={{ display: 'block', marginTop: 8 }}>
                    当前响应未返回结构化阶段列表，仅保留兼容字段。
                  </Typography.Text>
                )}
              </div>

              {hasFailure ? (
                <Alert
                  type={displayResult.ok ? 'warning' : 'error'}
                  showIcon
                  message={`失败阶段：${failureStageText}`}
                  description={(
                    <Space direction="vertical" size={4}>
                      <Typography.Text>{failureReasonText}</Typography.Text>
                      {displayResult.failure.retryable ? <Typography.Text type="secondary">可重试：是</Typography.Text> : null}
                    </Space>
                  )}
                />
              ) : null}

              {displayResult.captureSummary.length > 0 || displayResult.logs.length > 0 ? (
                <div>
                  <Typography.Text strong>调试细节</Typography.Text>
                  <Space direction="vertical" style={{ width: '100%', marginTop: 8 }} size={8}>
                    {displayResult.captureSummary.length > 0 ? (
                      <div>
                        <Typography.Text type="secondary">抓包摘要（{displayResult.captureSummary.length}）</Typography.Text>
                        <Space direction="vertical" style={{ width: '100%', marginTop: 8 }} size={8}>
                          {displayResult.captureSummary.map((capture, index) => (
                            <pre
                              key={`${index}-${readCaptureText(capture.name) || 'capture'}`}
                              style={{
                                margin: 0,
                                padding: 12,
                                borderRadius: token.borderRadius,
                                border: `1px solid ${token.colorBorder}`,
                                background: token.colorBgElevated,
                                color: token.colorTextSecondary,
                                fontFamily: 'SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace',
                                fontSize: 12,
                                lineHeight: 1.5,
                                whiteSpace: 'pre-wrap',
                                wordBreak: 'break-word',
                                maxHeight: 160,
                                overflow: 'auto',
                              }}
                            >
                              {formatCaptureItem(capture).join('\n')}
                            </pre>
                          ))}
                        </Space>
                      </div>
                    ) : null}

                    {displayResult.logs.length > 0 ? (
                      <div>
                        <Typography.Text type="secondary">日志（{displayResult.logs.length}）</Typography.Text>
                        <pre
                          style={{
                            margin: '8px 0 0',
                            padding: 12,
                            borderRadius: token.borderRadius,
                            border: `1px solid ${token.colorBorder}`,
                            background: token.colorBgElevated,
                            color: token.colorTextSecondary,
                            fontFamily: 'SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace',
                            fontSize: 12,
                            lineHeight: 1.5,
                            whiteSpace: 'pre-wrap',
                            wordBreak: 'break-word',
                            maxHeight: 220,
                            overflow: 'auto',
                          }}
                        >
                          {displayResult.logs.join('\n')}
                        </pre>
                      </div>
                    ) : null}
                  </Space>
                </div>
              ) : null}
            </Space>
          </div>
        ) : null}
      </Space>
    </Card>
  )
}
